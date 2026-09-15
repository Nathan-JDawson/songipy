"""Detect 'binge' sessions: runs of consecutive albums played in full."""

from __future__ import annotations

from typing import Any


def filter_since(listens: list[dict], cutoff: str) -> list[dict]:
    """Return listens whose ``played_at`` is strictly after ``cutoff``.

    ``played_at`` is an ISO-8601 string, so lexical comparison is sufficient.
    Listens without a ``played_at`` value are skipped.
    """
    return [
        listen
        for listen in listens
        if (played_at := listen.get("played_at")) and played_at > cutoff
    ]


def album_key(listen: dict) -> Any:
    """Return the identifier used to group a listen into an album run."""
    for key in ("album_id", "album_uri", "album_name"):
        value = listen.get(key)
        if value:
            return value
    return listen.get("track_uri")


def _runs(listens: list[dict]) -> list[tuple[Any, set[Any]]]:
    runs: list[tuple[Any, set[Any]]] = []
    for listen in listens:
        key = album_key(listen)
        if runs and runs[-1][0] == key:
            runs[-1][1].add(listen.get("track_uri"))
        else:
            runs.append((key, {listen.get("track_uri")}))
    return runs


def detect_album_sessions(
    listens: list[dict],
    min_distinct_tracks: int,
    min_albums: int,
) -> list[list[str]]:
    """Return maximal sessions of consecutive, sufficiently-played albums.

    ``listens`` must be ordered ascending by ``played_at``. Consecutive listens
    with the same album form a run; a run counts when it holds at least
    ``min_distinct_tracks`` distinct tracks. A session is a maximal group of
    consecutive counting runs (an uncounted run breaks it) of at least
    ``min_albums`` runs.
    """
    if min_albums <= 0:
        return []

    sessions: list[list[str]] = []
    current: list[str] = []
    for key, track_uris in _runs(listens):
        if len(track_uris) >= min_distinct_tracks:
            current.append(key)
        else:
            if len(current) >= min_albums:
                sessions.append(current)
            current = []

    if len(current) >= min_albums:
        sessions.append(current)
    return sessions
