"""Pure planning logic for filing playlists into Spotify folders.

This module has no network or browser dependencies so it can be unit-tested
in isolation. It only decides *what* should happen; actually creating folders
and moving playlists is the job of ``app.folders``.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_ROOT = "Songipy"
DEFAULT_SUBFOLDERS: tuple[str, ...] = ("Albums", "Genres")


@dataclass(frozen=True)
class PlaylistTarget:
    """A Songipy-prefixed playlist that maps onto a desired folder path."""

    name: str
    root: str | None
    subfolder: str
    label: str
    folder_path: tuple[str, ...]  # desired folder path, e.g. ("Songipy", "Albums")


@dataclass(frozen=True)
class FolderPlan:
    """The full set of actions needed to file playlists into folders."""

    create_folders: list[tuple[str, ...]]  # ordered, parents before children, deduped
    moves: list[tuple[str, tuple[str, ...]]]  # (playlist name, target path)
    skipped: list[str]  # already in the right place
    unrecognized: list[str]  # Songipy-prefixed but not root/<subfolder>/<label>


def parse_playlist_name(
    name: str,
    *,
    root: str = DEFAULT_ROOT,
    subfolders: tuple[str, ...] = DEFAULT_SUBFOLDERS,
) -> PlaylistTarget | None:
    """Parse a playlist name shaped ``root/<subfolder>/<label>``.

    Segments are whitespace-stripped (the ``root`` parameter is stripped too).
    Returns ``None`` when the name does not match the expected shape (wrong
    root, missing/extra segments, an unknown subfolder, an empty label, or an
    empty root).
    """
    root = root.strip()
    segments = [segment.strip() for segment in name.split("/")]
    if len(segments) != 3 or not root or segments[0] != root:
        return None
    if segments[1] not in subfolders:
        return None
    if not segments[2]:
        return None
    return PlaylistTarget(
        name=name,
        root=segments[0],
        subfolder=segments[1],
        label=segments[2],
        folder_path=(segments[0], segments[1]),
    )


def desired_folder_path(target: PlaylistTarget, *, nested: bool) -> tuple[str, ...]:
    """Return the folder path a playlist should live in.

    Nested mode uses ``root/<subfolder>`` (e.g. ``("Songipy", "Albums")``);
    flat mode falls back to a single level ``"root <subfolder>"`` (e.g.
    ``("Songipy Albums",)``) for web players that cannot nest folders.
    """
    if nested:
        return target.folder_path
    return (f"{target.root} {target.subfolder}",)


def folder_name_for(
    target: PlaylistTarget,
    *,
    root: str = DEFAULT_ROOT,
    flat: bool = True,
) -> str:
    """Return the real Spotify folder name for a playlist target.

    Flat mode (the MVP) uses a single folder named ``"<root> <subfolder>"``
    (e.g. ``"Songipy Albums"``). Nested folders are not implemented in the MVP,
    so ``flat=False`` returns the same flat name; ``root`` is stripped and an
    empty root falls back to just the subfolder name.
    """
    del flat  # nested folders are not implemented in the MVP
    root = root.strip()
    return f"{root} {target.subfolder}".strip()


def decide_actions(
    playlists: list[PlaylistTarget],
    existing_folders: set[tuple[str, ...]],
    existing_placements: dict[str, tuple[str, ...]],
    *,
    nested: bool,
    unrecognized: list[str] | None = None,
) -> FolderPlan:
    """Compute the actions needed to file ``playlists`` into folders.

    ``existing_folders`` is the set of folder paths that already exist;
    ``existing_placements`` maps playlist name -> current folder path. Targets
    whose current placement already equals the desired path are skipped; every
    other target becomes a move. Desired folder paths not already present are
    queued for creation with parents before children, deduped in first-seen
    order. Any candidate path that equals or is a prefix of some existing
    placement (``existing_placements.values()``) is never queued for creation:
    a playlist placed in a folder implies that folder and every ancestor
    exists, even when ``existing_folders`` under-reports them. ``unrecognized``
    names are passed through unchanged.
    """
    desired_paths: list[tuple[str, ...]] = [
        desired_folder_path(target, nested=nested) for target in playlists
    ]

    moves: list[tuple[str, tuple[str, ...]]] = []
    skipped: list[str] = []
    for target, desired in zip(playlists, desired_paths, strict=True):
        if existing_placements.get(target.name) == desired:
            skipped.append(target.name)
        else:
            moves.append((target.name, desired))

    create_folders: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    existing_placement_paths = set(existing_placements.values())
    for path in desired_paths:
        for depth in range(1, len(path) + 1):
            prefix = path[:depth]
            if prefix in existing_folders or prefix in seen:
                continue
            # A playlist placed in a folder implies that folder and every
            # ancestor already exists, even when existing_folders
            # under-reports them (inconsistent DOM reads).
            if any(placed[: len(prefix)] == prefix for placed in existing_placement_paths):
                continue
            seen.add(prefix)
            create_folders.append(prefix)

    return FolderPlan(
        create_folders=create_folders,
        moves=moves,
        skipped=skipped,
        unrecognized=list(unrecognized) if unrecognized is not None else [],
    )
