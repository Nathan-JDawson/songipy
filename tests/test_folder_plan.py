"""Unit tests for the pure folder-planning logic (no Playwright import)."""

import dataclasses

import pytest

from app.folder_plan import (
    FolderPlan,
    PlaylistTarget,
    decide_actions,
    desired_folder_path,
    folder_name_for,
    parse_playlist_name,
)


def _albums(label: str = "Last 7 Days — 2026-09-15 01:40") -> PlaylistTarget | None:
    return parse_playlist_name(f"Songipy/Albums/{label}")


def _genres(label: str = "metalcore — 2026-09-15 01:40") -> PlaylistTarget | None:
    return parse_playlist_name(f"Songipy/Genres/{label}")


# -- parse_playlist_name -----------------------------------------------------


def test_parse_playlist_name_albums_happy_path() -> None:
    name = "Songipy/Albums/Last 7 Days — 2026-09-15 01:40"
    target = parse_playlist_name(name)
    assert target is not None
    assert target.name == name
    assert target.root == "Songipy"
    assert target.subfolder == "Albums"
    assert target.label == "Last 7 Days — 2026-09-15 01:40"
    assert target.folder_path == ("Songipy", "Albums")


def test_parse_playlist_name_genre_happy_path() -> None:
    name = "Songipy/Genres/metalcore — 2026-09-15 01:40"
    target = parse_playlist_name(name)
    assert target is not None
    assert target.subfolder == "Genres"
    assert target.label == "metalcore — 2026-09-15 01:40"
    assert target.folder_path == ("Songipy", "Genres")


def test_parse_playlist_name_frozen_dataclass_equality() -> None:
    name = "Songipy/Albums/Last 7 Days — 2026-09-15 01:40"
    assert parse_playlist_name(name) == PlaylistTarget(
        name=name,
        root="Songipy",
        subfolder="Albums",
        label="Last 7 Days — 2026-09-15 01:40",
        folder_path=("Songipy", "Albums"),
    )


def test_parse_playlist_name_rejects_wrong_root() -> None:
    assert parse_playlist_name("Other/Albums/foo") is None


def test_parse_playlist_name_rejects_no_subfolder() -> None:
    assert parse_playlist_name("Songipy/foo") is None


def test_parse_playlist_name_rejects_extra_segments() -> None:
    assert parse_playlist_name("Songipy/Albums/foo/bar") is None


def test_parse_playlist_name_rejects_unknown_subfolder() -> None:
    assert parse_playlist_name("Songipy/Mixed/foo") is None


def test_parse_playlist_name_rejects_empty_root() -> None:
    assert parse_playlist_name("Songipy/Albums/foo", root="") is None


def test_parse_playlist_name_rejects_empty_label() -> None:
    assert parse_playlist_name("Songipy/Albums/") is None
    assert parse_playlist_name("Songipy/Albums/   ") is None


def test_parse_playlist_name_rejects_empty_root_guard_distinct_from_mismatch() -> None:
    # Exercises the `not root` guard specifically: with an empty root there is
    # nothing to match, so the name is rejected even before segment comparison.
    assert parse_playlist_name("/Albums/foo", root="") is None


def test_parse_playlist_name_strips_root_parameter() -> None:
    target = parse_playlist_name("Songipy/Albums/foo", root="  Songipy ")
    assert target is not None
    assert target.root == "Songipy"
    assert target.label == "foo"


def test_parse_playlist_name_strips_whitespace() -> None:
    target = parse_playlist_name("  Songipy / Albums / Last 7 Days — 2026-09-15 01:40 ")
    assert target is not None
    assert target.subfolder == "Albums"
    assert target.label == "Last 7 Days — 2026-09-15 01:40"


def test_playlist_target_is_frozen() -> None:
    target = _albums()
    assert target is not None
    with pytest.raises(dataclasses.FrozenInstanceError):
        target.label = "changed"  # type: ignore[misc]


# -- desired_folder_path -----------------------------------------------------


def test_desired_folder_path_nested() -> None:
    target = _albums()
    assert target is not None
    assert desired_folder_path(target, nested=True) == ("Songipy", "Albums")


def test_desired_folder_path_flat() -> None:
    target = _genres()
    assert target is not None
    assert desired_folder_path(target, nested=False) == ("Songipy Genres",)


# -- folder_name_for --------------------------------------------------------


def test_folder_name_for_flat_albums() -> None:
    target = _albums()
    assert target is not None
    assert folder_name_for(target) == "Songipy Albums"


def test_folder_name_for_flat_genres() -> None:
    target = _genres()
    assert target is not None
    assert folder_name_for(target) == "Songipy Genres"


def test_folder_name_for_flat_false_returns_flat_name() -> None:
    # Nested folders are not implemented in the MVP; `flat=False` still returns
    # the flat name.
    target = _albums()
    assert target is not None
    assert folder_name_for(target, flat=False) == "Songipy Albums"


def test_folder_name_for_strips_root_parameter() -> None:
    target = _albums()
    assert target is not None
    assert folder_name_for(target, root="  Songipy ") == "Songipy Albums"


def test_folder_name_for_empty_root_uses_subfolder() -> None:
    target = _albums()
    assert target is not None
    assert folder_name_for(target, root="") == "Albums"


# -- decide_actions ----------------------------------------------------------


def test_decide_actions_create_folders_parent_before_child_deduped() -> None:
    targets = [_albums(), _genres(), _albums("Last 30 Days — 2026-09-15 01:40")]
    plan = decide_actions(targets, existing_folders=set(), existing_placements={}, nested=True)

    assert plan.create_folders == [
        ("Songipy",),
        ("Songipy", "Albums"),
        ("Songipy", "Genres"),
    ]
    assert len(plan.moves) == 3
    assert plan.moves[0] == ("Songipy/Albums/Last 7 Days — 2026-09-15 01:40", ("Songipy", "Albums"))
    assert plan.skipped == []
    assert plan.unrecognized == []


def test_decide_actions_skips_when_already_placed() -> None:
    name = "Songipy/Albums/Last 7 Days — 2026-09-15 01:40"
    targets = [_albums()]
    plan = decide_actions(
        targets,
        existing_folders={("Songipy",), ("Songipy", "Albums")},
        existing_placements={name: ("Songipy", "Albums")},
        nested=True,
    )
    assert plan.skipped == [name]
    assert plan.moves == []
    assert plan.create_folders == []


def test_decide_actions_moves_only_misplaced() -> None:
    albums_name = "Songipy/Albums/Last 7 Days — 2026-09-15 01:40"
    genres_name = "Songipy/Genres/metalcore — 2026-09-15 01:40"
    targets = [_albums(), _genres()]
    plan = decide_actions(
        targets,
        existing_folders=set(),
        existing_placements={albums_name: ("Songipy", "Albums")},  # already right
        nested=True,
    )
    assert plan.skipped == [albums_name]
    assert plan.moves == [(genres_name, ("Songipy", "Genres"))]
    # ("Songipy", "Albums") already holds a playlist, so it and its ancestor
    # ("Songipy",) exist even though existing_folders is empty in this stub
    # state; only the Genres folder is queued for creation.
    assert plan.create_folders == [("Songipy", "Genres")]


def test_decide_actions_create_folders_excludes_placed_paths() -> None:
    # A playlist already placed in ("Songipy", "Albums") proves that folder AND
    # its ancestor ("Songipy",) exist, even when existing_folders
    # under-reports them (inconsistent DOM reads). Neither the desired path nor
    # any ancestor may be queued for creation; unrelated paths still are.
    albums_name = "Songipy/Albums/Last 7 Days — 2026-09-15 01:40"
    targets = [_albums(), _genres()]
    plan = decide_actions(
        targets,
        existing_folders=set(),
        existing_placements={albums_name: ("Songipy", "Albums")},
        nested=True,
    )
    assert plan.skipped == [albums_name]
    assert plan.moves == [("Songipy/Genres/metalcore — 2026-09-15 01:40", ("Songipy", "Genres"))]
    assert ("Songipy",) not in plan.create_folders  # ancestor of placement
    assert ("Songipy", "Albums") not in plan.create_folders  # placement itself
    assert ("Songipy", "Genres") in plan.create_folders  # unrelated path
    assert plan.create_folders == [("Songipy", "Genres")]


def test_decide_actions_create_folders_excludes_placed_paths_flat() -> None:
    # Flat mode uses single-level folder paths, so the placement path itself is
    # the only excluded candidate (it has no deeper ancestors); unrelated paths
    # are still queued.
    albums_name = "Songipy/Albums/Last 7 Days — 2026-09-15 01:40"
    targets = [_albums(), _genres()]
    plan = decide_actions(
        targets,
        existing_folders=set(),
        existing_placements={albums_name: ("Songipy Albums",)},
        nested=False,
    )
    assert plan.skipped == [albums_name]
    assert plan.moves == [("Songipy/Genres/metalcore — 2026-09-15 01:40", ("Songipy Genres",))]
    assert ("Songipy Albums",) not in plan.create_folders  # placement itself
    assert ("Songipy Genres",) in plan.create_folders  # unrelated path
    assert plan.create_folders == [("Songipy Genres",)]


def test_decide_actions_flat_folder_paths() -> None:
    targets = [_albums(), _genres()]
    plan = decide_actions(targets, existing_folders=set(), existing_placements={}, nested=False)

    assert plan.create_folders == [("Songipy Albums",), ("Songipy Genres",)]
    assert plan.moves == [
        ("Songipy/Albums/Last 7 Days — 2026-09-15 01:40", ("Songipy Albums",)),
        ("Songipy/Genres/metalcore — 2026-09-15 01:40", ("Songipy Genres",)),
    ]


def test_decide_actions_existing_folders_not_recreated() -> None:
    targets = [_albums()]
    plan = decide_actions(
        targets,
        existing_folders={("Songipy",), ("Songipy", "Albums")},
        existing_placements={},
        nested=True,
    )
    assert plan.create_folders == []


def test_decide_actions_unrecognized_passed_through() -> None:
    plan = decide_actions(
        [],
        existing_folders=set(),
        existing_placements={},
        nested=True,
        unrecognized=["Songipy/messy/name"],
    )
    assert plan.unrecognized == ["Songipy/messy/name"]


def test_decide_actions_empty_inputs() -> None:
    plan = decide_actions([], set(), {}, nested=True)
    assert plan == FolderPlan(create_folders=[], moves=[], skipped=[], unrecognized=[])
