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


def get_settings() -> Settings:
    return Settings(
        spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        spotify_redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", DEFAULT_REDIRECT_URI),
        spotify_refresh_token=os.getenv("SPOTIFY_REFRESH_TOKEN"),
        database_url=os.getenv("DATABASE_URL"),
        token_cache_path=os.getenv("SPOTIFY_TOKEN_CACHE", DEFAULT_TOKEN_CACHE_PATH),
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
