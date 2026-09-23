"""Command-line interface for the Spotify playlist generator."""

from __future__ import annotations

import argparse
import logging
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

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


def _open_db(*, write: bool = False) -> db_module.Database:
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
    database = _open_db(write=True)
    count = import_history.import_export(args.path, database)
    print(f"Imported {count} listens.")
    return 0


def _cmd_poll(args: argparse.Namespace) -> int:
    database = _open_db(write=True)
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
    tracks: list[dict] = []
    for index, track in enumerate(library.iter_saved_tracks(spotify)):
        if limit is not None and index >= limit:
            break
        tracks.append(track)
    return tracks


def _cmd_sync_genres(args: argparse.Namespace) -> int:
    spotify = _get_spotify(auth.SCOPES_ALL)
    tracks = _saved_tracks(spotify, args.top)
    mapping = classify.genre_playlist_map(spotify, tracks)
    kept = classify.keep_min_genres(mapping, config.MIN_PLAYLIST_TRACKS)
    print(
        f"skipped {len(mapping) - len(kept)} genres with fewer than "
        f"{config.MIN_PLAYLIST_TRACKS} tracks"
    )

    if not kept:
        print("No genres found for the saved tracks.")
        return 0

    for genre, track_uris in sorted(kept.items()):
        name = config.make_playlist_name("genre", genre)
        if args.dry_run:
            print(f"[dry-run] {name} ({len(track_uris)} tracks)")
            continue
        playlist_id = playlists_module.create_playlist(spotify, name)
        playlists_module.add_tracks(spotify, playlist_id, track_uris)
        print(f"{name} ({len(track_uris)} tracks)")
    return 0


def _cmd_sync_albums(args: argparse.Namespace) -> int:
    database = _open_db()
    listens = db_module.all_listens_ordered(database)

    windows = [albums.WindowSpec(*window) for window in config.ALBUM_WINDOWS]
    plans = albums.group_albums_by_window(listens, windows, config.MIN_TRACKS_PER_ALBUM)

    if all(not plan.albums for plan in plans):
        print("No albums found in any window.")
        return 0

    if args.top is not None:
        limit = max(0, args.top)
        plans = [replace(plan, albums=plan.albums[:limit]) for plan in plans]

    if args.dry_run:
        for plan in plans:
            if not plan.albums:
                continue
            names = ", ".join(album.name for album in plan.albums)
            name = config.make_playlist_name("albums", plan.spec.label)
            count = len(plan.albums)
            plural = "" if count == 1 else "s"
            print(f"[dry-run] {name} ({count} album{plural}): {names}")
        return 0

    spotify = _get_spotify(auth.SCOPES_ALL)

    all_keys = list(dict.fromkeys(album.key for plan in plans for album in plan.albums))
    album_to_track: dict[str, str] = {}
    album_to_name: dict[str, str] = {}
    for plan in plans:
        for album in plan.albums:
            album_to_track.setdefault(album.key, album.track_uri)
            album_to_name.setdefault(album.key, album.name)

    uris = [album_to_track[key] for key in all_keys if album_to_track.get(key)]
    uri_to_album = library.resolve_album_ids(spotify, uris)
    album_id_cache: dict[str, str] = {
        key: uri_to_album[album_to_track[key]]
        for key in all_keys
        if album_to_track.get(key) in uri_to_album
    }

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
            track_uris.extend(library.iter_album_tracks(spotify, album_id))

        if not track_uris:
            logger.warning("Skipping window with no resolvable tracks: %r", plan.spec.label)
            continue

        name = config.make_playlist_name("albums", plan.spec.label)
        playlist_id = playlists_module.create_playlist(spotify, name)
        playlists_module.add_tracks(spotify, playlist_id, track_uris)
        count = len(plan.albums)
        plural = "" if count == 1 else "s"
        print(f"{name} ({count} album{plural})")
    return 0


def _iter_user_playlists(spotify):
    """Yield all of the user's playlists, following spotipy's paging."""
    page = api.call_with_retry(spotify.current_user_playlists, limit=50)
    while page is not None:
        yield from page.get("items", [])
        if not page.get("next"):
            break
        page = api.call_with_retry(spotify.next, page)


def _default_chrome_profile_dir() -> str:
    """Return the default dedicated Chrome profile path under the repo root."""
    repo_root = Path(__file__).resolve().parents[2]
    return str(repo_root / ".spotify-chrome-profile")


def _cmd_organize(args: argparse.Namespace) -> int:
    """File Songipy-prefixed playlists into real Spotify folders (local-only).

    The live path launches the logged-in Playwright profile and drives the web
    player's internal rootlist API; ``--dry-run`` lists the same plan without a
    folder browser (it still authenticates via the Web API to list playlists).
    """
    settings = config.get_settings()
    spotify = _get_spotify(auth.SCOPES_ALL)

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

    if args.dry_run:
        plan = folder_plan.decide_actions(
            targets,
            existing_folders=set(),
            existing_placements={},
            nested=False,
            unrecognized=unrecognized,
        )
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
        return 0

    username = settings.spotify_username
    if not username:
        me = spotify.me()
        username = me.get("id") or ""
    if not username:
        raise RuntimeError("could not determine the Spotify username; set SPOTIFY_USERNAME")

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
        placements = driver.list_placements()

        existing_folders = set(folder_map)
        # Join the Web API name <-> uri list with the driver's uri -> path map;
        # only Songipy playlists are interesting, unknown names can be ignored.
        uri_to_name = {uri: name for name, uri in uri_by_name.items() if uri}
        existing_placements: dict[str, tuple[str, ...]] = {}
        for uri, path in placements.items():
            name = uri_to_name.get(uri)
            if name is None:
                continue
            existing_placements[name] = path or ()

        plan = folder_plan.decide_actions(
            targets,
            existing_folders=existing_folders,
            existing_placements=existing_placements,
            nested=False,
            unrecognized=unrecognized,
        )

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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="compute and print playlists without writing to Spotify",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        help="limit saved tracks (sync-genres) or albums per window (sync-albums)",
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
        sub.set_defaults(func=handler)

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
    raise SystemExit(main())
