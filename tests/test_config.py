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


def test_env_int_default_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("TEST_INT", raising=False)
    assert config._env_int("TEST_INT", 7) == 7


def test_env_int_parses_value(monkeypatch) -> None:
    monkeypatch.setenv("TEST_INT", "12")
    assert config._env_int("TEST_INT", 7) == 12


def test_env_int_invalid_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("TEST_INT", "not-a-number")
    assert config._env_int("TEST_INT", 7) == 7


def test_env_choice_default_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("TEST_CHOICE", raising=False)
    assert config._env_choice("TEST_CHOICE", "b", ("a", "b", "c")) == "b"


def test_env_choice_normalizes_and_validates(monkeypatch) -> None:
    monkeypatch.setenv("TEST_CHOICE", "  A ")
    assert config._env_choice("TEST_CHOICE", "b", ("a", "b", "c")) == "a"


def test_env_choice_invalid_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("TEST_CHOICE", "zzz")
    assert config._env_choice("TEST_CHOICE", "b", ("a", "b", "c")) == "b"


def test_genre_track_selection_default(monkeypatch) -> None:
    monkeypatch.delenv("GENRE_TRACK_SELECTION", raising=False)
    assert config.genre_track_selection() == "listened"


def test_genre_track_selection_env_override(monkeypatch) -> None:
    monkeypatch.setenv("GENRE_TRACK_SELECTION", "popular")
    assert config.genre_track_selection() == "popular"


def test_genre_track_selection_invalid_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("GENRE_TRACK_SELECTION", "bogus")
    assert config.genre_track_selection() == "listened"


def test_genre_max_tracks_per_album_default(monkeypatch) -> None:
    monkeypatch.delenv("GENRE_MAX_TRACKS_PER_ALBUM", raising=False)
    assert config.genre_max_tracks_per_album() == 5


def test_genre_max_tracks_per_album_env_override(monkeypatch) -> None:
    monkeypatch.setenv("GENRE_MAX_TRACKS_PER_ALBUM", "3")
    assert config.genre_max_tracks_per_album() == 3


def test_genre_max_tracks_per_album_invalid_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("GENRE_MAX_TRACKS_PER_ALBUM", "many")
    assert config.genre_max_tracks_per_album() == 5


def test_genre_max_tracks_per_album_clamps_to_one(monkeypatch) -> None:
    monkeypatch.setenv("GENRE_MAX_TRACKS_PER_ALBUM", "0")
    assert config.genre_max_tracks_per_album() == 1
    monkeypatch.setenv("GENRE_MAX_TRACKS_PER_ALBUM", "-3")
    assert config.genre_max_tracks_per_album() == 1
