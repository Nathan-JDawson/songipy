"""Classify tracks into genres using artist metadata."""

from __future__ import annotations

import logging
from typing import Any

from app import api
from app.config import GENRE_TRACK_SELECTION_CHOICES

logger = logging.getLogger(__name__)

ARTIST_BATCH_SIZE = 50


def normalize_genre(genre: str) -> str:
    return genre.strip().lower()


def build_track_genres(
    tracks: list[dict],
    artists_genres: dict[str, set[str]],
) -> dict[str, list[dict]]:
    """Map each genre to the full track objects whose artists carry that genre.

    A track is included in every genre present among any of its artists. Tracks
    whose artists have no genres are ignored, as are tracks without a URI.
    """
    result: dict[str, list[dict]] = {}
    for track in tracks:
        track_uri = track.get("uri")
        if not track_uri:
            continue
        genres: set[str] = set()
        for artist in track.get("artists") or []:
            for genre in artists_genres.get(artist.get("id"), set()):
                key = normalize_genre(genre)
                if key:
                    genres.add(key)
        for genre in genres:
            result.setdefault(genre, []).append(track)
    return result


def genre_playlist_map(spotify: Any, tracks: list[dict]) -> dict[str, list[dict]]:
    """Look up artist genres (batched) and group the given tracks by genre."""
    artist_ids = sorted(
        {
            artist["id"]
            for track in tracks
            for artist in (track.get("artists") or [])
            if artist.get("id")
        }
    )

    artists_genres: dict[str, set[str]] = {}
    for start in range(0, len(artist_ids), ARTIST_BATCH_SIZE):
        batch = artist_ids[start : start + ARTIST_BATCH_SIZE]
        response = api.call_with_retry(spotify.artists, batch)
        for artist in response.get("artists", []):
            if artist and artist.get("id"):
                artists_genres[artist["id"]] = set(artist.get("genres", []))

    return build_track_genres(tracks, artists_genres)


def keep_min_genres(mapping: dict[str, list[dict]], min_tracks: int) -> dict[str, list[dict]]:
    """Return only the genres with at least ``min_tracks`` tracks."""
    return {genre: tracks for genre, tracks in mapping.items() if len(tracks) >= min_tracks}


def _album_group_key(track: dict) -> tuple[object, ...]:
    """Return the album grouping key for a track.

    Tracks group by album id when present, else album name. Local-file tracks
    and tracks missing both album id and name get a per-track singleton key so
    they are never deduped.
    """
    album = track.get("album") or {}
    album_id = album.get("id")
    album_name = album.get("name")
    if track.get("is_local") or not (album_id or album_name):
        return ("local", track.get("uri"))
    if album_id:
        return ("id", album_id)
    return ("name", album_name)


def _track_number(track: dict) -> int | float:
    """Return the track number for ranking; missing values sort last."""
    value = track.get("track_number")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return float("inf")


def _rank_listened(group: list[dict], listen_stats: dict[str, dict]) -> list[dict]:
    """Rank ``group`` by local listen stats: plays, ms played, track number, uri.

    Every track in ``group`` is guaranteed to have listening history (zero-listen
    tracks are filtered out before grouping), so this is a pure stats ranking.
    """

    def key(track: dict) -> tuple[int, int, int | float, str]:
        stat = listen_stats.get(track.get("uri")) or {}
        play_count = int(stat.get("play_count") or 0)
        ms_played_total = int(stat.get("ms_played_total") or 0)
        return (-play_count, -ms_played_total, _track_number(track), track.get("uri") or "")

    return sorted(group, key=key)


def _rank_popular(group: list[dict]) -> list[dict]:
    """Rank ``group`` by track popularity (missing popularity = -1), then track number."""

    def key(track: dict) -> tuple[int, int | float]:
        popularity = track.get("popularity")
        if not isinstance(popularity, (int, float)) or isinstance(popularity, bool):
            popularity = -1
        return (-int(popularity), _track_number(track))

    return sorted(group, key=key)


def _is_listened(track: dict, listen_stats: dict[str, dict]) -> bool:
    """Return whether ``track`` has any listening history (> 0 plays).

    A track counts as listened only if its uri appears in ``listen_stats`` with a
    ``play_count`` above zero.
    """
    stat = listen_stats.get(track.get("uri"))
    if stat is None:
        return False
    return int(stat.get("play_count") or 0) > 0


def dedupe_album_tracks(
    tracks: list[dict],
    listen_stats: dict[str, dict],
    cap: int,
    mode: str,
) -> list[dict]:
    """Keep at most ``cap`` tracks per album within a genre playlist.

    In ``listened`` and ``popular`` modes every track with no listening history
    (no entry in ``listen_stats``, or a ``play_count`` below 1) is dropped first,
    regardless of album. The remaining tracks are grouped by album (album id,
    else album name, else a per-track singleton for local files and tracks
    without album metadata). Albums with at most ``cap`` listened tracks are kept
    whole; larger albums are trimmed to their top-``cap`` listened tracks
    according to ``mode``:

    - "all": no dedupe; the input list is returned unchanged (zero-listen
      tracks are kept).
    - "listened": rank by local listen stats — play count desc, then ms played
      desc, then track number asc, then uri asc. An album whose tracks are all
      unlistened contributes nothing.
    - "popular": rank by track popularity desc (missing popularity = -1), then
      track number asc, using only the listened tracks (zero-listen tracks are
      already dropped).

    The result preserves the original track order (a stable filter).
    """
    if mode == "all":
        return list(tracks)
    if mode not in GENRE_TRACK_SELECTION_CHOICES:
        raise ValueError(
            f"unknown genre track selection mode {mode!r}; "
            f"expected one of: {', '.join(GENRE_TRACK_SELECTION_CHOICES)}"
        )

    listened = [track for track in tracks if _is_listened(track, listen_stats)]

    groups: dict[tuple[object, ...], list[dict]] = {}
    for track in listened:
        groups.setdefault(_album_group_key(track), []).append(track)

    kept_ids: set[int] = set()
    for group in groups.values():
        if len(group) <= cap:
            kept_ids.update(id(track) for track in group)
            continue
        if mode == "listened":
            ranked = _rank_listened(group, listen_stats)
        else:
            ranked = _rank_popular(group)
        kept_ids.update(id(track) for track in ranked[:cap])

    return [track for track in tracks if id(track) in kept_ids]
