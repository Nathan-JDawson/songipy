"""Thin wrappers around Spotify playlist creation and track insertion."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

ADD_TRACKS_BATCH = 100


def create_playlist(spotify: Any, name: str) -> str:
    user_id = spotify.me()["id"]
    playlist = spotify.user_playlist_create(user_id, name, public=True)
    return playlist["id"]


def add_tracks(spotify: Any, playlist_id: str, track_uris: list[str]) -> None:
    for start in range(0, len(track_uris), ADD_TRACKS_BATCH):
        spotify.playlist_add_items(playlist_id, track_uris[start : start + ADD_TRACKS_BATCH])
