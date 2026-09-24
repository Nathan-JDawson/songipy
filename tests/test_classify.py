import pytest

from app.classify import (
    build_track_genres,
    dedupe_album_tracks,
    keep_min_genres,
    normalize_genre,
)


def test_normalize_genre_lowercases_and_strips() -> None:
    assert normalize_genre("  Hip Hop ") == "hip hop"
    assert normalize_genre("ROCK") == "rock"


def test_track_assigned_to_every_genre_of_its_artists() -> None:
    t1 = {"uri": "t1", "artists": [{"id": "a1"}, {"id": "a2"}]}
    t2 = {"uri": "t2", "artists": [{"id": "a2"}]}
    t3 = {"uri": "t3", "artists": [{"id": "a3"}]}
    tracks = [t1, t2, t3]
    artists_genres = {
        "a1": {"Rock"},
        "a2": {"rock", "pop"},
        "a3": set(),
    }

    result = build_track_genres(tracks, artists_genres)

    assert result == {"rock": [t1, t2], "pop": [t1, t2]}


def test_tracks_without_genres_are_ignored() -> None:
    tracks = [{"uri": "t1", "artists": [{"id": "unknown"}]}]
    assert build_track_genres(tracks, {}) == {}


def test_tracks_without_uri_are_skipped() -> None:
    tracks = [{"uri": None, "artists": [{"id": "a1"}]}]
    assert build_track_genres(tracks, {"a1": {"rock"}}) == {}


def test_keep_min_genres_drops_below_threshold() -> None:
    a = {"uri": "a"}
    b = {"uri": "b"}
    c = {"uri": "c"}
    mapping = {"rock": [a, b], "pop": [a], "jazz": [a, b, c]}
    assert keep_min_genres(mapping, 2) == {"rock": [a, b], "jazz": [a, b, c]}


def test_keep_min_genres_keeps_equals_threshold() -> None:
    assert keep_min_genres({"pop": [{"uri": "a"}, {"uri": "b"}]}, 2) == {
        "pop": [{"uri": "a"}, {"uri": "b"}]
    }


def test_keep_min_genres_empty_input() -> None:
    assert keep_min_genres({}, 5) == {}


def _track(
    uri: str,
    *,
    album_id: str | None = None,
    album_name: str | None = None,
    track_number: int = 1,
    popularity: int | None = None,
    is_local: bool = False,
    name: str = "",
) -> dict:
    album: dict = {}
    if album_id is not None:
        album["id"] = album_id
    if album_name is not None:
        album["name"] = album_name
    track: dict = {"uri": uri, "album": album, "track_number": track_number, "name": name}
    if popularity is not None:
        track["popularity"] = popularity
    if is_local:
        track["is_local"] = True
    return track


def test_dedupe_groups_by_album_id_and_applies_cap() -> None:
    tracks = [
        _track("t1", album_id="a1", track_number=1, name="A"),
        _track("t2", album_id="a1", track_number=2, name="B"),
        _track("t3", album_id="a1", track_number=3, name="C"),
        _track("t4", album_id="a1", track_number=4, name="D"),
        _track("t5", album_id="a1", track_number=5, name="E"),
        _track("t6", album_id="a1", track_number=6, name="F"),
        _track("u1", album_id="a2", track_number=1, name="G"),
        _track("u2", album_id="a2", track_number=2, name="H"),
    ]
    stats = {
        "t1": {"play_count": 1, "ms_played_total": 100},
        "t2": {"play_count": 2, "ms_played_total": 200},
        "t3": {"play_count": 3, "ms_played_total": 300},
        "t4": {"play_count": 4, "ms_played_total": 400},
        "t5": {"play_count": 5, "ms_played_total": 500},
        # t6 has zero listens
        "u1": {"play_count": 1, "ms_played_total": 10},
        "u2": {"play_count": 2, "ms_played_total": 20},
    }

    result = dedupe_album_tracks(tracks, stats, cap=5, mode="listened")

    # a1's zero-listen t6 is dropped by the filter; a2 kept whole.
    assert [t["uri"] for t in result] == ["t1", "t2", "t3", "t4", "t5", "u1", "u2"]


def test_dedupe_ranks_by_plays_then_ms() -> None:
    t1 = _track("t1", album_id="a1", track_number=1)
    t2 = _track("t2", album_id="a1", track_number=5)
    t3 = _track("t3", album_id="a1", track_number=2)
    t4 = _track("t4", album_id="a1", track_number=3)
    t5 = _track("t5", album_id="a1", track_number=4)
    t6 = _track("t6", album_id="a1", track_number=6)
    stats = {
        "t1": {"play_count": 3, "ms_played_total": 500},
        "t2": {"play_count": 3, "ms_played_total": 700},
        "t3": {"play_count": 2, "ms_played_total": 9999},
        "t4": {"play_count": 1, "ms_played_total": 1},
        "t5": {"play_count": 1, "ms_played_total": 2},
        # t6 has zero listens
    }

    result = dedupe_album_tracks([t1, t2, t3, t4, t5, t6], stats, cap=3, mode="listened")

    # t2 beats t1 on ms despite a higher track number; t6 (zero listens) is
    # dropped by the zero-listen filter before ranking.
    assert [t["uri"] for t in result] == ["t1", "t2", "t3"]


def test_dedupe_ties_break_by_track_number() -> None:
    t1 = _track("t1", album_id="a1", track_number=9)
    t2 = _track("t2", album_id="a1", track_number=2)
    t3 = _track("t3", album_id="a1", track_number=5)
    t4 = _track("t4", album_id="a1", track_number=1)
    stats = {uri: {"play_count": 2, "ms_played_total": 100} for uri in ("t1", "t2", "t3", "t4")}

    result = dedupe_album_tracks([t1, t2, t3, t4], stats, cap=2, mode="listened")

    assert [t["uri"] for t in result] == ["t2", "t4"]


def test_dedupe_groups_by_album_name_when_id_missing() -> None:
    tracks = [
        _track("t1", album_name="Greatest Hits", track_number=1),
        _track("t2", album_name="Greatest Hits", track_number=2),
        _track("t3", album_name="Greatest Hits", track_number=3),
        _track("x1", album_name="Other Album", track_number=1),
    ]
    stats = {
        "t1": {"play_count": 1, "ms_played_total": 1},
        "t2": {"play_count": 2, "ms_played_total": 2},
        # t3 has zero listens
        "x1": {"play_count": 1, "ms_played_total": 1},
    }

    result = dedupe_album_tracks(tracks, stats, cap=2, mode="listened")

    # Greatest Hits has 2 listened (t3 dropped by the filter) <= cap 2 -> kept
    # whole; Other Album kept whole.
    assert [t["uri"] for t in result] == ["t1", "t2", "x1"]


def test_dedupe_local_files_are_singletons() -> None:
    tracks = [
        _track("l1", is_local=True, track_number=1),
        _track("l2", is_local=True, track_number=2),
        _track("l3", is_local=True, track_number=3),
    ]
    stats = {
        "l1": {"play_count": 1, "ms_played_total": 1},
        "l2": {"play_count": 1, "ms_played_total": 1},
        "l3": {"play_count": 1, "ms_played_total": 1},
    }

    result = dedupe_album_tracks(tracks, stats, cap=1, mode="listened")

    assert [t["uri"] for t in result] == ["l1", "l2", "l3"]


def test_dedupe_tracks_without_album_metadata_are_singletons() -> None:
    tracks = [_track("m1"), _track("m2")]
    stats = {
        "m1": {"play_count": 1, "ms_played_total": 1},
        "m2": {"play_count": 1, "ms_played_total": 1},
    }

    result = dedupe_album_tracks(tracks, stats, cap=1, mode="listened")

    assert [t["uri"] for t in result] == ["m1", "m2"]


def test_dedupe_keeps_albums_at_or_below_cap() -> None:
    tracks = [
        _track("t1", album_id="a1", track_number=1),
        _track("t2", album_id="a1", track_number=2),
        _track("t3", album_id="a1", track_number=3),
    ]
    stats = {
        "t1": {"play_count": 1, "ms_played_total": 1},
        "t2": {"play_count": 1, "ms_played_total": 1},
        "t3": {"play_count": 1, "ms_played_total": 1},
    }

    result = dedupe_album_tracks(tracks, stats, cap=3, mode="listened")

    assert [t["uri"] for t in result] == ["t1", "t2", "t3"]


def test_dedupe_zero_listen_album_contributes_nothing() -> None:
    tracks = [
        _track("t1", album_id="a1", track_number=1, name="Z"),
        _track("t2", album_id="a1", track_number=1, name="A"),
        _track("t3", album_id="a1", track_number=2, name="M"),
        _track("t4", album_id="a1", track_number=2, name="B"),
        _track("t5", album_id="a1", track_number=3, name="C"),
    ]

    result = dedupe_album_tracks(tracks, {}, cap=3, mode="listened")

    # An album whose tracks are all zero-listen contributes nothing.
    assert result == []


def test_dedupe_mixed_album_applies_cap_to_listened_subset() -> None:
    tracks = [
        _track("t1", album_id="a1", track_number=1, name="A"),
        _track("t2", album_id="a1", track_number=2, name="B"),
        _track("t3", album_id="a1", track_number=3, name="C"),
        _track("t4", album_id="a1", track_number=4, name="D"),
        _track("t5", album_id="a1", track_number=5, name="E"),
        _track("u1", album_id="a1", track_number=6, name="F"),
        _track("u2", album_id="a1", track_number=7, name="G"),
    ]
    stats = {
        "t1": {"play_count": 1, "ms_played_total": 100},
        "t2": {"play_count": 5, "ms_played_total": 500},
        "t3": {"play_count": 3, "ms_played_total": 300},
        "t4": {"play_count": 4, "ms_played_total": 400},
        "t5": {"play_count": 2, "ms_played_total": 200},
        # u1, u2 have zero listens
    }

    result = dedupe_album_tracks(tracks, stats, cap=3, mode="listened")

    # Only listened tracks participate; top 3 by plays are t2, t4, t3, but the
    # output preserves original track order.
    assert [t["uri"] for t in result] == ["t2", "t3", "t4"]


def test_dedupe_single_listened_track_kept_from_unlistened_album() -> None:
    tracks = [
        _track("star", album_id="a1", track_number=9),
        _track("cold1", album_id="a1", track_number=1),
        _track("cold2", album_id="a1", track_number=2),
        _track("cold3", album_id="a1", track_number=3),
    ]
    stats = {"star": {"play_count": 99, "ms_played_total": 9999}}

    result = dedupe_album_tracks(tracks, stats, cap=1, mode="listened")

    assert [t["uri"] for t in result] == ["star"]


def test_dedupe_mode_all_keeps_zero_listen_tracks() -> None:
    tracks = [
        _track("t1", album_id="a1", track_number=1),
        _track("t2", album_id="a1", track_number=2),
    ]

    result = dedupe_album_tracks(tracks, {}, cap=1, mode="all")

    assert [t["uri"] for t in result] == ["t1", "t2"]


def test_dedupe_empty_listen_stats_listened_mode_empty() -> None:
    tracks = [
        _track("t1", album_id="a1", track_number=1),
        _track("t2", album_id="a1", track_number=2),
    ]

    result = dedupe_album_tracks(tracks, {}, cap=5, mode="listened")

    assert result == []


def test_dedupe_mode_all_is_passthrough() -> None:
    tracks = [
        _track("t1", album_id="a1", track_number=1),
        _track("t2", album_id="a1", track_number=2),
        _track("t3", album_id="a1", track_number=3),
    ]

    result = dedupe_album_tracks(tracks, {}, cap=1, mode="all")

    assert result == tracks
    assert result is not tracks


def test_dedupe_mode_popular_ranks_by_popularity() -> None:
    tracks = [
        _track("p1", album_id="a1", popularity=90, track_number=3),
        _track("p2", album_id="a1", popularity=None, track_number=1),
        _track("p3", album_id="a1", popularity=50, track_number=2),
        _track("p4", album_id="a1", popularity=90, track_number=1),
        _track("p5", album_id="a1", popularity=70, track_number=4),
    ]
    stats = {
        "p1": {"play_count": 1, "ms_played_total": 1},
        "p2": {"play_count": 1, "ms_played_total": 1},
        "p3": {"play_count": 1, "ms_played_total": 1},
        "p4": {"play_count": 1, "ms_played_total": 1},
        "p5": {"play_count": 1, "ms_played_total": 1},
    }

    result = dedupe_album_tracks(tracks, stats, cap=3, mode="popular")

    # top 3: p4 (90, tn1), p1 (90, tn3), p5 (70); p3 and missing-popularity p2 drop.
    assert [t["uri"] for t in result] == ["p1", "p4", "p5"]


def test_dedupe_popular_mode_drops_zero_listen() -> None:
    tracks = [
        _track("p1", album_id="a1", popularity=90, track_number=3),
        _track("p2", album_id="a1", popularity=50, track_number=2),
        _track("p3", album_id="a1", popularity=80, track_number=1),
    ]
    stats = {"p1": {"play_count": 1, "ms_played_total": 100}}

    result = dedupe_album_tracks(tracks, stats, cap=5, mode="popular")

    # Only the listened track participates, despite the higher-popularity p3.
    assert [t["uri"] for t in result] == ["p1"]


def test_dedupe_preserves_original_order() -> None:
    t1 = _track("t1", album_id="a1", track_number=1)
    t2 = _track("t2", album_id="a1", track_number=2)
    t3 = _track("t3", album_id="a1", track_number=3)
    t4 = _track("t4", album_id="a1", track_number=4)
    t5 = _track("t5", album_id="a1", track_number=5)
    t6 = _track("t6", album_id="a1", track_number=6)
    stats = {
        "t1": {"play_count": 1, "ms_played_total": 100},
        "t2": {"play_count": 5, "ms_played_total": 500},
        "t3": {"play_count": 4, "ms_played_total": 400},
        "t4": {"play_count": 3, "ms_played_total": 300},
        "t5": {"play_count": 2, "ms_played_total": 200},
        # t6 has zero listens
    }
    scrambled = [t6, t2, t4, t1, t5, t3]

    result = dedupe_album_tracks(scrambled, stats, cap=3, mode="listened")

    kept_uris = [t["uri"] for t in result]
    # t6 (zero listens) is dropped by the filter; top 3 are t2, t3, t4.
    assert kept_uris == ["t2", "t4", "t3"]
    input_uris = [t["uri"] for t in scrambled]
    assert kept_uris == [uri for uri in input_uris if uri in kept_uris]


def test_dedupe_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="unknown genre track selection mode"):
        dedupe_album_tracks([], {}, cap=5, mode="bogus")
