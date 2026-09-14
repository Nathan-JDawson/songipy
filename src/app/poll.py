"""Poll the Spotify recently-played endpoint into the listens store."""

from __future__ import annotations

import logging
from typing import Any

from app.db import Database, upsert_listens

logger = logging.getLogger(__name__)


def item_to_row(item: dict) -> dict[str, Any]:
    """Map a recently-played API item to a listen row."""
    track = item["track"]
    context = item.get("context") or {}
    return {
        "played_at": item["played_at"],
        "track_uri": track["uri"],
        "track_name": track.get("name"),
        "artist_name": ", ".join(artist["name"] for artist in track.get("artists", [])),
        "album_name": (track.get("album") or {}).get("name"),
        "context_uri": context.get("uri"),
        "ms_played": None,
        "skipped": None,
    }


def poll_recent(spotify: Any, db: Database, limit: int = 50) -> int:
    """Fetch the most recent plays and upsert them. Returns inserted count."""
    response = spotify.current_user_recently_played(limit=limit)
    rows = [item_to_row(item) for item in response.get("items", [])]
    return upsert_listens(db, rows)
