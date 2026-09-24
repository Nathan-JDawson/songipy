"""Application configuration loaded from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_REDIRECT_URI = "http://127.0.0.1:8080/callback"
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOKEN_CACHE_PATH = str(_REPO_ROOT / ".tokens.json")

MIN_TRACKS_PER_ALBUM = 3
MIN_MS_PLAYED = 30_000

MIN_PLAYLIST_TRACKS = 50
MAX_RATE_LIMIT_RETRIES = 5
RATE_LIMIT_MAX_BACKOFF = 60

# (start_days_ago, end_days_ago, label); window = [now - start, now - end] inclusive, UTC.
ALBUM_WINDOWS: tuple[tuple[int, int, str], ...] = (
    (7, 0, "Last 7 Days"),
    (30, 0, "Last 30 Days"),
    (14, 8, "Days 8-14"),
    (90, 0, "Last 90 Days"),
)

# Optional root prefix for all generated playlists; "" disables it entirely.
PLAYLIST_ROOT = "Songipy"

PLAYLIST_NAME_FORMAT: dict[str, str] = {
    "genre": "Genres/{label} — {timestamp}",
    "albums": "Albums/{label} — {timestamp}",
}

# Subfolders used by the folder-style playlist names under PLAYLIST_ROOT.
FOLDER_SUBFOLDERS: tuple[str, ...] = ("Albums", "Genres")

# sync-genres per-album track selection modes and defaults.
GENRE_TRACK_SELECTION_CHOICES: tuple[str, ...] = ("all", "listened", "popular")
DEFAULT_GENRE_TRACK_SELECTION = "listened"
DEFAULT_GENRE_MAX_TRACKS_PER_ALBUM = 5


def folder_subfolders() -> tuple[str, ...]:
    """Return the subfolder names used under ``PLAYLIST_ROOT``."""
    return FOLDER_SUBFOLDERS


def genre_track_selection() -> str:
    """Return the sync-genres track-selection mode from ``GENRE_TRACK_SELECTION``."""
    return _env_choice(
        "GENRE_TRACK_SELECTION", DEFAULT_GENRE_TRACK_SELECTION, GENRE_TRACK_SELECTION_CHOICES
    )


def genre_max_tracks_per_album() -> int:
    """Return the per-album track cap for sync-genres from ``GENRE_MAX_TRACKS_PER_ALBUM``."""
    return max(1, _env_int("GENRE_MAX_TRACKS_PER_ALBUM", DEFAULT_GENRE_MAX_TRACKS_PER_ALBUM))


def _env_bool(name: str, default: bool) -> bool:
    """Parse ``name`` as a boolean ("1"/"true"/"yes" -> True); else ``default``."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes"}


def _env_int(name: str, default: int) -> int:
    """Parse ``name`` as an int; on missing/invalid values return ``default``."""
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return default


def _env_choice(name: str, default: str, choices: tuple[str, ...]) -> str:
    """Parse ``name`` as one of ``choices`` (case/space-insensitive); else ``default``."""
    value = os.getenv(name)
    if value is None:
        return default
    cleaned = value.strip().lower()
    if cleaned in choices:
        return cleaned
    return default


def utc_timestamp() -> str:
    """Return the current UTC time as ``%Y-%m-%d %H:%M``."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M")


def make_playlist_name(kind: str, label: str) -> str:
    """Build a folder-style playlist name for ``kind`` (``"genre"`` or ``"albums"``).

    The name is shaped ``<root>/<KindFolder>/<label> — <timestamp>`` where
    ``<root>`` is ``PLAYLIST_ROOT`` (omitted entirely when it is empty).
    """
    try:
        template = PLAYLIST_NAME_FORMAT[kind]
    except KeyError:
        known = ", ".join(sorted(PLAYLIST_NAME_FORMAT))
        raise ValueError(f"unknown playlist kind {kind!r}; expected one of: {known}") from None
    base = template.format(label=label, timestamp=utc_timestamp())
    if PLAYLIST_ROOT:
        return f"{PLAYLIST_ROOT}/{base}"
    return base


@dataclass(frozen=True)
class Settings:
    """Runtime settings read from environment variables."""

    spotify_client_id: str | None
    spotify_redirect_uri: str
    spotify_refresh_token: str | None
    database_url: str | None
    token_cache_path: str
    spotify_chrome_profile: str | None
    spotify_chrome_channel: str | None
    spotify_username: str | None
    folder_sync_headless: bool


def get_settings() -> Settings:
    return Settings(
        spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        spotify_redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", DEFAULT_REDIRECT_URI),
        spotify_refresh_token=os.getenv("SPOTIFY_REFRESH_TOKEN"),
        database_url=os.getenv("DATABASE_URL"),
        token_cache_path=os.getenv("SPOTIFY_TOKEN_CACHE", DEFAULT_TOKEN_CACHE_PATH),
        spotify_chrome_profile=os.getenv("SPOTIFY_CHROME_PROFILE"),
        # None/empty -> Playwright's bundled Chromium (no `channel`); a
        # non-empty value (e.g. "chrome" or "msedge") selects an installed browser.
        spotify_chrome_channel=os.getenv("SPOTIFY_CHROME_CHANNEL") or None,
        # Optional override for the account username used in spclient rootlist
        # URLs; when unset `organize` derives it from `spotify.me()["id"]`.
        spotify_username=os.getenv("SPOTIFY_USERNAME") or None,
        folder_sync_headless=_env_bool("FOLDER_SYNC_HEADLESS", default=False),
    )


def get_database_url() -> str:
    """Return ``DATABASE_URL`` or raise a clear error if it is unset."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to your .env (see .env.example), e.g. "
            "postgresql://user:password@host/dbname or sqlite:///listens.db"
        )
    return url
