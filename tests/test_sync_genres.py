import re

import pytest

import app.__main__ as main_module
from app import classify, config


def _track(uri: str, album_id: str, track_number: int, name: str = "") -> dict:
    return {
        "uri": uri,
        "album": {"id": album_id, "name": name},
        "track_number": track_number,
        "name": name,
    }


def _genres(monkeypatch, tracks: list[dict]) -> None:
    monkeypatch.setattr(main_module, "_get_spotify", lambda scopes: object())
    monkeypatch.setattr(main_module, "_saved_tracks", lambda spotify, limit: tracks)
    monkeypatch.setattr(classify, "genre_playlist_map", lambda spotify, tracks: {"rock": tracks})


def test_sync_genres_dry_run_all_does_not_open_db(monkeypatch, capsys) -> None:
    def _no_db(**kwargs):
        raise AssertionError("--tracks all must not open the DB")

    tracks = [_track(f"t{i}", f"a{i % 2}", i) for i in range(1, 61)]
    monkeypatch.setattr(main_module, "_open_db", _no_db)
    _genres(monkeypatch, tracks)

    exit_code = main_module.main(["sync-genres", "--dry-run", "--tracks", "all"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert re.search(
        r"\[dry-run\] Songipy/Genres/rock — \d{4}-\d{2}-\d{2} \d{2}:\d{2} \(60 tracks\)", out
    )


def test_sync_genres_dry_run_default_listened_dedupes(monkeypatch, capsys) -> None:
    monkeypatch.delenv("GENRE_TRACK_SELECTION", raising=False)
    tracks = [_track(f"t{i}", "album1", i, name=f"T{i}") for i in range(1, 56)]
    stats = {
        f"t{i}": {"play_count": 56 - i, "ms_played_total": 1000 * (56 - i)} for i in range(1, 56)
    }
    opened: list[object] = []

    def fake_open_db(**kwargs):
        opened.append(kwargs)
        return object()

    monkeypatch.setattr(main_module, "_open_db", fake_open_db)
    monkeypatch.setattr(main_module.db_module, "listen_stats_by_uri", lambda db: stats)
    _genres(monkeypatch, tracks)
    monkeypatch.setattr(config, "MIN_PLAYLIST_TRACKS", 5)

    exit_code = main_module.main(["sync-genres", "--dry-run"])

    assert exit_code == 0
    assert opened  # default mode is "listened", so the DB must be opened
    out = capsys.readouterr().out
    assert re.search(
        r"\[dry-run\] Songipy/Genres/rock — \d{4}-\d{2}-\d{2} \d{2}:\d{2} \(5 tracks\)", out
    )


def test_sync_genres_invalid_tracks_choice_exits(monkeypatch) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main_module.main(["sync-genres", "--dry-run", "--tracks", "bogus"])
    assert excinfo.value.code == 2


def test_sync_genres_no_genres(monkeypatch, capsys) -> None:
    monkeypatch.setattr(main_module, "_open_db", lambda **kwargs: object())
    monkeypatch.setattr(main_module.db_module, "listen_stats_by_uri", lambda db: {})
    _genres(monkeypatch, [])

    exit_code = main_module.main(["sync-genres", "--dry-run", "--tracks", "listened"])

    assert exit_code == 0
    assert "No genres found for the saved tracks." in capsys.readouterr().out
