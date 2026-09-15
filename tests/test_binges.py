from app.binges import detect_album_sessions, filter_since


def _listen(album_id: str, track_uri: str) -> dict:
    return {"album_id": album_id, "track_uri": track_uri}


def _album(album_id: str, tracks: int, prefix: str = "t") -> list[dict]:
    return [_listen(album_id, f"{prefix}{album_id}-{i}") for i in range(tracks)]


def test_merges_consecutive_same_album_runs() -> None:
    listens = _album("A", 3) + _album("B", 3)
    assert detect_album_sessions(listens, 3, 2) == [["A", "B"]]


def test_distinct_tracks_within_a_run_are_deduplicated() -> None:
    listens = [_listen("A", "same")] * 5
    assert detect_album_sessions(listens, 3, 1) == []


def test_min_distinct_tracks_filters_short_runs() -> None:
    listens = _album("A", 2) + _album("B", 3)
    assert detect_album_sessions(listens, 3, 2) == []


def test_min_albums_threshold() -> None:
    listens = _album("A", 3) + _album("B", 3)
    assert detect_album_sessions(listens, 3, 3) == []


def test_interleaved_albums_stay_in_chronological_order() -> None:
    listens = _album("A", 3) + _album("B", 3) + _album("A", 3, prefix="u")
    assert detect_album_sessions(listens, 3, 2) == [["A", "B", "A"]]


def test_uncounted_run_breaks_a_session() -> None:
    listens = _album("A", 3) + _album("B", 1) + _album("C", 3)
    assert detect_album_sessions(listens, 3, 2) == []


def test_empty_input() -> None:
    assert detect_album_sessions([], 3, 2) == []


def test_filter_since_keeps_strictly_newer() -> None:
    listens = [
        {"played_at": "2026-01-01T00:00:00Z"},
        {"played_at": "2026-01-02T00:00:00Z"},
        {"played_at": "2026-01-03T00:00:00Z"},
    ]

    result = filter_since(listens, "2026-01-02T00:00:00Z")

    assert [listen["played_at"] for listen in result] == ["2026-01-03T00:00:00Z"]


def test_filter_since_skips_missing_played_at() -> None:
    listens = [{}, {"played_at": None}, {"played_at": "2026-01-03T00:00:00Z"}]

    assert filter_since(listens, "2026-01-02T00:00:00Z") == [{"played_at": "2026-01-03T00:00:00Z"}]


def test_filter_since_uses_string_ordering() -> None:
    listens = [
        {"played_at": "2025-09-09T23:59:59.999Z"},
        {"played_at": "2025-09-10T00:00:00.001Z"},
    ]

    assert filter_since(listens, "2025-09-10T00:00:00.000Z") == [
        {"played_at": "2025-09-10T00:00:00.001Z"}
    ]
