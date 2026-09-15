"""Group recently-listened albums into date-range windows for playlist generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class WindowSpec:
    start_days_ago: int  # older bound
    end_days_ago: int  # newer bound
    label: str


@dataclass(frozen=True)
class AlbumRef:
    key: str
    name: str
    track_uri: str  # representative (first seen) track URI in window
    last_played_at: str  # max played_at in window (ISO string)


@dataclass(frozen=True)
class WindowPlan:
    spec: WindowSpec
    albums: list[AlbumRef]


def album_identity(listen: dict) -> str:
    """Return the identity used to group a listen into an album."""
    album_name = listen.get("album_name")
    if album_name:
        return album_name
    return listen.get("track_uri") or ""


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating a trailing ``Z`` UTC marker.

    ``datetime.fromisoformat`` understands ``+00:00`` but not a trailing ``Z``
    (as written by the poll/import writers), so translate ``Z`` first. Offset-less
    timestamps are assumed to be UTC. Returns ``None`` when the string cannot be
    parsed.
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


def group_albums_by_window(
    listens: list[dict],
    windows: list[WindowSpec],
    min_distinct_tracks: int,
    now: datetime | None = None,
) -> list[WindowPlan]:
    """Group ``listens`` into one plan per window of qualifying albums.

    A window covers ``[now - start_days_ago, now - end_days_ago]`` inclusive
    (``start_days_ago`` is the older bound). ``played_at`` values are ISO
    strings using either a ``Z`` or ``+00:00`` UTC marker; each is parsed to a
    datetime and compared against the window bounds, so equal timestamps in
    different formats compare correctly. Listens without a parseable
    ``played_at`` are skipped, as are listens with an empty album identity.
    An album qualifies when at least ``min_distinct_tracks`` distinct track
    URIs were played within the window. Albums are sorted most-recent
    activity first (descending parsed ``last_played_at``), tie-broken by name
    ascending.

    ``now`` is injectable for tests; it defaults to the current UTC time.
    """
    if now is None:
        now = datetime.now(UTC)

    plans: list[WindowPlan] = []
    for spec in windows:
        start_dt = now - timedelta(days=spec.start_days_ago)
        end_dt = now - timedelta(days=spec.end_days_ago)

        grouped: dict[str, dict[str, Any]] = {}
        for listen in listens:
            played_at = listen.get("played_at")
            if not played_at:
                continue
            parsed = _parse_iso(played_at)
            if parsed is None or not (start_dt <= parsed <= end_dt):
                continue
            key = album_identity(listen)
            if not key:
                continue
            entry = grouped.setdefault(key, {})
            entry.setdefault("name", listen.get("album_name") or "")
            entry.setdefault("first_track_uri", listen.get("track_uri") or "")
            track_uri = listen.get("track_uri")
            if track_uri:
                entry.setdefault("track_uris", set()).add(track_uri)
            last_parsed = entry.get("last_played_at_parsed")
            if last_parsed is None or parsed > last_parsed:
                entry["last_played_at_parsed"] = parsed
                entry["last_played_at"] = played_at

        albums: list[AlbumRef] = []
        for key, entry in grouped.items():
            if len(entry.get("track_uris", set())) < min_distinct_tracks:
                continue
            albums.append(
                AlbumRef(
                    key=key,
                    name=entry["name"],
                    track_uri=entry["first_track_uri"],
                    last_played_at=entry["last_played_at"],
                )
            )
        albums.sort(key=lambda album: album.name)
        albums.sort(key=lambda album: _parse_iso(album.last_played_at), reverse=True)
        plans.append(WindowPlan(spec=spec, albums=albums))
    return plans
