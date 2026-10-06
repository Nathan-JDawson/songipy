"""Command-line interface for the Spotify playlist generator."""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import albums, api, auth, classify, config, folder_plan, folders, import_history, library
from app import db as db_module
from app import playlists as playlists_module
from app import poll as poll_module

logger = logging.getLogger(__name__)


def _format_played_at(value: str | None) -> str:
    if not value:
        return "?"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_spotify(scopes: list[str]):
    settings = config.get_settings()
    if settings.spotify_refresh_token:
        return auth.get_client_from_refresh_token(scopes)
    return auth.get_local_spotify(scopes)


def _open_db() -> db_module.Database:
    database = db_module.Database(config.get_database_url())
    db_module.create_schema(database)
    return database


def _cmd_auth(args: argparse.Namespace) -> int:
    spotify = auth.get_local_spotify(auth.SCOPES_ALL)
    user = spotify.me()
    name = user.get("display_name") or user.get("id") or "unknown user"
    print(f"Authenticated as {name}.")
    return 0


def _cmd_import(args: argparse.Namespace) -> int:
    with db_module.Database(config.get_database_url()) as database:
        db_module.create_schema(database)
        count = import_history.import_export(args.path, database)
    print(f"Imported {count} listens.")
    return 0


def _cmd_poll(args: argparse.Namespace) -> int:
    database = _open_db()
    spotify = _get_spotify(auth.SCOPES_POLL)
    count = poll_module.poll_recent(spotify, database)
    print(f"Inserted {count} new listens.")
    return 0


def _cmd_recent(args: argparse.Namespace) -> int:
    database = _open_db()
    for row in db_module.latest_listens(database, args.count):
        played_at = _format_played_at(row.get("played_at"))
        track_name = row.get("track_name") or "Unknown track"
        artist_name = row.get("artist_name") or "Unknown artist"
        album_name = row.get("album_name") or "Unknown album"
        print(f"{played_at}  {track_name} — {artist_name} — {album_name}")
    return 0


def _saved_tracks(spotify, limit: int | None) -> list[dict]:
    return list(library.iter_saved_tracks(spotify, limit=limit))


def _dedupe_genre_mapping(mapping: dict[str, list[dict]], mode: str) -> dict[str, list[dict]]:
    """Apply per-album track dedupe for ``mode`` (no-op for the "all" mode)."""
    if mode == config.TRACK_SELECTION_ALL:
        return mapping
    database = _open_db()
    listen_stats = db_module.listen_stats_by_uri(database)
    cap = config.genre_max_tracks_per_album()
    return {
        genre: classify.dedupe_album_tracks(genre_tracks, listen_stats, cap, mode)
        for genre, genre_tracks in mapping.items()
    }


def _create_genre_playlists(
    spotify: Any, mapping: dict[str, list[dict]], *, dry_run: bool, user_id: str | None = None
) -> None:
    """Create (or, for ``dry_run``, print) one playlist per genre."""
    for genre, genre_tracks in sorted(mapping.items()):
        name = config.make_playlist_name("genre", genre)
        if dry_run:
            print(f"[dry-run] {name} ({len(genre_tracks)} tracks)")
            continue
        playlist_id = playlists_module.create_playlist(spotify, name, user_id=user_id)
        track_uris = [track["uri"] for track in genre_tracks]
        playlists_module.add_tracks(spotify, playlist_id, track_uris)
        print(f"{name} ({len(genre_tracks)} tracks)")


def _cmd_sync_genres(args: argparse.Namespace) -> int:
    spotify = _get_spotify(auth.SCOPES_ALL)
    tracks = _saved_tracks(spotify, getattr(args, "top", None))
    mapping = classify.genre_playlist_map(spotify, tracks)
    mode = getattr(args, "tracks", config.genre_track_selection())
    mapping = _dedupe_genre_mapping(mapping, mode)
    kept = classify.keep_min_genres(mapping, config.MIN_PLAYLIST_TRACKS)
    print(
        f"skipped {len(mapping) - len(kept)} genres with fewer than "
        f"{config.MIN_PLAYLIST_TRACKS} tracks"
    )
    if not kept:
        print("No genres found for the saved tracks.")
        return 0
    user_id = api.call_with_retry(spotify.me)["id"] if not getattr(args, "dry_run", False) else None
    _create_genre_playlists(spotify, kept, dry_run=getattr(args, "dry_run", False), user_id=user_id)
    return 0


def _print_album_plans(plans: list[albums.WindowPlan]) -> None:
    """Print the dry-run representation of one plan per window."""
    for plan in plans:
        if not plan.albums:
            continue
        names = ", ".join(album.name for album in plan.albums)
        name = config.make_playlist_name("albums", plan.spec.label)
        count = len(plan.albums)
        plural = "" if count == 1 else "s"
        print(f"[dry-run] {name} ({count} album{plural}): {names}")


def _resolve_album_ids(plans: list[albums.WindowPlan], spotify: Any) -> dict[str, str]:
    """Resolve each album key to its Spotify album id via a representative track."""
    album_to_track: dict[str, str] = {}
    for plan in plans:
        for album in plan.albums:
            album_to_track.setdefault(album.key, album.track_uri)
    uris = [uri for uri in album_to_track.values() if uri]
    uri_to_album = library.resolve_album_ids(spotify, uris)
    return {
        key: uri_to_album[track_uri]
        for key, track_uri in album_to_track.items()
        if track_uri in uri_to_album
    }


def _create_album_playlists(
    spotify: Any,
    plans: list[albums.WindowPlan],
    album_id_cache: dict[str, str],
    user_id: str | None = None,
) -> None:
    """Create one playlist per window from the resolved album track lists."""
    album_to_name = {album.key: album.name for plan in plans for album in plan.albums}
    for plan in plans:
        track_uris: list[str] = []
        for album in plan.albums:
            album_id = album_id_cache.get(album.key)
            if album_id is None:
                logger.warning(
                    "Could not resolve album id for %r (%s); skipping",
                    album.key,
                    album_to_name.get(album.key, album.key),
                )
                continue
            track_uris.extend(library.get_album_tracks(spotify, album_id))
        if not track_uris:
            logger.warning("Skipping window with no resolvable tracks: %r", plan.spec.label)
            continue
        name = config.make_playlist_name("albums", plan.spec.label)
        playlist_id = playlists_module.create_playlist(spotify, name, user_id=user_id)
        playlists_module.add_tracks(spotify, playlist_id, track_uris)
        count = len(plan.albums)
        plural = "" if count == 1 else "s"
        print(f"{name} ({count} album{plural})")


def _cmd_sync_albums(args: argparse.Namespace) -> int:
    database = _open_db()
    listens = db_module.all_listens_ordered(database)
    windows = [albums.WindowSpec(*window) for window in config.ALBUM_WINDOWS]
    plans = albums.group_albums_by_window(listens, windows, config.MIN_TRACKS_PER_ALBUM)

    if all(not plan.albums for plan in plans):
        print("No albums found in any window.")
        return 0

    if getattr(args, "top", None) is not None:
        plans = [replace(plan, albums=plan.albums[: max(0, args.top)]) for plan in plans]

    if getattr(args, "dry_run", False):
        _print_album_plans(plans)
        return 0

    spotify = _get_spotify(auth.SCOPES_ALL)
    user_id = api.call_with_retry(spotify.me)["id"]
    album_id_cache = _resolve_album_ids(plans, spotify)
    _create_album_playlists(spotify, plans, album_id_cache, user_id=user_id)
    return 0


def _iter_user_playlists(spotify):
    """Yield all of the user's playlists, following spotipy's paging."""
    page = api.call_with_retry(spotify.current_user_playlists, limit=50)
    while page is not None:
        yield from page.get("items", [])
        if not page.get("next"):
            break
        page = api.call_with_retry(spotify.next, page)


def _cmd_prune(args: argparse.Namespace) -> int:
    """Delete all Songipy-prefixed playlists owned by the current user.

    The live path requires ``--yes`` because deletion is permanent; ``--dry-run``
    only lists the playlists that would be deleted.
    """
    spotify = _get_spotify(auth.SCOPES_ALL)
    user_id = api.call_with_retry(spotify.me)["id"]

    prefix = f"{config.PLAYLIST_ROOT}/" if config.PLAYLIST_ROOT else ""
    subfolder_prefixes = [f"{sub}/" for sub in config.folder_subfolders()]

    targets: list[dict] = []
    for playlist in _iter_user_playlists(spotify):
        name = playlist.get("name") or ""
        if (playlist.get("owner") or {}).get("id") != user_id:
            continue
        if prefix:
            if name.startswith(prefix):
                targets.append(playlist)
        elif any(name.startswith(sub) for sub in subfolder_prefixes):
            targets.append(playlist)

    if getattr(args, "dry_run", False):
        print(f"[dry-run] would delete {len(targets)} playlist(s)")
        for playlist in targets:
            print(f"  {playlist.get('name')}")
        return 0

    if not getattr(args, "yes", False):
        print(
            "Refusing to delete playlists without confirmation: deletion is "
            "permanent. Re-run with --yes to confirm.",
            file=sys.stderr,
        )
        return 2

    for playlist in targets:
        api.call_with_retry(spotify.current_user_unfollow_playlist, playlist.get("id"))
    print(f"deleted {len(targets)} playlist(s)")
    return 0


def _default_chrome_profile_dir() -> str:
    """Return the default dedicated Chrome profile path under the repo root."""
    repo_root = Path(__file__).resolve().parents[2]
    return str(repo_root / ".spotify-chrome-profile")


def _collect_playlist_targets(
    spotify: Any,
) -> tuple[list[folder_plan.PlaylistTarget], dict[str, str], list[str]]:
    """Return (targets, uri_by_name, unrecognized) for the user's Songipy playlists."""
    prefix = f"{config.PLAYLIST_ROOT}/" if config.PLAYLIST_ROOT else ""
    targets: list[folder_plan.PlaylistTarget] = []
    uri_by_name: dict[str, str] = {}
    unrecognized: list[str] = []
    for playlist in _iter_user_playlists(spotify):
        name = playlist.get("name") or ""
        if prefix and not name.startswith(prefix):
            continue
        target = folder_plan.parse_playlist_name(
            name,
            root=config.PLAYLIST_ROOT,
            subfolders=config.folder_subfolders(),
        )
        if target is None:
            unrecognized.append(name)
        else:
            uri_by_name[name] = playlist.get("uri") or ""
            targets.append(target)
    return targets, uri_by_name, unrecognized


def _print_organize_plan(plan: folder_plan.FolderPlan) -> None:
    """Print the dry-run representation of a folder plan."""
    print(f"folders to create: {len(plan.create_folders)}")
    for path in plan.create_folders:
        print(f"  [dry-run] create folder {path[-1]!r}")
    print(f"moves: {len(plan.moves)}")
    for name, path in plan.moves:
        print(f"  [dry-run] move {name!r} -> {path[-1]!r}")
    print(f"skipped: {len(plan.skipped)}")
    for name in plan.skipped:
        print(f"  [dry-run] already placed {name!r}")
    print(f"unrecognized: {len(plan.unrecognized)}")
    for name in plan.unrecognized:
        print(f"  [dry-run] unrecognized {name!r}")


def _apply_organize_plan(
    plan: folder_plan.FolderPlan,
    driver: folders.FolderDriver,
    targets: list[folder_plan.PlaylistTarget],
    uri_by_name: dict[str, str],
    folder_map: dict[tuple[str, ...], str],
) -> None:
    """Create the plan's folders and move its playlists, printing the outcome."""
    folder_name_by_path = {
        folder_plan.desired_folder_path(target, nested=False): folder_plan.folder_name_for(
            target, root=config.PLAYLIST_ROOT
        )
        for target in targets
    }
    folder_start_uri_by_path = dict(folder_map)
    created_folders: list[str] = []
    for path in plan.create_folders:
        start_uri = driver.create_folder(path, folder_name_by_path[path])
        folder_start_uri_by_path[path] = start_uri
        created_folders.append(path[-1])
    moved: list[tuple[str, str]] = []
    for name, path in plan.moves:
        start_uri = folder_start_uri_by_path.get(path)
        if start_uri is None:
            raise RuntimeError(f"no start-group URI known for folder path {path!r}")
        driver.move_playlist(uri_by_name[name], start_uri)
        moved.append((name, path[-1]))
    for folder_name in created_folders:
        print(f"created folder {folder_name!r}")
    for name, folder_name in moved:
        print(f"moved {name!r} -> {folder_name!r}")
    print(
        f"created {len(created_folders)} folder(s), "
        f"moved {len(moved)} playlist(s), skipped {len(plan.skipped)}"
    )
    for name in plan.skipped:
        print(f"  already placed {name!r}")
    for name in plan.unrecognized:
        print(f"  unrecognized {name!r}")


def _resolve_spotify_username(settings: config.Settings, spotify: Any) -> str:
    """Return the account username for spclient URLs, from settings or the Web API."""
    username = settings.spotify_username
    if not username:
        me = spotify.me()
        username = me.get("id") or ""
    if not username:
        raise RuntimeError("could not determine the Spotify username; set SPOTIFY_USERNAME")
    return username


def _build_existing_placements(
    placements: dict[str, tuple[str, ...] | None],
    uri_by_name: dict[str, str],
) -> dict[str, tuple[str, ...]]:
    """Map Songipy playlist names to their current folder paths from the rootlist.

    Only playlists that appear in ``uri_by_name`` (the Web API name <-> uri list)
    are interesting; unknown names are ignored. ``None`` (library root) maps to
    the empty tuple.
    """
    uri_to_name = {uri: name for name, uri in uri_by_name.items() if uri}
    existing: dict[str, tuple[str, ...]] = {}
    for uri, path in placements.items():
        name = uri_to_name.get(uri)
        if name is None:
            continue
        existing[name] = path or ()
    return existing


def _cmd_organize(args: argparse.Namespace) -> int:
    """File Songipy-prefixed playlists into real Spotify folders (local-only).

    The live path launches the logged-in Playwright profile and drives the web
    player's internal rootlist API; ``--dry-run`` lists the same plan without a
    folder browser (it still authenticates via the Web API to list playlists).
    """
    settings = config.get_settings()
    spotify = _get_spotify(auth.SCOPES_ALL)
    targets, uri_by_name, unrecognized = _collect_playlist_targets(spotify)

    if getattr(args, "dry_run", False):
        # NOTE: dry-run does not launch the folder browser, so it cannot see
        # existing folders/placements.  The plan assumes a clean slate.
        plan = folder_plan.decide_actions(
            targets,
            existing_folders=set(),
            existing_placements={},
            nested=False,
            unrecognized=unrecognized,
        )
        _print_organize_plan(plan)
        return 0

    username = _resolve_spotify_username(settings, spotify)
    user_data_dir = settings.spotify_chrome_profile or _default_chrome_profile_dir()
    driver = folders.PlaywrightFolderDriver(
        folders.DriverConfig(
            user_data_dir=user_data_dir,
            channel=settings.spotify_chrome_channel,
            headful=not settings.folder_sync_headless,
            username=username,
        )
    )
    try:
        driver.open()
        folder_map = driver.list_folders()
        existing_placements = _build_existing_placements(driver.list_placements(), uri_by_name)
        plan = folder_plan.decide_actions(
            targets,
            existing_folders=set(folder_map),
            existing_placements=existing_placements,
            nested=False,
            unrecognized=unrecognized,
        )
        _apply_organize_plan(plan, driver, targets, uri_by_name, folder_map)
    finally:
        driver.close()
    return 0


def _add_shared_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=argparse.SUPPRESS,
        help="compute and print playlists without writing to Spotify",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=argparse.SUPPRESS,
        help="limit saved tracks (sync-genres) or albums per window (sync-albums)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app",
        description="Generate Spotify playlists from your library and listening history.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    auth_parser = subparsers.add_parser("auth", help="run interactive Spotify login")
    auth_parser.set_defaults(func=_cmd_auth)

    import_parser = subparsers.add_parser("import", help="import a history export")
    import_parser.add_argument("path", help="directory or .zip export to import")
    import_parser.set_defaults(func=_cmd_import)

    poll_parser = subparsers.add_parser("poll", help="poll recently-played tracks")
    poll_parser.set_defaults(func=_cmd_poll)

    recent_parser = subparsers.add_parser("recent", help="print recent listens")
    recent_parser.add_argument("count", nargs="?", type=int, default=10)
    recent_parser.set_defaults(func=_cmd_recent)

    for name, handler, help_text in (
        ("sync-genres", _cmd_sync_genres, "create playlists per genre"),
        (
            "sync-albums",
            _cmd_sync_albums,
            "create playlists of recently-listened albums per date range",
        ),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        _add_shared_options(sub)
        if name == "sync-genres":
            sub.add_argument(
                "--tracks",
                choices=config.GENRE_TRACK_SELECTION_CHOICES,
                default=config.genre_track_selection(),
                help="how to select/dedupe tracks per album: all (no dedupe), "
                "listened (rank by local listen stats; default), popular "
                "(rank by track popularity)",
            )
        sub.set_defaults(func=handler)

    prune_parser = subparsers.add_parser(
        "prune",
        help="delete all Songipy-prefixed playlists (permanent; requires --yes)",
    )
    prune_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=argparse.SUPPRESS,
        help="list the playlists that would be deleted without deleting anything",
    )
    prune_parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm deletion; deleted playlists cannot be recovered",
    )
    prune_parser.set_defaults(func=_cmd_prune)

    organize_parser = subparsers.add_parser(
        "organize",
        help="move Songipy playlists into real Spotify folders via the internal rootlist API",
    )
    organize_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=argparse.SUPPRESS,
        help="list the plan without launching a folder browser "
        "(playlists are still read via the Web API)",
    )
    organize_parser.set_defaults(func=_cmd_organize)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
