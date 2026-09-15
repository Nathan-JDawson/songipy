"""Command-line interface for the Spotify playlist generator."""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime, timedelta

from app import auth, binges, classify, config, import_history, library
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

    cutoff = (datetime.now(UTC) - timedelta(days=config.ALBUM_WINDOW_DAYS)).isoformat()
    recent = binges.filter_since(listens, cutoff)

    for listen in recent:
        listen["album_id"] = listen.get("album_name") or listen.get("track_uri")

    sessions = binges.detect_album_sessions(recent, config.MIN_TRACKS_PER_ALBUM, config.MIN_ALBUMS)
    sessions.reverse()
    if args.top is not None:
        sessions = sessions[: args.top]

    if not sessions:
        print("No binge sessions found.")
        return 0

    album_to_track: dict[str, str] = {}
    album_to_name: dict[str, str] = {}
    for listen in recent:
        key = listen["album_id"]
        album_to_track.setdefault(key, listen["track_uri"])
        album_to_name.setdefault(key, listen.get("album_name") or key)

    if args.dry_run:
        for session in sessions:
            names = ", ".join(album_to_name.get(key, key) for key in session)
            print(f"[dry-run] Binge session ({len(session)} albums): {names}")
        return 0

    spotify = _get_spotify(auth.SCOPES_ALL)

    all_keys = list(dict.fromkeys(key for session in sessions for key in session))
    uris = [album_to_track[key] for key in all_keys if album_to_track.get(key)]
    uri_to_album = library.resolve_album_ids(spotify, uris)
    album_id_cache: dict[str, str] = {
        key: uri_to_album[album_to_track[key]]
        for key in all_keys
        if album_to_track.get(key) in uri_to_album
    }

    for session in sessions:
        track_uris: list[str] = []
        for key in session:
            album_id = album_id_cache.get(key)
            if album_id is None:
                logger.warning("Could not resolve album id for %r; skipping", key)
                continue
            track_uris.extend(library.iter_album_tracks(spotify, album_id))

        if not track_uris:
            logger.warning("Skipping binge session with no resolvable tracks: %r", session)
            continue

        name = config.make_playlist_name("binge", f"{len(session)} albums")
        playlist_id = playlists_module.create_playlist(spotify, name)
        playlists_module.add_tracks(spotify, playlist_id, track_uris)
        print(f"{name} ({len(track_uris)} tracks)")
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
        help="limit saved tracks (sync-genres) or sessions (sync-albums)",
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
        help="limit saved tracks (sync-genres) or sessions (sync-albums)",
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
        ("sync-albums", _cmd_sync_albums, "create playlists per binge session"),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        _add_shared_options(sub)
        sub.set_defaults(func=handler)

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
