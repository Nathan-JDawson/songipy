"""Internal-API driver for the Spotify web player's folder feature (local-only).

The Spotify Web API exposes no folder endpoints, so the ``organize`` command
talks to the web player's **rootlist** internal API instead of scraping the
DOM. The endpoints live on host ``https://spclient.wg.spotify.com`` under
``/playlist/v2/user/{username}`` and are driven from the logged-in page via
``fetch`` (see :class:`PlaywrightFolderDriver`).

By default the driver launches Playwright's bundled Chromium with a dedicated
logged-in profile; set ``SPOTIFY_CHROME_CHANNEL`` (e.g. ``"chrome"`` or
``"msedge"``) to use an installed browser instead. This module is deliberately
NOT exercised by the automated tests (the parsing logic lives in the pure
``app.rootlist`` module and IS unit-tested).
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote_plus

from playwright.sync_api import TimeoutError, sync_playwright

from app.rootlist import parse_rootlist_items

logger = logging.getLogger(__name__)

_SPCLIENT_HOST = "https://spclient.wg.spotify.com"
_PATHFINDER_FRAGMENT = "api-partner.spotify.com/pathfinder"
_REFERER = "https://open.spotify.com/"

# The four headers the web player sends on page-load pathfinder requests and
# that the spclient rootlist calls reuse; the rest are set statically.
_CAPTURED_HEADERS = (
    "authorization",
    "client-token",
    "spotify-app-version",
    "app-platform",
)

# Runs inside the page context so the browser's own session/CORS rules apply.
_JS_FETCH = """
async (args) => {
  const res = await fetch(args.url, {
    method: args.method,
    headers: args.headers,
    body: args.body,
  });
  const text = await res.text();
  let json = null;
  try { json = text ? JSON.parse(text) : null; } catch (err) { json = text; }
  return { ok: res.ok, status: res.status, json };
}
"""


class FolderSyncError(RuntimeError):
    """Raised when the Spotify web session cannot be driven (login wall, etc.)."""


class RootlistError(FolderSyncError):
    """Raised when a rootlist API call fails (non-2xx) or returns bad data."""


@dataclass(frozen=True)
class DriverConfig:
    """Configuration for the Playwright rootlist driver."""

    user_data_dir: str
    # None -> Playwright's bundled Chromium (no `channel`); set to e.g.
    # "chrome" or "msedge" to use an installed browser via Playwright's channel.
    channel: str | None = None
    headful: bool = True
    base_url: str = "https://open.spotify.com"
    timeout_ms: int = 30_000
    # Optional override for the account username used in spclient URLs. The
    # caller (the ``organize`` CLI) always sets it, from ``SPOTIFY_USERNAME`` or
    # ``spotify.me()``; the driver itself never tries to guess it.
    username: str | None = None


@runtime_checkable
class FolderDriver(Protocol):
    """Interface the ``organize`` command relies on (swappable for testing)."""

    def open(self) -> None: ...

    def list_folders(self) -> dict[tuple[str, ...], str]: ...

    def list_placements(self) -> dict[str, tuple[str, ...] | None]: ...

    def create_folder(self, path: tuple[str, ...], name: str) -> str: ...

    def move_playlist(self, playlist_uri: str, to: str | None) -> None: ...

    def close(self) -> None: ...


class PlaywrightFolderDriver:
    """Concrete :class:`FolderDriver` backed by the rootlist internal API."""

    def __init__(self, config: DriverConfig) -> None:
        self._cfg = config
        self._playwright: Any = None
        self._context: Any = None
        self._page: Any = None
        self._headers: dict[str, str] = {}
        self._username: str = ""
        self._base: str = ""
        self._rootlist_data: Any = None

    # -- lifecycle -----------------------------------------------------------

    def open(self) -> None:
        """Launch the logged-in profile, capture auth headers, resolve username."""
        self._playwright = sync_playwright().start()
        try:
            # Only pass `channel` when set so Playwright's bundled Chromium is
            # used by default (passing channel=None would disable it).
            launch_kwargs: dict[str, Any] = {}
            if self._cfg.channel:
                launch_kwargs["channel"] = self._cfg.channel
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=self._cfg.user_data_dir,
                headless=not self._cfg.headful,
                **launch_kwargs,
            )
        except Exception:
            self._playwright.stop()
            self._playwright = None
            raise
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self._page.on("request", self._on_request)
        self._page.goto(self._cfg.base_url, wait_until="domcontentloaded")
        self._wait_for_auth_headers()
        self._username = self._cfg.username or ""
        if not self._username:
            raise FolderSyncError(
                "could not determine the Spotify username; set SPOTIFY_USERNAME "
                "or log into the SPOTIFY_CHROME_PROFILE profile and retry"
            )
        self._base = f"{_SPCLIENT_HOST}/playlist/v2/user/{self._username}"

    def close(self) -> None:
        """Close the browser context and stop Playwright."""
        try:
            if self._context is not None:
                self._context.close()
        finally:
            if self._playwright is not None:
                self._playwright.stop()
            self._context = None
            self._page = None
            self._headers = {}
            self._username = ""
            self._base = ""
            self._rootlist_data = None
            self._playwright = None

    # -- read state ----------------------------------------------------------

    def list_folders(self) -> dict[tuple[str, ...], str]:
        """Return ``{folder_path: start_group_uri}`` from the rootlist.

        ``folder_path`` is a tuple of unquoted folder names (``("My Shit",)``);
        ``start_group_uri`` is the stable ``spotify:start-group:<hash>``
        reference (no ``:<name>`` suffix).
        """
        items = self._get_rootlist().get("contents", {}).get("items", [])
        folders, _ = parse_rootlist_items(items)
        return folders

    def list_placements(self) -> dict[str, tuple[str, ...] | None]:
        """Return ``{playlist_uri: folder_path}`` from the rootlist.

        ``None`` means the playlist sits at the library root.
        """
        items = self._get_rootlist().get("contents", {}).get("items", [])
        _, placements = parse_rootlist_items(items)
        return placements

    # -- write operations ----------------------------------------------------

    def create_folder(self, path: tuple[str, ...], name: str) -> str:
        """Create a folder named ``name`` at the top of the library.

        ``path`` is accepted for :class:`FolderDriver` compatibility but ignored:
        the MVP only creates flat top-level folders, so the delta always uses
        ``addFirst: true`` regardless of ``path``. Returns the stable
        ``spotify:start-group:<hash>`` URI for the new folder.
        """
        del path  # MVP: flat folders only, path is unused
        hash_ = secrets.token_hex(8)
        timestamp = str(int(time.time() * 1000))
        payload = {
            "deltas": [
                {
                    "ops": [
                        {
                            "kind": "ADD",
                            "add": {
                                "items": [
                                    {
                                        "uri": (
                                            f"spotify:start-group:{hash_}:"
                                            f"{quote_plus(name, safe='')}"
                                        ),
                                        "attributes": {"timestamp": timestamp},
                                    },
                                    {
                                        "uri": f"spotify:end-group:{hash_}",
                                        "attributes": {"timestamp": timestamp},
                                    },
                                ],
                                "addFirst": True,
                            },
                        }
                    ],
                    "info": {"source": {"client": "WEBPLAYER"}},
                }
            ]
        }
        self._request("POST", "/rootlist/changes", payload=payload)
        self._rootlist_data = None
        return f"spotify:start-group:{hash_}"

    def move_playlist(self, playlist_uri: str, to: str | None) -> None:
        """Move ``playlist_uri`` after ``to`` (a start-group URI) or to the root.

        When ``to`` is ``None`` the playlist is moved to the library root via
        ``addFirst: true``; otherwise it is inserted directly after the folder's
        ``spotify:start-group:<hash>`` URI.
        """
        if to is None:
            mov: dict[str, Any] = {
                "items": [{"uri": playlist_uri, "attributes": {}}],
                "addFirst": True,
            }
        else:
            mov = {
                "items": [{"uri": playlist_uri, "attributes": {}}],
                "addAfterItem": {"uri": to, "attributes": {}},
            }
        payload = {
            "deltas": [
                {
                    "ops": [{"kind": "MOV", "mov": mov}],
                    "info": {"source": {"client": "WEBPLAYER"}},
                }
            ]
        }
        self._request("POST", "/rootlist/changes", payload=payload)
        self._rootlist_data = None

    # -- internal helpers ----------------------------------------------------

    def _on_request(self, request: Any) -> None:
        """Accumulate auth headers from any pathfinder request.

        The four headers can be spread across several page-load requests, so
        each pathfinder request contributes whatever it carries and the missing
        keys are filled in by later requests.
        """
        if _PATHFINDER_FRAGMENT not in request.url:
            return
        headers = {key.lower(): value for key, value in request.headers.items()}
        for key in _CAPTURED_HEADERS:
            if key not in self._headers and key in headers:
                self._headers[key] = headers[key]

    def _wait_for_auth_headers(self) -> None:
        """Wait until pathfinder requests carry all four auth headers.

        Uses ``page.wait_for_event`` (which pumps the sync dispatcher) instead
        of ``time.sleep``, so the request handler actually runs. Returns as soon
        as every header has been seen on any pathfinder request.
        """
        deadline = time.monotonic() + self._cfg.timeout_ms / 1000
        while time.monotonic() < deadline:
            if all(key in self._headers for key in _CAPTURED_HEADERS):
                return
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                break
            try:
                self._page.wait_for_event(
                    "request",
                    predicate=lambda request: _PATHFINDER_FRAGMENT in request.url,
                    timeout=remaining_ms,
                )
            except TimeoutError:
                break
        missing = [key for key in _CAPTURED_HEADERS if key not in self._headers]
        raise FolderSyncError(
            f"did not capture all required pathfinder headers ({', '.join(missing)}) "
            f"on {self._cfg.base_url}; log into the SPOTIFY_CHROME_PROFILE profile "
            "once manually, then retry"
        )

    def _api_headers(self, *, has_body: bool) -> dict[str, str]:
        headers = {
            "Authorization": self._headers.get("authorization", ""),
            "client-token": self._headers.get("client-token", ""),
            "spotify-app-version": self._headers.get("spotify-app-version", ""),
            "app-platform": self._headers.get("app-platform", ""),
            "Accept": "application/json",
            "Referer": _REFERER,
        }
        if has_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _get_rootlist(self) -> Any:
        if self._rootlist_data is None:
            self._rootlist_data = self._request(
                "GET",
                "/rootlist?decorate=revision,length,attributes,timestamp,owner,capabilities",
            )
        return self._rootlist_data

    def _request(self, method: str, path: str, *, payload: dict[str, Any] | None = None) -> Any:
        url = f"{self._base}{path}"
        body = json.dumps(payload) if payload is not None else None
        result = self._page.evaluate(
            _JS_FETCH,
            {
                "url": url,
                "method": method,
                "headers": self._api_headers(has_body=payload is not None),
                "body": body,
            },
        )
        if not result.get("ok"):
            raise RootlistError(
                f"rootlist {method} {path} failed (HTTP {result.get('status')}): "
                f"{result.get('json')}"
            )
        return result.get("json")
