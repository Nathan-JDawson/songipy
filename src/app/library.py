"""Helpers for paginating the user's saved library and album tracks."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from app import api

logger = logging.getLogger(__name__)

PAGE_SIZE = 50
TRACKS_BATCH = 50


def iter_saved_tracks(spotify: Any) -> Iterator[dict]:
    """Yield every saved track object (not the wrapper) for the current user."""
    offset = 0
    while True:
        page = api.call_with_retry(
            spotify.current_user_saved_tracks, limit=PAGE_SIZE, offset=offset
        )
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
        page = api.call_with_retry(spotify.album_tracks, album_id, limit=PAGE_SIZE, offset=offset)
        items = page.get("items", [])
        if not items:
            break
        uris.extend(track["uri"] for track in items)
        offset += len(items)
        if not page.get("next"):
            break
    return uris


def resolve_album_ids(spotify: Any, track_uris: list[str]) -> dict[str, str]:
    """Map track URIs to their album ids, fetching track metadata in batches."""
    album_ids: dict[str, str] = {}
    for start in range(0, len(track_uris), TRACKS_BATCH):
        batch = track_uris[start : start + TRACKS_BATCH]
        response = api.call_with_retry(spotify.tracks, batch)
        for track in response.get("tracks", []):
            if not track or not track.get("uri"):
                continue
            album = track.get("album") or {}
            if album.get("id"):
                album_ids[track["uri"]] = album["id"]
    return album_ids
