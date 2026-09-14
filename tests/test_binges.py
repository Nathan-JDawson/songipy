from app.binges import detect_album_sessions


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
