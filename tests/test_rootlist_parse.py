"""Unit tests for the pure rootlist item-list parser (no browser required)."""

from app.rootlist import parse_rootlist_items, stable_start_group_uri


def _items(*uris: str) -> list[dict]:
    return [{"uri": uri, "attributes": {}} for uri in uris]


def test_stable_start_group_uri_strips_name_suffix() -> None:
    assert (
        stable_start_group_uri("spotify:start-group:a862f2e932f7be38:My+Shit")
        == "spotify:start-group:a862f2e932f7be38"
    )


def test_stable_start_group_uri_rejects_non_start_group() -> None:
    for bad in ("spotify:end-group:abcd", "spotify:playlist:xyz"):
        try:
            stable_start_group_uri(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {bad!r}")


def test_parse_rootlist_flat_folders_and_placements() -> None:
    items = _items(
        "spotify:playlist:root_playlist",
        "spotify:start-group:aaaabbbbccccdddd:My+Shit",
        "spotify:playlist:p1",
        "spotify:end-group:aaaabbbbccccdddd",
        "spotify:playlist:after_folder",
    )
    folders, placements = parse_rootlist_items(items)

    assert folders == {("My Shit",): "spotify:start-group:aaaabbbbccccdddd"}
    assert placements == {
        "spotify:playlist:root_playlist": None,
        "spotify:playlist:p1": ("My Shit",),
        "spotify:playlist:after_folder": None,
    }


def test_parse_rootlist_nested_pairs() -> None:
    items = _items(
        "spotify:start-group:1111222233334444:Parent",
        "spotify:playlist:in_parent",
        "spotify:start-group:5555666677778888:Child",
        "spotify:playlist:in_child",
        "spotify:end-group:5555666677778888",
        "spotify:end-group:1111222233334444",
        "spotify:playlist:after_all",
    )
    folders, placements = parse_rootlist_items(items)

    assert folders == {
        ("Parent",): "spotify:start-group:1111222233334444",
        ("Parent", "Child"): "spotify:start-group:5555666677778888",
    }
    assert placements == {
        "spotify:playlist:in_parent": ("Parent",),
        "spotify:playlist:in_child": ("Parent", "Child"),
        "spotify:playlist:after_all": None,
    }


def test_parse_rootlist_unquotes_urlencoded_names() -> None:
    items = _items(
        "spotify:start-group:aaaabbbbccccdddd:Other%27s+Mix",
        "spotify:playlist:p1",
        "spotify:end-group:aaaabbbbccccdddd",
    )
    folders, placements = parse_rootlist_items(items)

    assert folders == {("Other's Mix",): "spotify:start-group:aaaabbbbccccdddd"}
    assert placements["spotify:playlist:p1"] == ("Other's Mix",)


def test_parse_rootlist_empty_items() -> None:
    folders, placements = parse_rootlist_items([])
    assert folders == {}
    assert placements == {}


def test_parse_rootlist_unmatched_end_group_is_ignored() -> None:
    items = _items(
        "spotify:end-group:deadbeefdeadbeef",
        "spotify:playlist:p1",
    )
    folders, placements = parse_rootlist_items(items)
    assert folders == {}
    assert placements == {"spotify:playlist:p1": None}


def test_parse_rootlist_empty_name_group_keeps_parent_nesting() -> None:
    items = _items(
        "spotify:start-group:1111222233334444:Parent",
        "spotify:start-group:5555666677778888:",
        "spotify:end-group:5555666677778888",
        "spotify:playlist:after_empty",
        "spotify:end-group:1111222233334444",
        "spotify:playlist:after_parent",
    )
    folders, placements = parse_rootlist_items(items)

    assert folders == {("Parent",): "spotify:start-group:1111222233334444"}
    assert all("" not in path for path in folders)
    assert placements == {
        "spotify:playlist:after_empty": ("Parent",),
        "spotify:playlist:after_parent": None,
    }
