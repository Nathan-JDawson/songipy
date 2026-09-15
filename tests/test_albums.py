from datetime import UTC, datetime, timedelta

from app.albums import WindowSpec, album_identity, group_albums_by_window

NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)

LAST_7 = WindowSpec(7, 0, "Last 7 Days")
DAYS_8_14 = WindowSpec(14, 8, "Days 8-14")


def _listen(album_name: str, track_uri: str, played_at: str) -> dict:
    return {"album_name": album_name, "track_uri": track_uri, "played_at": played_at}


def _days_ago(days: int) -> str:
    return (NOW - timedelta(days=days)).isoformat()


def _days_ago_z(days: int) -> str:
    """Like ``_days_ago`` but with the store's trailing ``Z`` UTC marker."""
    return (NOW - timedelta(days=days)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def test_albums_assigned_to_correct_window() -> None:
    listens = [
        _listen("A", "t1", _days_ago(1)),
        _listen("A", "t2", _days_ago(1)),
        _listen("A", "t3", _days_ago(1)),
        _listen("B", "u1", _days_ago(10)),
        _listen("B", "u2", _days_ago(10)),
        _listen("B", "u3", _days_ago(10)),
    ]

    plans = group_albums_by_window(listens, [LAST_7, DAYS_8_14], 3, now=NOW)

    assert [plan.spec.label for plan in plans] == ["Last 7 Days", "Days 8-14"]
    assert [album.key for album in plans[0].albums] == ["A"]
    assert [album.key for album in plans[1].albums] == ["B"]


def test_qualification_requires_min_distinct_tracks() -> None:
    listens = [
        _listen("A", "t1", _days_ago(1)),
        _listen("A", "t2", _days_ago(1)),
    ]

    assert group_albums_by_window(listens, [LAST_7], 3, now=NOW)[0].albums == []
    albums = group_albums_by_window(listens, [LAST_7], 2, now=NOW)[0].albums
    assert [album.key for album in albums] == ["A"]


def test_repeated_track_uri_does_not_inflate_distinct_count() -> None:
    listens = [_listen("A", "t1", _days_ago(1)) for _ in range(5)]

    assert group_albums_by_window(listens, [LAST_7], 3, now=NOW)[0].albums == []


def test_albums_ordered_most_recent_first() -> None:
    listens = [
        _listen("A", "a1", _days_ago(3)),
        _listen("A", "a2", _days_ago(3)),
        _listen("A", "a3", _days_ago(3)),
        _listen("B", "b1", _days_ago(1)),
        _listen("B", "b2", _days_ago(1)),
        _listen("B", "b3", _days_ago(1)),
    ]

    plans = group_albums_by_window(listens, [LAST_7], 3, now=NOW)

    assert [album.key for album in plans[0].albums] == ["B", "A"]
    assert [album.last_played_at for album in plans[0].albums] == [
        _days_ago(1),
        _days_ago(3),
    ]


def test_identity_falls_back_to_track_uri() -> None:
    assert album_identity({"album_name": "X", "track_uri": "t"}) == "X"
    assert album_identity({"track_uri": "t"}) == "t"
    assert album_identity({}) == ""


def test_same_album_appears_in_multiple_windows() -> None:
    listens = [_listen("A", f"t{i}", _days_ago(i)) for i in range(1, 4)]

    plans = group_albums_by_window(listens, [LAST_7, WindowSpec(90, 0, "Last 90 Days")], 3, now=NOW)

    assert [album.key for album in plans[0].albums] == ["A"]
    assert [album.key for album in plans[1].albums] == ["A"]


def test_window_boundaries_inclusive() -> None:
    listens = [
        _listen("A", "a1", _days_ago(7)),
        _listen("A", "a2", _days_ago(7)),
        _listen("A", "a3", _days_ago_z(7)),
        _listen("B", "b1", _days_ago(8)),
        _listen("B", "b2", _days_ago(8)),
        _listen("B", "b3", _days_ago(8)),
    ]

    plans = group_albums_by_window(listens, [LAST_7, DAYS_8_14], 3, now=NOW)

    assert [album.key for album in plans[0].albums] == ["A"]
    assert [album.key for album in plans[1].albums] == ["B"]


def test_missing_played_at_ignored() -> None:
    listens = [
        _listen("A", "a1", ""),
        {"album_name": "A", "track_uri": "a2"},
        _listen("A", "a3", _days_ago(1)),
    ]

    plans = group_albums_by_window(listens, [LAST_7], 3, now=NOW)

    assert plans[0].albums == []


def test_empty_input_returns_plan_per_window() -> None:
    plans = group_albums_by_window([], [LAST_7, DAYS_8_14], 3, now=NOW)

    assert [plan.spec.label for plan in plans] == ["Last 7 Days", "Days 8-14"]
    assert all(plan.albums == [] for plan in plans)


def test_empty_album_identity_ignored() -> None:
    listens = [
        {"played_at": _days_ago(1), "track_uri": ""},
        {"played_at": _days_ago(1)},
        _listen("", "", _days_ago(1)),
    ]

    plans = group_albums_by_window(listens, [LAST_7], 1, now=NOW)

    assert plans[0].albums == []


def test_input_need_not_be_ordered() -> None:
    listens = [
        _listen("A", "t1", _days_ago(3)),
        _listen("B", "b1", _days_ago(1)),
        _listen("A", "t2", _days_ago(2)),
        _listen("B", "b2", _days_ago(0)),
        _listen("A", "t3", _days_ago(1)),
        _listen("B", "b3", _days_ago(2)),
    ]

    plans = group_albums_by_window(listens, [LAST_7], 3, now=NOW)

    assert [album.key for album in plans[0].albums] == ["B", "A"]
    assert plans[0].albums[0].last_played_at == _days_ago(0)
    assert plans[0].albums[1].last_played_at == _days_ago(1)


def test_z_suffix_at_window_boundary_included() -> None:
    now = datetime(2026, 9, 15, 12, 30, 45, tzinfo=UTC)
    same_day = WindowSpec(0, 0, "Same Day")
    listens = [
        _listen("A", "a1", "2026-09-15T12:30:45.000Z"),
        _listen("A", "a2", "2026-09-15T12:30:45.000Z"),
        _listen("A", "a3", "2026-09-15T12:30:45.000Z"),
    ]

    plans = group_albums_by_window(listens, [same_day], 3, now=now)

    assert [album.key for album in plans[0].albums] == ["A"]


def test_z_suffix_included_despite_lexical_order() -> None:
    # Window end bound is 12:30:45.000500+00:00; a listen at 12:30:45.000Z is
    # semantically inside but lexically sorts after the bound (Z > 5 and
    # ".000Z" vs "+00:00"), which the old string comparison got wrong.
    now = datetime(2026, 9, 15, 12, 30, 45, 500, tzinfo=UTC)
    last_day = WindowSpec(1, 0, "Last Day")
    listens = [
        _listen("A", "a1", "2026-09-15T12:30:45.000Z"),
        _listen("A", "a2", "2026-09-15T12:30:45.000Z"),
        _listen("A", "a3", "2026-09-15T12:30:45.000Z"),
    ]

    plans = group_albums_by_window(listens, [last_day], 3, now=now)

    assert [album.key for album in plans[0].albums] == ["A"]


def test_offset_less_played_at_treated_as_utc() -> None:
    # A valid ISO string with no offset parses to a naive datetime; it must be
    # treated as UTC so comparing it against the aware window bounds does not
    # raise TypeError.
    now = datetime(2026, 9, 15, 12, 30, 45, tzinfo=UTC)
    same_day = WindowSpec(0, 0, "Same Day")
    listens = [
        _listen("A", "a1", "2026-09-15T12:30:45"),
        _listen("A", "a2", "2026-09-15T12:30:45"),
        _listen("A", "a3", "2026-09-15T12:30:45"),
    ]

    plans = group_albums_by_window(listens, [same_day], 3, now=now)

    assert [album.key for album in plans[0].albums] == ["A"]


def test_albums_ordered_by_parsed_time_not_lexical_string() -> None:
    # "2026-01-15T12:00:00.500+00:00" is lexically earlier than
    # "2026-01-15T12:00:00Z" ('.' < 'Z') but is the later clock time; sorting by
    # the parsed datetime must put it first.
    now = datetime(2026, 1, 16, 0, 0, 0, tzinfo=UTC)
    last_day = WindowSpec(1, 0, "Last Day")
    listens = [
        _listen("LaterClock", "a1", "2026-01-15T12:00:00.500+00:00"),
        _listen("LaterClock", "a2", "2026-01-15T12:00:00.500+00:00"),
        _listen("EarlierClock", "b1", "2026-01-15T12:00:00Z"),
        _listen("EarlierClock", "b2", "2026-01-15T12:00:00Z"),
    ]

    plans = group_albums_by_window(listens, [last_day], 2, now=now)

    assert [album.key for album in plans[0].albums] == ["LaterClock", "EarlierClock"]
    assert [album.last_played_at for album in plans[0].albums] == [
        "2026-01-15T12:00:00.500+00:00",
        "2026-01-15T12:00:00Z",
    ]
