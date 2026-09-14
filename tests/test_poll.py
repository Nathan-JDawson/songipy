from app.poll import item_to_row


def test_item_to_row_maps_recently_played_item() -> None:
    item = {
        "played_at": "2026-09-14T12:30:45.000Z",
        "track": {
            "uri": "spotify:track:1",
            "name": "Song",
            "artists": [{"name": "Artist One"}, {"name": "Artist Two"}],
            "album": {"name": "Album"},
        },
        "context": {"uri": "spotify:playlist:abc"},
    }

    row = item_to_row(item)

    assert row == {
        "played_at": "2026-09-14T12:30:45.000Z",
        "track_uri": "spotify:track:1",
        "track_name": "Song",
        "artist_name": "Artist One, Artist Two",
        "album_name": "Album",
        "context_uri": "spotify:playlist:abc",
        "ms_played": None,
        "skipped": None,
    }


def test_item_to_row_without_context() -> None:
    item = {
        "played_at": "2026-09-14T12:30:45.000Z",
        "track": {
            "uri": "spotify:track:2",
            "name": "Another",
            "artists": [],
            "album": {},
        },
    }

    row = item_to_row(item)

    assert row["context_uri"] is None
    assert row["artist_name"] == ""
    assert row["album_name"] is None
