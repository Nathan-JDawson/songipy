import re
from datetime import UTC, datetime, timedelta

import app.__main__ as main_module


def _no_spotify(*args, **kwargs):
    raise AssertionError("dry-run must not create a Spotify client")


def _inject(monkeypatch, listens: list[dict]) -> None:
    monkeypatch.setattr(main_module, "_open_db", lambda **kwargs: object())
    monkeypatch.setattr(main_module.db_module, "all_listens_ordered", lambda db: listens)
    monkeypatch.setattr(main_module, "_get_spotify", _no_spotify)


def _listen(album_name: str, track_uri: str, played_at: str) -> dict:
    return {"album_name": album_name, "track_uri": track_uri, "played_at": played_at}


def _line(label: str, n_albums: int, names: str) -> str:
    plural = "" if n_albums == 1 else "s"
    head = rf"\[dry-run\] Songipy/Albums/{re.escape(label)} .* \({n_albums} album{plural}\)"
    return rf"{head}: {re.escape(names)}"


def test_sync_albums_dry_run_makes_no_spotify_calls(monkeypatch, capsys) -> None:
    now = datetime.now(UTC)
    listens = [
        _listen("A", "a1", (now - timedelta(days=1)).isoformat()),
        _listen("A", "a2", (now - timedelta(days=1)).isoformat()),
        _listen("A", "a3", (now - timedelta(days=1)).isoformat()),
    ]
    _inject(monkeypatch, listens)

    exit_code = main_module.main(["sync-albums", "--dry-run"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert re.search(_line("Last 7 Days", 1, "A"), out)
    assert re.search(_line("Last 30 Days", 1, "A"), out)
    assert re.search(_line("Last 90 Days", 1, "A"), out)


def test_sync_albums_dry_run_no_albums(monkeypatch, capsys) -> None:
    now = datetime.now(UTC)
    listens = [_listen("A", "a1", (now - timedelta(days=1)).isoformat())]
    _inject(monkeypatch, listens)

    exit_code = main_module.main(["sync-albums", "--dry-run"])

    assert exit_code == 0
    assert "No albums found in any window." in capsys.readouterr().out


def test_sync_albums_dry_run_top_limits_albums(monkeypatch, capsys) -> None:
    now = datetime.now(UTC)
    listens = [
        _listen("A", "a1", (now - timedelta(days=1)).isoformat()),
        _listen("A", "a2", (now - timedelta(days=1)).isoformat()),
        _listen("A", "a3", (now - timedelta(days=1)).isoformat()),
        _listen("B", "b1", (now - timedelta(days=2)).isoformat()),
        _listen("B", "b2", (now - timedelta(days=2)).isoformat()),
        _listen("B", "b3", (now - timedelta(days=2)).isoformat()),
    ]
    _inject(monkeypatch, listens)

    exit_code = main_module.main(["sync-albums", "--dry-run", "--top", "1"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert re.search(_line("Last 7 Days", 1, "A"), out)
    assert not re.search(r"\(2 albums\)", out)
