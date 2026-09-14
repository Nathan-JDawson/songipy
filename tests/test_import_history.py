import json
from pathlib import Path

import pytest

from app.db import Database, create_schema
from app.import_history import import_export, parse_export


def _write(directory: Path, name: str, entries: list[dict]) -> None:
    (directory / name).write_text(json.dumps(entries), encoding="utf-8")


def test_parses_current_format(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "Streaming_History_Audio_2026.json",
        [
            {
                "ts": "2026-09-14T12:30:45.000Z",
                "ms_played": 60000,
                "spotify_track_uri": "spotify:track:1",
                "master_metadata_track_name": "Song",
                "master_metadata_album_artist_name": "Artist",
                "master_metadata_album_album_name": "Album",
                "context": "spotify:playlist:abc",
                "skipped": False,
            }
        ],
    )

    rows = parse_export(tmp_path)

    assert rows == [
        {
            "played_at": "2026-09-14T12:30:45.000Z",
            "track_uri": "spotify:track:1",
            "track_name": "Song",
            "artist_name": "Artist",
            "album_name": "Album",
            "context_uri": "spotify:playlist:abc",
            "ms_played": 60000,
            "skipped": 0,
        }
    ]


def test_parses_legacy_format(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "StreamingHistory_music_0.json",
        [
            {
                "ts": "2020-01-01T00:00:00Z",
                "msPlayed": 45000,
                "trackName": "Old Song",
                "artistName": "Old Artist",
                "albumName": "Old Album",
            }
        ],
    )

    rows = parse_export(tmp_path)

    assert len(rows) == 1
    assert rows[0]["track_name"] == "Old Song"
    assert rows[0]["artist_name"] == "Old Artist"
    assert rows[0]["album_name"] == "Old Album"
    assert rows[0]["track_uri"] is None
    assert rows[0]["context_uri"] is None

    database = Database("sqlite:///:memory:")
    create_schema(database)

    assert import_export(tmp_path, database) == 0


def test_filters_short_and_skipped_plays(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "Streaming_History_Audio_2026.json",
        [
            {
                "ts": "2026-09-14T12:00:00.000Z",
                "ms_played": 10000,
                "spotify_track_uri": "spotify:track:short",
                "master_metadata_track_name": "Short",
            },
            {
                "ts": "2026-09-14T12:01:00.000Z",
                "ms_played": 60000,
                "spotify_track_uri": "spotify:track:skipped",
                "master_metadata_track_name": "Skipped",
                "skipped": True,
            },
            {
                "ts": "2026-09-14T12:02:00.000Z",
                "ms_played": 60000,
                "spotify_track_uri": "spotify:track:kept",
                "master_metadata_track_name": "Kept",
            },
            {
                "ms_played": 60000,
                "spotify_track_uri": "spotify:track:no-ts",
                "master_metadata_track_name": "No timestamp",
            },
        ],
    )

    rows = parse_export(tmp_path)

    assert [row["track_uri"] for row in rows] == ["spotify:track:kept"]


def test_parse_export_missing_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        parse_export(tmp_path / "does-not-exist")
