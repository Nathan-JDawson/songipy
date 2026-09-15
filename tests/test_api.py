import pytest
import spotipy

from app import api


def _rate_limit_error(retry_after: str | None = "0.01") -> spotipy.SpotifyException:
    headers = {"Retry-After": retry_after} if retry_after is not None else None
    return spotipy.SpotifyException(429, -1, "rate limited", reason="rate limited", headers=headers)


def test_call_with_retry_retries_then_succeeds() -> None:
    calls = {"count": 0}

    def fn() -> str:
        calls["count"] += 1
        if calls["count"] <= 2:
            raise _rate_limit_error()
        return "ok"

    assert api.call_with_retry(fn, max_retries=5) == "ok"
    assert calls["count"] == 3


def test_call_with_retry_passes_arguments() -> None:
    def fn(a: int, *, b: int) -> int:
        return a + b

    assert api.call_with_retry(fn, 1, b=2) == 3


def test_call_with_retry_reraises_after_max_retries() -> None:
    calls = {"count": 0}

    def fn() -> str:
        calls["count"] += 1
        raise _rate_limit_error()

    with pytest.raises(spotipy.SpotifyException):
        api.call_with_retry(fn, max_retries=2)
    assert calls["count"] == 3


def test_call_with_retry_does_not_retry_other_statuses() -> None:
    calls = {"count": 0}

    def fn() -> str:
        calls["count"] += 1
        raise spotipy.SpotifyException(500, -1, "server error")

    with pytest.raises(spotipy.SpotifyException):
        api.call_with_retry(fn, max_retries=5)
    assert calls["count"] == 1


def test_call_with_retry_falls_back_to_exponential_backoff(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(api.time, "sleep", sleeps.append)

    def fn() -> str:
        raise _rate_limit_error(retry_after=None)

    with pytest.raises(spotipy.SpotifyException):
        api.call_with_retry(fn, max_retries=2)
    assert sleeps == [1.0, 2.0]


def test_call_with_retry_caps_backoff(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(api.time, "sleep", sleeps.append)

    def fn() -> str:
        raise _rate_limit_error(retry_after="9999")

    with pytest.raises(spotipy.SpotifyException):
        api.call_with_retry(fn, max_retries=1)
    assert sleeps == [60]


def test_call_with_retry_falls_back_on_negative_retry_after(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(api.time, "sleep", sleeps.append)
    calls = {"count": 0}

    def fn() -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise _rate_limit_error(retry_after="-1")
        return "ok"

    assert api.call_with_retry(fn, max_retries=5) == "ok"
    assert calls["count"] == 2
    assert sleeps == [1.0]


def test_call_with_retry_falls_back_on_nan_retry_after(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(api.time, "sleep", sleeps.append)
    calls = {"count": 0}

    def fn() -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise _rate_limit_error(retry_after="NaN")
        return "ok"

    assert api.call_with_retry(fn, max_retries=5) == "ok"
    assert calls["count"] == 2
    assert sleeps == [1.0]
