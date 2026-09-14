"""Helpers for paginating the user's saved library and album tracks."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

PAGE_SIZE = 50


def iter_saved_tracks(spotify: Any) -> Iterator[dict]:
    """Yield every saved track object (not the wrapper) for the current user."""
    offset = 0
    while True:
        page = spotify.current_user_saved_tracks(limit=PAGE_SIZE, offset=offset)
        items = page.get("items", [])
        if not items:
            break
        for item in items:
            track = item.get("track")
            if track:
                yield track
        offset += len(items)
        if not page.get("next"):
            break


def iter_album_tracks(spotify: Any, album_id: str) -> list[str]:
    """Return all track URIs of an album, in the order Spotify returns them."""
    uris: list[str] = []
    offset = 0
    while True:
        page = spotify.album_tracks(album_id, limit=PAGE_SIZE, offset=offset)
        items = page.get("items", [])
        if not items:
            break
        uris.extend(track["uri"] for track in items)
        offset += len(items)
        if not page.get("next"):
            break
    return uris
