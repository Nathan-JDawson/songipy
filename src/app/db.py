"""Storage layer supporting both Postgres (psycopg) and SQLite (stdlib)."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Literal

logger = logging.getLogger(__name__)

Backend = Literal["postgresql", "sqlite"]

COLUMNS: tuple[str, ...] = (
    "played_at",
    "track_uri",
    "track_name",
    "artist_name",
    "album_name",
    "context_uri",
    "ms_played",
    "skipped",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS listens (
    played_at TEXT NOT NULL,
    track_uri TEXT NOT NULL,
    track_name TEXT,
    artist_name TEXT,
    album_name TEXT,
    context_uri TEXT,
    ms_played INTEGER,
    skipped INTEGER,
    PRIMARY KEY (played_at, track_uri)
)
"""


def _detect_backend(url: str) -> Backend:
    scheme = url.split("://", 1)[0].lower()
    if scheme in ("postgresql", "postgres"):
        return "postgresql"
    return "sqlite"


def _sqlite_path(url: str) -> str:
    if url == ":memory:":
        return ":memory:"
    if url.startswith("sqlite://"):
        rest = url[len("sqlite://") :]
        if rest in (":memory:", "/:memory:"):
            return ":memory:"
        if rest.startswith("//"):
            return rest[1:]
        return rest.lstrip("/")
    return url


def _row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    return {key: row[key] for key in row.keys()}


class Database:
    """A backend-agnostic database handle.

    A single connection is kept alive for the lifetime of the instance so that
    in-memory SQLite databases persist across calls.
    """

    def __init__(self, url: str) -> None:
        self.url = url
        self.backend: Backend = _detect_backend(url)
        self._conn: Any | None = None

    @property
    def placeholder(self) -> str:
        return "%s" if self.backend == "postgresql" else "?"

    def connect(self) -> Any:
        if self._conn is None:
            self._conn = self._open()
        return self._conn

    def _open(self) -> Any:
        if self.backend == "postgresql":
            import psycopg
            from psycopg.rows import dict_row

            return psycopg.connect(self.url, row_factory=dict_row)

        conn = sqlite3.connect(_sqlite_path(self.url))
        conn.row_factory = sqlite3.Row
        return conn

    def commit(self) -> None:
        self.connect().commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> Database:
        self.connect()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


@contextmanager
def _cursor(conn: Any) -> Iterator[Any]:
    cursor = conn.cursor()
    try:
        yield cursor
    finally:
        cursor.close()


def _query(db: Database, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    conn = db.connect()
    with _cursor(conn) as cur:
        cur.execute(sql, params)
        return [_row_to_dict(row) for row in cur.fetchall()]


def create_schema(db: Database) -> None:
    conn = db.connect()
    with _cursor(conn) as cur:
        cur.execute(SCHEMA)
    conn.commit()


def upsert_listens(db: Database, rows: list[dict[str, Any]]) -> int:
    """Insert rows, silently skipping duplicates. Returns inserted count."""
    if not rows:
        return 0

    placeholders = ", ".join([db.placeholder] * len(COLUMNS))
    columns = ", ".join(COLUMNS)
    sql = (
        f"INSERT INTO listens ({columns}) VALUES ({placeholders}) "
        "ON CONFLICT (played_at, track_uri) DO NOTHING"
    )

    conn = db.connect()
    inserted = 0
    with _cursor(conn) as cur:
        for row in rows:
            if not row.get("played_at") or not row.get("track_uri"):
                logger.debug("skipping listen without played_at/track_uri: %r", row)
                continue
            values = [row.get(column) for column in COLUMNS]
            cur.execute(sql, values)
            if cur.rowcount and cur.rowcount > 0:
                inserted += cur.rowcount
    conn.commit()
    return inserted


def latest_listens(db: Database, limit: int = 10) -> list[dict[str, Any]]:
    return _query(
        db,
        f"SELECT * FROM listens ORDER BY played_at DESC LIMIT {db.placeholder}",
        [limit],
    )


def all_listens_ordered(db: Database) -> list[dict[str, Any]]:
    return _query(db, "SELECT * FROM listens ORDER BY played_at ASC", [])


def listens_since(db: Database, iso_ts: str) -> list[dict[str, Any]]:
    return _query(
        db,
        f"SELECT * FROM listens WHERE played_at > {db.placeholder} ORDER BY played_at ASC",
        [iso_ts],
    )
