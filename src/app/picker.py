"""Local web app: pick recently-listened albums and generate a Spotify playlist.

This module owns the FastAPI app and its routes; all pure logic lives in
``picker_logic``. Network calls go through the injected ``spotify_factory`` and
the local DB is injected via ``create_app(db=...)`` so tests can run against
in-memory SQLite and a monkeypatched Spotify client.

The password gate (``PICKER_PASSWORD``) is deliberately an *inconvenience* gate
for a trusted LAN, not real security: plain HTTP, a session cookie, constant-time
password compare only. It exists to keep casual visitors from generating
playlists on your account; anyone on the LAN who knows the URL and the password
can use it. Set it empty to disable the gate entirely.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app import api, auth, config, library, picker_logic, playlists
from app import db as db_module

logger = logging.getLogger(__name__)

COOKIE_NAME = "picker_session"

_HTML_DIR = Path(__file__).resolve().parent / "static"

LOGIN_FORM = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Songipy Picker</title>
    <style>
      body { font-family: system-ui, sans-serif; display: flex; align-items: center;
             justify-content: center; min-height: 100vh; margin: 0; background: #121212;
             color: #fff; }
      form { background: #181818; padding: 2rem; border-radius: 8px; width: 280px; }
      label { display: block; margin-bottom: .5rem; }
      input { width: 100%; padding: .5rem; box-sizing: border-box; border-radius: 4px;
              border: 1px solid #333; }
      button { margin-top: 1rem; width: 100%; padding: .6rem; border: 0; border-radius: 4px;
               background: #1db954; color: #fff; font-weight: 600; cursor: pointer; }
    </style>
  </head>
  <body>
    <form method="post" action="/login">
      <h1>Songipy Picker</h1>
      <label for="password">Password</label>
      <input type="password" id="password" name="password" autofocus
             autocomplete="current-password">
      <button type="submit">Unlock</button>
    </form>
  </body>
</html>
"""


def _load_picker_html() -> str:
    """Return the picker page markup from ``static/picker.html``."""
    path = _HTML_DIR / "picker.html"
    return path.read_text(encoding="utf-8")


# --- password gate -------------------------------------------------------


def _sign(nonce: str) -> str:
    """Sign a nonce with the picker password as the HMAC key."""
    secret = (config.get_settings().picker_password or "").encode()
    return hmac.new(secret, nonce.encode(), hashlib.sha256).hexdigest()


def _valid_token(token: str) -> bool:
    """Return True if *token* carries a valid ``nonce:signature`` signature."""
    if ":" not in token:
        return False
    nonce, sig = token.split(":", 1)
    return hmac.compare_digest(sig, _sign(nonce))


def _require_auth(request: Request) -> None:
    """FastAPI dependency: 401 unless the request carries a valid session cookie.

    When ``PICKER_PASSWORD`` is unset/empty the gate is disabled entirely.
    """
    if not config.get_settings().picker_password:
        return
    token = request.cookies.get(COOKIE_NAME)
    if not token or not _valid_token(token):
        raise HTTPException(status_code=401, detail="Not authenticated")


# --- Spotify / DB wiring (injectable for tests) --------------------------


def _open_default_db() -> db_module.Database:
    database = db_module.Database(config.get_database_url())
    db_module.create_schema(database)
    return database


def _default_spotify_factory() -> Any:
    """Return a Spotify client supporting both interactive cache and refresh token."""
    settings = config.get_settings()
    if settings.spotify_refresh_token:
        return auth.get_client_from_refresh_token(auth.SCOPES_ALL)
    return auth.get_local_spotify(auth.SCOPES_ALL)


def _resolve_album_metadata(spotify: Any, track_uris: list[str]) -> dict[str, dict]:
    """Map representative track URIs to their album metadata (id/name/artist/cover/count).

    Mirrors the batched ``spotify.tracks()`` pattern in ``library.resolve_album_ids``
    but retains the album object so the picker can show covers/artists.
    """
    result: dict[str, dict] = {}
    for start in range(0, len(track_uris), library.TRACKS_BATCH):
        batch = track_uris[start : start + library.TRACKS_BATCH]
        response = api.call_with_retry(spotify.tracks, batch)
        for track in response.get("tracks", []):
            if not track or not track.get("uri"):
                continue
            album = track.get("album") or {}
            if not album.get("id"):
                continue
            images = album.get("images") or []
            cover_url = images[0]["url"] if images else None
            artist = ", ".join(
                a.get("name", "") for a in (album.get("artists") or []) if a.get("name")
            )
            result[track["uri"]] = {
                "album_id": album["id"],
                "name": album.get("name") or "",
                "artist": artist,
                "cover_url": cover_url,
                "total_tracks": album.get("total_tracks"),
            }
    return result


def _fetch_album_track_objects(spotify: Any, album_id: str) -> list[dict]:
    """Return an album's full tracklist (disc-aware) as lightweight objects."""
    tracks: list[dict] = []
    offset = 0
    while True:
        page = api.call_with_retry(
            spotify.album_tracks, album_id, limit=library.PAGE_SIZE, offset=offset
        )
        items = page.get("items", [])
        if not items:
            break
        for track in items:
            if not track or not track.get("uri"):
                continue
            artist = ", ".join(
                a.get("name", "") for a in (track.get("artists") or []) if a.get("name")
            )
            tracks.append(
                {
                    "uri": track["uri"],
                    "name": track.get("name") or "",
                    "artist": artist,
                    "disc_number": track.get("disc_number"),
                    "track_number": track.get("track_number"),
                }
            )
        offset += len(items)
        if not page.get("next"):
            break
    return tracks


# --- FastAPI app ---------------------------------------------------------


class GenerateRequest(BaseModel):
    title: str
    album_ids: list[str]


def create_app(
    *,
    db: db_module.Database | None = None,
    spotify_factory: Callable[[], Any] | None = None,
) -> FastAPI:
    """Build the picker FastAPI app.

    *db* defaults to the configured production/dev database; pass an in-memory
    SQLite ``Database`` in tests. *spotify_factory* defaults to the real client;
    pass a lambda returning a fake in tests.
    """
    database = db if db is not None else _open_default_db()
    get_spotify = spotify_factory or _default_spotify_factory
    # In-process cache so repeated track-list expands don't refetch Spotify.
    track_cache: dict[str, list[dict]] = {}

    app = FastAPI(title="Songipy Album Picker")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> str:
        if config.get_settings().picker_password:
            token = request.cookies.get(COOKIE_NAME)
            if not token or not _valid_token(token):
                return LOGIN_FORM
        return _load_picker_html()

    @app.post("/login")
    def login(password: str = Form(...)) -> RedirectResponse:
        expected = config.get_settings().picker_password or ""
        if not expected or not hmac.compare_digest(password.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="Invalid password")
        nonce = secrets.token_hex(16)
        token = f"{nonce}:{_sign(nonce)}"
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax")
        return response

    @app.post("/logout")
    def logout() -> RedirectResponse:
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(COOKIE_NAME)
        return response

    @app.get("/api/albums")
    def api_albums(window: int = 30, request: Request = None) -> dict:
        _require_auth(request)
        window = window if window in (7, 30, 90) else 30
        listens = db_module.all_listens_ordered(database)
        entries = picker_logic.group_recent_albums(
            listens,
            window_days=window,
            min_distinct_tracks=config.MIN_TRACKS_PER_ALBUM,
        )
        spotify = get_spotify()
        metadata = _resolve_album_metadata(
            spotify, [e.representative_track_uri for e in entries if e.representative_track_uri]
        )
        seen: set[str] = set()
        rows: list[dict] = []
        for entry in entries:
            meta = metadata.get(entry.representative_track_uri)
            album_id = meta["album_id"] if meta else entry.key
            if album_id in seen:
                continue  # dedupe by Spotify album id
            seen.add(album_id)
            if meta:
                track_count = meta["total_tracks"] or entry.track_count
                rows.append(
                    {
                        "album_id": album_id,
                        "name": meta["name"] or entry.name,
                        "artist": meta["artist"],
                        "cover_url": meta["cover_url"],
                        "track_count": track_count,
                        "last_played_at": entry.last_played_at,
                    }
                )
            else:
                rows.append(
                    {
                        "album_id": album_id,
                        "name": entry.name,
                        "artist": "",
                        "cover_url": None,
                        "track_count": entry.track_count,
                        "last_played_at": entry.last_played_at,
                    }
                )
        return {"albums": rows}

    @app.get("/api/albums/{album_id}/tracks")
    def api_album_tracks(album_id: str, request: Request = None) -> dict:
        _require_auth(request)
        if album_id in track_cache:
            return {"tracks": track_cache[album_id]}
        tracks = _fetch_album_track_objects(get_spotify(), album_id)
        track_cache[album_id] = tracks
        return {"tracks": tracks}

    @app.post("/api/generate")
    def api_generate(body: GenerateRequest, request: Request = None) -> dict:
        _require_auth(request)
        title = body.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="title is required")
        if not body.album_ids:
            raise HTTPException(status_code=400, detail="no albums selected")
        spotify = get_spotify()
        user_id = api.call_with_retry(spotify.me)["id"]
        # NOTE: picks are intentionally NOT prefixed with `Songipy/`, so
        # `organize` won't file them and `prune` won't clean them up. They are
        # user-curated one-offs, not generated artifacts.
        playlist_id = playlists.create_playlist(spotify, title, user_id=user_id)
        # Fetch each album's live tracklist (disc-aware) and flatten in the
        # requested album order; whole albums, album order within each.
        track_lists: list[list[dict]] = []
        for album_id in body.album_ids:
            track_lists.append(_fetch_album_track_objects(spotify, album_id))
        track_uris = picker_logic.flatten_album_tracks(track_lists)
        playlists.add_tracks(spotify, playlist_id, track_uris)
        return {
            "playlist_id": playlist_id,
            "url": f"https://open.spotify.com/playlist/{playlist_id}",
            "track_count": len(track_uris),
        }

    return app
