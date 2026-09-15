from app.library import resolve_album_ids


class FakeSpotify:
    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def tracks(self, batch: list[str]) -> dict:
        self.batches.append(list(batch))
        return {"tracks": [{"uri": uri, "album": {"id": f"album-{uri}"}} for uri in batch]}


class PartialSpotify:
    def tracks(self, batch: list[str]) -> dict:
        return {
            "tracks": [
                None,
                {"uri": None, "album": {"id": "a"}},
                {"uri": "u", "album": {}},
                {"uri": "v", "album": {"id": "album-v"}},
            ]
        }


def test_resolve_album_ids_maps_uris_to_album_ids() -> None:
    spotify = FakeSpotify()
    uris = [f"spotify:track:{i}" for i in range(3)]

    result = resolve_album_ids(spotify, uris)

    assert result == {uri: f"album-{uri}" for uri in uris}
    assert spotify.batches == [uris]


def test_resolve_album_ids_splits_into_chunks_of_50() -> None:
    spotify = FakeSpotify()
    uris = [f"spotify:track:{i}" for i in range(120)]

    result = resolve_album_ids(spotify, uris)

    assert [len(batch) for batch in spotify.batches] == [50, 50, 20]
    assert len(result) == 120


def test_resolve_album_ids_skips_incomplete_tracks() -> None:
    assert resolve_album_ids(PartialSpotify(), ["x"]) == {"v": "album-v"}


def test_resolve_album_ids_empty_input() -> None:
    spotify = FakeSpotify()
    assert resolve_album_ids(spotify, []) == {}
    assert spotify.batches == []
