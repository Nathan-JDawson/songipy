"""Classify tracks into genres using artist metadata."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

ARTIST_BATCH_SIZE = 50


def normalize_genre(genre: str) -> str:
    return genre.strip().lower()


def build_track_genres(
    tracks: list[dict],
    artists_genres: dict[str, set[str]],
) -> dict[str, list[str]]:
    """Map each genre to the tracks whose artists carry that genre.

    A track is included in every genre present among any of its artists. Tracks
    whose artists have no genres are ignored.
    """
    result: dict[str, list[str]] = {}
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
            result.setdefault(genre, []).append(track_uri)
    return result


def genre_playlist_map(spotify: Any, tracks: list[dict]) -> dict[str, list[str]]:
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
        response = spotify.artists(batch)
        for artist in response.get("artists", []):
            if artist and artist.get("id"):
                artists_genres[artist["id"]] = set(artist.get("genres", []))

    return build_track_genres(tracks, artists_genres)
