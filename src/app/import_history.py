"""Parse Spotify 'Download your data' exports into normalized listen rows."""

from __future__ import annotations

import fnmatch
import json
import logging
import zipfile
from collections.abc import Iterator
from pathlib import Path

from app import config
from app.db import Database, upsert_listens

logger = logging.getLogger(__name__)

EXPORT_PATTERNS: tuple[str, ...] = (
    "Streaming_History_Audio_*.json",
    "StreamingHistory_music_*.json",
    "Streaming_History_Video_*.json",
)


def _matches_export(name: str) -> bool:
    base = Path(name).name
    return any(fnmatch.fnmatch(base, pattern) for pattern in EXPORT_PATTERNS)


def _iter_payloads(path: Path) -> Iterator[list[dict]]:
    if path.is_dir():
        for pattern in EXPORT_PATTERNS:
            for file in sorted(path.rglob(pattern)):
                yield json.loads(file.read_text(encoding="utf-8"))
    elif path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if _matches_export(name):
                    with archive.open(name) as handle:
                        yield json.load(handle)


def parse_entry(entry: dict) -> dict | None:
    """Map one raw export entry to a listen row, or ``None`` if filtered out."""
    played_at = entry.get("ts")
    if not played_at:
        return None

    ms_played = entry.get("ms_played", entry.get("msPlayed"))
    if ms_played is not None and ms_played < config.MIN_MS_PLAYED:
        return None
    if entry.get("skipped"):
        return None

    return {
        "played_at": played_at,
        "track_uri": entry.get("spotify_track_uri"),
        "track_name": entry.get("master_metadata_track_name", entry.get("trackName")),
        "artist_name": entry.get("master_metadata_album_artist_name", entry.get("artistName")),
        "album_name": entry.get("master_metadata_album_album_name", entry.get("albumName")),
        "context_uri": entry.get("context"),
        "ms_played": ms_played,
        "skipped": 1 if entry.get("skipped") else 0,
    }


def parse_export(path: str | Path) -> list[dict]:
    """Read every matching JSON file in ``path`` (a directory or .zip)."""
    export_path = Path(path)
    if not export_path.exists():
        raise FileNotFoundError(f"export path does not exist: {export_path}")

    rows: list[dict] = []
    for payload in _iter_payloads(export_path):
        for entry in payload:
            row = parse_entry(entry)
            if row is not None:
                rows.append(row)
    return rows


def import_export(path: str | Path, db: Database) -> int:
    """Parse an export and upsert it, returning the number of new listens."""
    rows = parse_export(path)
    usable = [row for row in rows if row.get("track_uri") and row.get("played_at")]
    skipped = len(rows) - len(usable)
    if skipped:
        logger.info("skipped %d rows without a track URI", skipped)
    return upsert_listens(db, usable)
