from app.classify import build_track_genres, normalize_genre


def test_normalize_genre_lowercases_and_strips() -> None:
    assert normalize_genre("  Hip Hop ") == "hip hop"
    assert normalize_genre("ROCK") == "rock"


def test_track_assigned_to_every_genre_of_its_artists() -> None:
    tracks = [
        {"uri": "t1", "artists": [{"id": "a1"}, {"id": "a2"}]},
        {"uri": "t2", "artists": [{"id": "a2"}]},
        {"uri": "t3", "artists": [{"id": "a3"}]},
    ]
    artists_genres = {
        "a1": {"Rock"},
        "a2": {"rock", "pop"},
        "a3": set(),
    }

    result = build_track_genres(tracks, artists_genres)

    assert result == {"rock": ["t1", "t2"], "pop": ["t1", "t2"]}


def test_tracks_without_genres_are_ignored() -> None:
    tracks = [{"uri": "t1", "artists": [{"id": "unknown"}]}]
    assert build_track_genres(tracks, {}) == {}


def test_tracks_without_uri_are_skipped() -> None:
    tracks = [{"uri": None, "artists": [{"id": "a1"}]}]
    assert build_track_genres(tracks, {"a1": {"rock"}}) == {}
