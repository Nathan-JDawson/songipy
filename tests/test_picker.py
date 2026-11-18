from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app import db as db_module
from app import picker, picker_logic


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _listen(album_name: str, track_uri: str, played_at: str) -> dict:
    return {"album_name": album_name, "track_uri": track_uri, "played_at": played_at}


# --- group_recent_albums -------------------------------------------------


def test_group_recent_albums_window_filtering() -> None:
    now = datetime.now(UTC)
    listens = [
        _listen("Old", "o1", _iso(now - timedelta(days=40))),
        _listen("Old", "o2", _iso(now - timedelta(days=40))),
        _listen("Old", "o3", _iso(now - timedelta(days=40))),
        _listen("New", "n1", _iso(now - timedelta(days=2))),
        _listen("New", "n2", _iso(now - timedelta(days=2))),
        _listen("New", "n3", _iso(now - timedelta(days=2))),
    ]
    entries = picker_logic.group_recent_albums(
        listens, window_days=30, min_distinct_tracks=3, now=now
    )
    assert [e.key for e in entries] == ["New"]


def test_group_recent_albums_min_distinct_tracks_rule() -> None:
    now = datetime.now(UTC)
    # Album A only 2 distinct tracks -> excluded; B has 3 -> included.
    listens = [
        _listen("A", "a1", _iso(now - timedelta(days=1))),
        _listen("A", "a2", _iso(now - timedelta(days=1))),
        _listen("B", "b1", _iso(now - timedelta(days=1))),
        _listen("B", "b2", _iso(now - timedelta(days=1))),
        _listen("B", "b3", _iso(now - timedelta(days=1))),
    ]
    entries = picker_logic.group_recent_albums(
        listens, window_days=7, min_distinct_tracks=3, now=now
    )
    assert [e.key for e in entries] == ["B"]


def test_group_recent_albums_repeated_same_track_does_not_count() -> None:
    now = datetime.now(UTC)
    # 3 plays but only 1 distinct track -> excluded.
    listens = [
        _listen("A", "a1", _iso(now - timedelta(days=1))),
        _listen("A", "a1", _iso(now - timedelta(days=1, hours=2))),
        _listen("A", "a1", _iso(now - timedelta(days=1, hours=4))),
    ]
    entries = picker_logic.group_recent_albums(
        listens, window_days=7, min_distinct_tracks=3, now=now
    )
    assert entries == []


def test_group_recent_albums_sorts_by_last_played_desc() -> None:
    now = datetime.now(UTC)
    # B played most recently -> first.
    listens = [
        _listen("A", "a1", _iso(now - timedelta(days=3))),
        _listen("A", "a2", _iso(now - timedelta(days=3))),
        _listen("A", "a3", _iso(now - timedelta(days=3))),
        _listen("B", "b1", _iso(now - timedelta(days=1))),
        _listen("B", "b2", _iso(now - timedelta(days=1))),
        _listen("B", "b3", _iso(now - timedelta(days=1))),
    ]
    entries = picker_logic.group_recent_albums(
        listens, window_days=7, min_distinct_tracks=3, now=now
    )
    assert [e.key for e in entries] == ["B", "A"]


def test_group_recent_albums_caps_at_50() -> None:
    now = datetime.now(UTC)
    listens: list[dict] = []
    for i in range(60):
        for j in range(3):
            listens.append(
                _listen(
                    f"Album {i:02d}",
                    f"track-{i}-{j}",
                    _iso(now - timedelta(days=1, hours=i)),
                )
            )
    entries = picker_logic.group_recent_albums(
        listens, window_days=7, min_distinct_tracks=3, now=now
    )
    assert len(entries) == 50


def test_group_recent_albums_track_count_is_distinct() -> None:
    now = datetime.now(UTC)
    listens = [
        _listen("A", "a1", _iso(now - timedelta(days=1))),
        _listen("A", "a1", _iso(now - timedelta(days=1, hours=2))),
        _listen("A", "a2", _iso(now - timedelta(days=1, hours=3))),
        _listen("A", "a3", _iso(now - timedelta(days=1, hours=4))),
    ]
    entries = picker_logic.group_recent_albums(
        listens, window_days=7, min_distinct_tracks=3, now=now
    )
    assert len(entries) == 1
    assert entries[0].track_count == 3


# --- flatten_album_tracks -------------------------------------------------


def _track(uri: str, disc: int, number: int) -> dict:
    return {"uri": uri, "disc_number": disc, "track_number": number}


def test_flatten_album_tracks_preserves_album_order() -> None:
    albums = [
        [{"uri": "a1"}, {"uri": "a2"}],
        [{"uri": "b1"}, {"uri": "b2"}],
    ]
    assert picker_logic.flatten_album_tracks(albums) == ["a1", "a2", "b1", "b2"]


def test_flatten_album_tracks_disc_aware() -> None:
    albums = [[_track("c2", 2, 1), _track("c1", 1, 1), _track("c3", 1, 2), _track("c4", 2, 2)]]
    assert picker_logic.flatten_album_tracks(albums) == ["c1", "c3", "c2", "c4"]


def test_flatten_album_tracks_keeps_uri_strings_in_order() -> None:
    albums = [["u3", "u1", "u2"]]
    assert picker_logic.flatten_album_tracks(albums) == ["u3", "u1", "u2"]


def test_flatten_album_tracks_preserves_cross_album_duplicates() -> None:
    # Same track on two albums appears twice (deluxe vs standard).
    albums = [[{"uri": "shared"}], [{"uri": "shared"}]]
    assert picker_logic.flatten_album_tracks(albums) == ["shared", "shared"]


def test_flatten_album_tracks_missing_metadata_uses_index_order() -> None:
    albums = [[{"uri": "x"}, {"uri": "y"}]]
    assert picker_logic.flatten_album_tracks(albums) == ["x", "y"]


# --- generate route + auth gate (FastAPI TestClient, fake Spotify) --------


class FakeSpotify:
    """Maps each track URI to an album id (``uri_to_album``), plus album tracklists.

    The album metadata returned by ``tracks()`` derives the album id from the
    track URI, so the picker's dedupe-by-album-id and id resolution are exercised
    with realistic ids.
    """

    def __init__(self, album_tracks: dict[str, list[dict]], uri_to_album: dict[str, str]) -> None:
        self._album_tracks = album_tracks
        self.uri_to_album = uri_to_album
        self.calls = {"tracks": [], "album_tracks": [], "created": [], "added": []}

    def me(self) -> dict:
        return {"id": "user-1"}

    def tracks(self, uris: list[str]) -> dict:
        self.calls["tracks"].append(list(uris))
        items = []
        for uri in uris:
            album_id = self.uri_to_album.get(uri, f"album-{uri}")
            # Derive the album name from the id ("album-A" -> "Album A") so it
            # matches the DB's cached album_name in the fixtures.
            name = " ".join(part.title() for part in album_id.split("-"))
            items.append(
                {
                    "uri": uri,
                    "album": {
                        "id": album_id,
                        "name": name,
                        "artists": [{"name": "Artist"}],
                        "images": [{"url": f"http://img/{uri}.png"}],
                        "total_tracks": 3,
                    },
                }
            )
        return {"tracks": items}

    def album_tracks(self, album_id: str, limit: int = 50, offset: int = 0) -> dict:
        self.calls["album_tracks"].append((album_id, limit, offset))
        items = self._album_tracks.get(album_id, [])
        page = items[offset : offset + limit]
        next_url = None
        if offset + len(page) < len(items):
            next_url = "https://api.spotify.com/v1/albums/x/tracks?next"
        return {"items": page, "next": next_url}

    def user_playlist_create(self, user_id: str, name: str, public: bool) -> dict:
        self.calls["created"].append((user_id, name, public))
        return {"id": "pl-1"}

    def playlist_add_items(self, playlist_id: str, uris: list[str]) -> dict:
        self.calls["added"].append((playlist_id, list(uris)))
        return {}


def _seed_db(listens: list[dict]) -> db_module.Database:
    db = db_module.Database("sqlite:///:memory:")
    db_module.create_schema(db)
    db_module.upsert_listens(db, listens)
    return db


def _make_client(
    db: db_module.Database, spotify: FakeSpotify, *, password: str | None = ""
) -> TestClient:
    # An explicit `password=""` disables the picker gate for this app instance
    # regardless of the ambient environment, so API tests are hermetic even when
    # the real `.env` sets PICKER_PASSWORD.
    app = picker.create_app(db=db, spotify_factory=lambda: spotify, password=password)
    return TestClient(app)


def _recent_listens(n: int = 3) -> list[dict]:
    now = datetime.now(UTC)
    return [
        _listen("Album", f"spotify:track:r{i}", _iso(now - timedelta(days=1))) for i in range(n)
    ]


def _two_album_listens() -> list[dict]:
    """Two albums, each with 3 distinct tracks, A played more recently than B."""
    now = datetime.now(UTC)
    listens = [
        _listen("Album A", f"spotify:track:a{i}", _iso(now - timedelta(days=1))) for i in range(3)
    ]
    listens += [
        _listen("Album B", f"spotify:track:b{i}", _iso(now - timedelta(days=2))) for i in range(3)
    ]
    return listens


def test_generate_creates_public_playlist_no_songipy_prefix_exact_order() -> None:
    db = _seed_db(_two_album_listens())
    # A's tracklist is out of album order on disc 2 vs disc 1; B is in order.
    spotify = FakeSpotify(
        {
            "album-A": [
                _track("spotify:track:a1", 2, 1),
                _track("spotify:track:a0", 1, 1),
                _track("spotify:track:a2", 1, 2),
            ],
            "album-B": [
                _track("spotify:track:b0", 1, 1),
                _track("spotify:track:b1", 1, 2),
                _track("spotify:track:b2", 1, 3),
            ],
        },
        uri_to_album={
            "spotify:track:a0": "album-A",
            "spotify:track:a1": "album-A",
            "spotify:track:a2": "album-A",
            "spotify:track:b0": "album-B",
            "spotify:track:b1": "album-B",
            "spotify:track:b2": "album-B",
        },
    )
    client = _make_client(db, spotify)

    rows = client.get("/api/albums?window=7").json()["albums"]
    by_name = {r["name"]: r["album_id"] for r in rows}
    assert by_name["Album A"] == "album-A"
    assert by_name["Album B"] == "album-B"

    # Request B then A -> exact flattened order follows the requested album order.
    resp = client.post(
        "/api/generate",
        json={"title": "My Picks", "album_ids": [by_name["Album B"], by_name["Album A"]]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["playlist_id"] == "pl-1"
    assert data["url"] == "https://open.spotify.com/playlist/pl-1"
    assert data["track_count"] == 6

    created = spotify.calls["created"]
    assert len(created) == 1
    user_id, name, public = created[0]
    assert user_id == "user-1"
    assert name == "My Picks"
    assert public is True
    assert not name.startswith("Songipy/")

    added = spotify.calls["added"]
    assert len(added) == 1
    _, uris = added[0]
    # B first, then A's disc-aware order: disc1 tracks (a0, a2) before disc2 (a1).
    assert uris == [
        "spotify:track:b0",
        "spotify:track:b1",
        "spotify:track:b2",
        "spotify:track:a0",
        "spotify:track:a2",
        "spotify:track:a1",
    ]


def test_generate_batches_tracks_over_100() -> None:
    db = _seed_db(_recent_listens(3))
    spotify = FakeSpotify(
        {"album-A": [_track(f"spotify:track:x{i}", 1, i + 1) for i in range(150)]},
        uri_to_album={"spotify:track:r0": "album-A"},
    )
    client = _make_client(db, spotify)

    resp = client.post("/api/generate", json={"title": "Big", "album_ids": ["album-A"]})
    assert resp.status_code == 200
    assert resp.json()["track_count"] == 150
    assert len(spotify.calls["added"]) == 2


def test_generate_requires_title() -> None:
    db = _seed_db(_recent_listens(3))
    client = _make_client(db, FakeSpotify({}, uri_to_album={}))
    resp = client.post("/api/generate", json={"title": "   ", "album_ids": ["a"]})
    assert resp.status_code == 400


def test_generate_requires_albums() -> None:
    db = _seed_db(_recent_listens(3))
    client = _make_client(db, FakeSpotify({}, uri_to_album={}))
    resp = client.post("/api/generate", json={"title": "Picks", "album_ids": []})
    assert resp.status_code == 400


# --- auth gate -----------------------------------------------------------


def test_auth_gate_blocks_unauth_and_allows_login() -> None:
    # The password is passed explicitly to `create_app`, so this test never
    # depends on the ambient environment (no .env / env var needed or read).
    db = _seed_db(_recent_listens(3))
    spotify = FakeSpotify({}, uri_to_album={})
    app = picker.create_app(db=db, spotify_factory=lambda: spotify, password="secret")
    client = TestClient(app)

    # Unauthenticated API -> 401.
    assert client.get("/api/albums").status_code == 401
    assert client.get("/api/albums/x/tracks").status_code == 401
    assert client.post("/api/generate", json={"title": "x", "album_ids": []}).status_code == 401

    # Root shows the login form when not authed.
    root = client.get("/")
    assert root.status_code == 200
    assert "Password" in root.text

    # Wrong password -> 401.
    assert client.post("/login", data={"password": "wrong"}).status_code == 401

    # Correct password sets a cookie and redirects.
    resp = client.post("/login", data={"password": "secret"}, follow_redirects=False)
    assert resp.status_code == 303
    assert "picker_session" in resp.headers.get("set-cookie", "")

    # With the cookie, API calls pass.
    authed = client.post("/login", data={"password": "secret"}, follow_redirects=False)
    client.cookies.set("picker_session", _cookie_value(authed))
    assert client.get("/api/albums").status_code == 200
    assert client.post("/api/generate", json={"title": "x", "album_ids": ["a"]}).status_code != 401


def test_no_password_gate_when_unset() -> None:
    # A gate-less app instance: explicit empty password, no ambient env needed.
    db = _seed_db(_recent_listens(3))
    spotify = FakeSpotify({}, uri_to_album={})
    client = _make_client(db, spotify, password="")
    # Root serves the page (not the login form) and API is open.
    assert "Password" not in client.get("/").text
    assert client.get("/api/albums").status_code == 200


def test_login_rejected_when_gate_disabled() -> None:
    # With an empty gate password, /login has nothing to authenticate against.
    db = _seed_db(_recent_listens(3))
    spotify = FakeSpotify({}, uri_to_album={})
    client = _make_client(db, spotify, password="")
    assert client.post("/login", data={"password": "anything"}).status_code == 401


def _cookie_value(resp) -> str:
    set_cookie = resp.headers["set-cookie"]
    for part in set_cookie.split(";"):
        if part.strip().startswith("picker_session="):
            return part.strip().split("=", 1)[1]
    raise AssertionError("no picker_session cookie in response")
