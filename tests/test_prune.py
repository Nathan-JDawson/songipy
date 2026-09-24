import app.__main__ as main_module
from app import config


class _FakeSpotify:
    def __init__(self, user_id: str = "me") -> None:
        self._user_id = user_id
        self.unfollowed: list[str] = []

    def me(self) -> dict:
        return {"id": self._user_id}

    def current_user_unfollow_playlist(self, playlist_id: str) -> None:
        self.unfollowed.append(playlist_id)


def _playlist(name: str, playlist_id: str, owner: str = "me") -> dict:
    return {"name": name, "id": playlist_id, "owner": {"id": owner}}


def _inject(monkeypatch, spotify, playlists: list[dict]) -> None:
    monkeypatch.setattr(main_module, "_get_spotify", lambda scopes: spotify)
    monkeypatch.setattr(main_module, "_iter_user_playlists", lambda s: playlists)


def test_prune_dry_run_lists_only_owned_songipy_playlists(monkeypatch, capsys) -> None:
    playlists = [
        _playlist("Songipy/Genres/rock — 2026-01-01 00:00", "p1"),
        _playlist("My Mix", "p2"),
        _playlist("Songipy/Genres/pop — 2026-01-01 00:00", "p3", owner="other"),
    ]
    _inject(monkeypatch, _FakeSpotify(), playlists)

    exit_code = main_module.main(["prune", "--dry-run"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "[dry-run] would delete 1 playlist(s)" in out
    assert "Songipy/Genres/rock — 2026-01-01 00:00" in out
    assert "My Mix" not in out
    assert "Songipy/Genres/pop" not in out


def test_prune_live_requires_yes(monkeypatch, capsys) -> None:
    spotify = _FakeSpotify()
    playlists = [_playlist("Songipy/Genres/rock — 2026-01-01 00:00", "p1")]
    _inject(monkeypatch, spotify, playlists)

    exit_code = main_module.main(["prune"])

    assert exit_code != 0
    assert spotify.unfollowed == []
    captured = capsys.readouterr()
    assert "permanent" in captured.out + captured.err


def test_prune_live_deletes_with_yes(monkeypatch, capsys) -> None:
    spotify = _FakeSpotify()
    playlists = [
        _playlist("Songipy/Genres/rock — 2026-01-01 00:00", "p1"),
        _playlist("Songipy/Albums/Last 7 Days — 2026-01-01 00:00", "p2"),
        _playlist("Not Mine", "p3", owner="other"),
    ]
    _inject(monkeypatch, spotify, playlists)

    exit_code = main_module.main(["prune", "--yes"])

    assert exit_code == 0
    assert spotify.unfollowed == ["p1", "p2"]
    assert "deleted 2 playlist(s)" in capsys.readouterr().out


def test_prune_dry_run_matches_subfolder_prefixes_when_root_empty(monkeypatch, capsys) -> None:
    playlists = [
        _playlist("Albums/Last 7 Days — 2026-01-01 00:00", "p1"),
        _playlist("Genres/rock — 2026-01-01 00:00", "p2"),
        _playlist("Other/thing", "p3"),
    ]
    _inject(monkeypatch, _FakeSpotify(), playlists)
    monkeypatch.setattr(config, "PLAYLIST_ROOT", "")

    exit_code = main_module.main(["prune", "--dry-run"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "[dry-run] would delete 2 playlist(s)" in out
    assert "Albums/Last 7 Days" in out
    assert "Genres/rock" in out
    assert "Other/thing" not in out
