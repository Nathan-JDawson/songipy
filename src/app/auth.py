"""Spotify authentication helpers (PKCE local login and refresh-token mode)."""

from __future__ import annotations

import logging

import spotipy
from spotipy.oauth2 import SpotifyPKCE

from app import config

logger = logging.getLogger(__name__)

SCOPES_ALL = [
    "user-library-read",
    "user-read-recently-played",
    "playlist-modify-public",
    "playlist-modify-private",
]
SCOPES_POLL = ["user-read-recently-played"]


def _require_client_id(settings: config.Settings) -> str:
    if not settings.spotify_client_id:
        raise RuntimeError("SPOTIFY_CLIENT_ID is not set. Add it to your .env (see .env.example).")
    return settings.spotify_client_id


def get_local_spotify(
    scopes: list[str],
    cache_path: str | None = None,
) -> spotipy.Spotify:
    """Run the interactive PKCE authorization-code flow and return a client."""
    settings = config.get_settings()
    auth_manager = SpotifyPKCE(
        client_id=_require_client_id(settings),
        redirect_uri=settings.spotify_redirect_uri,
        scope=" ".join(scopes),
        cache_path=cache_path or settings.token_cache_path,
        open_browser=True,
    )
    return spotipy.Spotify(auth_manager=auth_manager)


def get_client_from_refresh_token(
    scopes: list[str],
    cache_path: str | None = None,
) -> spotipy.Spotify:
    """Build a non-interactive client from ``SPOTIFY_REFRESH_TOKEN``."""
    settings = config.get_settings()
    if not settings.spotify_refresh_token:
        raise RuntimeError("SPOTIFY_REFRESH_TOKEN is not set. Set it for headless/cloud polling.")

    auth_manager = SpotifyPKCE(
        client_id=_require_client_id(settings),
        redirect_uri=settings.spotify_redirect_uri,
        scope=" ".join(scopes),
        cache_path=cache_path or settings.token_cache_path,
        open_browser=False,
    )
    auth_manager.refresh_access_token(settings.spotify_refresh_token)
    return spotipy.Spotify(auth_manager=auth_manager)
