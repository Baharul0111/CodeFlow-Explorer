"""Tiny in-memory sliding-window rate limiter keyed by session token or client IP."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request

from app.api.errors import TooManyRequestsError


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_seconds: float = 60.0) -> None:
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            raise TooManyRequestsError(
                "You are doing that too often. Please wait a minute and try again."
            )
        bucket.append(now)


def client_key(request: Request) -> str:
    token = request.headers.get("X-Session-Token")
    if token:
        return f"tok:{token[:16]}"
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"
