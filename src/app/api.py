"""Retry helper for Spotify API calls that hit rate limits."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable

import spotipy

from app import config

logger = logging.getLogger(__name__)


def _retry_after_seconds(exc: spotipy.SpotifyException, attempt: int) -> float:
    """Return the retry delay for ``exc``; fall back to exponential backoff."""
    headers = exc.headers or {}
    value = headers.get("Retry-After")
    if value is not None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = None
        if parsed is not None and math.isfinite(parsed) and parsed >= 0:
            return min(parsed, config.RATE_LIMIT_MAX_BACKOFF)
    return min(float(2**attempt), config.RATE_LIMIT_MAX_BACKOFF)


def call_with_retry[T](
    fn: Callable[..., T],
    *args: object,
    max_retries: int = config.MAX_RATE_LIMIT_RETRIES,
    **kwargs: object,
) -> T:
    """Call ``fn`` retrying only on Spotify 429 (rate limit) responses.

    The wait between attempts honours ``Retry-After`` when present and
    parseable, otherwise it uses exponential backoff. Delays are capped at
    ``config.RATE_LIMIT_MAX_BACKOFF`` seconds. After ``max_retries`` retries the
    original exception is re-raised.
    """
    attempt = 0
    while True:
        try:
            return fn(*args, **kwargs)
        except spotipy.SpotifyException as exc:
            if exc.http_status != 429 or attempt >= max_retries:
                raise
            delay = min(_retry_after_seconds(exc, attempt), config.RATE_LIMIT_MAX_BACKOFF)
            logger.warning(
                "Spotify rate limit (429) on attempt %d/%d; sleeping %.2fs",
                attempt + 1,
                max_retries,
                delay,
            )
            time.sleep(delay)
            attempt += 1
