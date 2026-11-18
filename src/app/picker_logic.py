"""Pure logic for the interactive album picker (no network, no FastAPI imports).

Everything here is a plain function over plain dicts/listens so it can be unit
tested without a live Spotify client or database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

MAX_ALBUMS = 50


def album_identity(listen: dict) -> str:
    """Return the identity key grouping a listen into an album.

    Mirrors ``app.albums.album_identity``: the cached ``album_name`` string when
    present, else the track URI. The picker keeps its own copy so this module
    stays fully standalone.
    """
    album_name = listen.get("album_name")
    if album_name:
        return album_name
    return listen.get("track_uri") or ""


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating a trailing ``Z`` UTC marker.

    ``datetime.fromisoformat`` understands ``+00:00`` but not a trailing ``Z``
    (as written by the poll/import writers), so translate ``Z`` first.
    Offset-less timestamps are assumed to be UTC.
    """
    if ts.endswith("Z"):
        ts = f"{ts[:-1]}+00:00"
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


@dataclass(frozen=True)
class AlbumEntry:
    """A recently-listened album candidate for the picker."""

    key: str  # grouping identity (album name, else track URI)
    name: str
    track_uris: frozenset[str]  # distinct track URIs heard within the window
    track_count: int  # distinct DB track count in window (≠ Spotify total)
    last_played_at: str  # max played_at in window (original ISO string)
    representative_track_uri: str  # first-seen track URI used to resolve album id


def group_recent_albums(
    listens: list[dict],
    *,
    window_days: int,
    min_distinct_tracks: int,
    now: datetime | None = None,
) -> list[AlbumEntry]:
    """Derive the picker's album rows from listen rows.

    Only listens within the last *window_days* days (per ``played_at``) count.
    An album qualifies when at least *min_distinct_tracks* distinct track URIs
    were played inside the window. Entries are sorted by most-recent
    ``played_at`` descending and capped at ``MAX_ALBUMS``. ``now`` is injectable
    for tests; it defaults to the current UTC time.
    """
    if now is None:
        now = datetime.now(UTC)
    cutoff = now - timedelta(days=window_days)

    grouped: dict[str, dict[str, Any]] = {}
    for listen in listens:
        played_at = listen.get("played_at")
        if not played_at:
            continue
        parsed = _parse_iso(played_at)
        if parsed is None or parsed < cutoff:
            continue
        key = album_identity(listen)
        if not key:
            continue
        entry = grouped.setdefault(key, {})
        entry.setdefault("name", listen.get("album_name") or "")
        entry.setdefault("representative_track_uri", listen.get("track_uri") or "")
        track_uri = listen.get("track_uri")
        if track_uri:
            entry.setdefault("track_uris", set()).add(track_uri)
        if parsed >= entry.get("last_played_at_parsed", datetime.min.replace(tzinfo=UTC)):
            entry["last_played_at_parsed"] = parsed
            entry["last_played_at"] = played_at

    qualifying = [
        (entry["last_played_at_parsed"], key, entry)
        for key, entry in grouped.items()
        if len(entry.get("track_uris", set())) >= min_distinct_tracks
    ]
    qualifying.sort(key=lambda item: item[0], reverse=True)

    return [
        AlbumEntry(
            key=key,
            name=entry["name"],
            track_uris=frozenset(entry["track_uris"]),
            track_count=len(entry["track_uris"]),
            last_played_at=entry["last_played_at"],
            representative_track_uri=entry["representative_track_uri"],
        )
        for _, key, entry in qualifying[:MAX_ALBUMS]
    ]


def _to_int(value: Any, default: int) -> int:
    """Coerce ``value`` to an int, falling back to ``default`` on bad input."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _track_order_key(pair: tuple[int, Any]) -> tuple[int, int]:
    """Ordering key for one track within an album: (disc_number, track_number).

    Items may be full track objects (dicts with ``disc_number``/``track_number``)
    or plain URI strings (no disc metadata); the index is the tie-breaker so the
    API's original order is preserved when the metadata is missing.
    """
    index, track = pair
    if not isinstance(track, dict):
        return (1, index + 1)
    disc = _to_int(track.get("disc_number"), 1)
    number = _to_int(track.get("track_number"), index + 1)
    return (disc, number)


def flatten_album_tracks(track_lists: list[list[Any]]) -> list[str]:
    """Flatten per-album track lists into one ordered URI list.

    Albums keep the order they appear in *track_lists*. Within an album the
    tracks are stably sorted by ``(disc_number, track_number)`` (disc-aware);
    items that are plain URI strings keep the order they were returned in.

    Tracks are deliberately NOT deduplicated across albums: the same track
    appearing on two selected albums (e.g. a deluxe edition and its standard
    release) is included twice, once per album — matching the albums the user
    chose. Spotify allows duplicate tracks in a playlist.
    """
    flattened: list[str] = []
    for album_tracks in track_lists:
        indexed = list(enumerate(album_tracks))
        indexed.sort(key=_track_order_key)
        for _, track in indexed:
            uri = track["uri"] if isinstance(track, dict) else track
            if uri:
                flattened.append(uri)
    return flattened
