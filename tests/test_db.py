import pytest

from app.db import (
    Database,
    all_listens_ordered,
    create_schema,
    latest_listens,
    listen_stats_by_uri,
    listens_since,
    upsert_listens,
)


@pytest.fixture
def db() -> Database:
    database = Database("sqlite:///:memory:")
    create_schema(database)
    return database


def _row(played_at: str, track_uri: str, name: str = "Track") -> dict:
    return {
        "played_at": played_at,
        "track_uri": track_uri,
        "track_name": name,
        "artist_name": "Artist",
        "album_name": "Album",
        "context_uri": None,
        "ms_played": 60000,
        "skipped": 0,
    }


def test_upsert_is_idempotent(db: Database) -> None:
    row = _row("2026-09-14T12:30:45.000Z", "spotify:track:1")

    assert upsert_listens(db, [row]) == 1
    assert upsert_listens(db, [row]) == 0


def test_upsert_returns_number_inserted(db: Database) -> None:
    rows = [
        _row("2026-09-14T12:00:00.000Z", "spotify:track:1"),
        _row("2026-09-14T12:01:00.000Z", "spotify:track:2"),
    ]
    assert upsert_listens(db, rows) == 2
    assert upsert_listens(db, rows + rows) == 0


def test_upsert_skips_rows_without_key(db: Database) -> None:
    assert upsert_listens(db, [{"played_at": None, "track_uri": "x"}]) == 0
    assert upsert_listens(db, [{"played_at": "2026-01-01T00:00:00Z", "track_uri": None}]) == 0


def test_latest_listens_orders_descending(db: Database) -> None:
    upsert_listens(
        db,
        [
            _row("2026-09-14T12:00:00.000Z", "spotify:track:1"),
            _row("2026-09-14T12:02:00.000Z", "spotify:track:3"),
            _row("2026-09-14T12:01:00.000Z", "spotify:track:2"),
        ],
    )

    latest = latest_listens(db, limit=2)

    assert [row["track_uri"] for row in latest] == ["spotify:track:3", "spotify:track:2"]
    assert latest[0]["track_name"] == "Track"


def test_all_listens_ordered_is_ascending(db: Database) -> None:
    upsert_listens(
        db,
        [
            _row("2026-09-14T12:02:00.000Z", "spotify:track:3"),
            _row("2026-09-14T12:00:00.000Z", "spotify:track:1"),
        ],
    )

    ordered = all_listens_ordered(db)

    assert [row["track_uri"] for row in ordered] == ["spotify:track:1", "spotify:track:3"]


def test_listens_since_filters(db: Database) -> None:
    upsert_listens(
        db,
        [
            _row("2026-09-14T12:00:00.000Z", "spotify:track:1"),
            _row("2026-09-14T12:05:00.000Z", "spotify:track:2"),
        ],
    )

    rows = listens_since(db, "2026-09-14T12:00:00.000Z")

    assert [row["track_uri"] for row in rows] == ["spotify:track:2"]


def test_listen_stats_by_uri_counts_and_sums(db: Database) -> None:
    upsert_listens(
        db,
        [
            _row("2026-09-14T12:00:00.000Z", "spotify:track:1"),
            _row("2026-09-14T12:01:00.000Z", "spotify:track:1"),
            _row("2026-09-14T12:02:00.000Z", "spotify:track:2"),
        ],
    )

    stats = listen_stats_by_uri(db)

    assert stats == {
        "spotify:track:1": {"play_count": 2, "ms_played_total": 120000},
        "spotify:track:2": {"play_count": 1, "ms_played_total": 60000},
    }


def test_listen_stats_by_uri_handles_null_ms_played(db: Database) -> None:
    row = _row("2026-09-14T12:00:00.000Z", "spotify:track:1")
    row["ms_played"] = None
    upsert_listens(db, [row])

    stats = listen_stats_by_uri(db)

    assert stats["spotify:track:1"]["play_count"] == 1
    assert stats["spotify:track:1"]["ms_played_total"] == 0


def test_listen_stats_by_uri_empty(db: Database) -> None:
    assert listen_stats_by_uri(db) == {}
