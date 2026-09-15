import re

import pytest

from app import config


def test_make_playlist_name_albums_folder_shape() -> None:
    name = config.make_playlist_name("albums", "Last 7 Days")
    assert name.startswith("Songipy/Albums/")
    assert re.fullmatch(
        r"^Songipy/Albums/Last 7 Days — \d{4}-\d{2}-\d{2} \d{2}:\d{2}$",
        name,
    )


def test_make_playlist_name_genre_folder_shape() -> None:
    name = config.make_playlist_name("genre", "hip hop")
    assert name.startswith("Songipy/Genres/")
    assert re.fullmatch(
        r"^Songipy/Genres/hip hop — \d{4}-\d{2}-\d{2} \d{2}:\d{2}$",
        name,
    )


def test_make_playlist_name_unknown_kind_raises() -> None:
    with pytest.raises(ValueError, match="unknown playlist kind"):
        config.make_playlist_name("bogus", "label")


def test_make_playlist_name_no_root_prefix(monkeypatch) -> None:
    monkeypatch.setattr(config, "PLAYLIST_ROOT", "")
    name = config.make_playlist_name("albums", "Last 7 Days")
    assert name.startswith("Albums/Last 7 Days — ")
    assert not name.startswith("Songipy/")
