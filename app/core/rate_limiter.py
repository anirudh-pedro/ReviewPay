"""In-memory sliding-window rate limiter for production and API protection.

Performs thread-safe, memory-bounded window tracking without requiring external
infrastructure such as Redis or Memcached.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock
from typing import Mapping
from app.core.errors import RevivePayError


class RateLimitExceeded(RevivePayError):
    """Client has exceeded the allowed request rate."""

    code = "RATE_LIMIT_EXCEEDED"
    http_status = 429

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Too many requests. Please try again in {retry_after} second(s).")
        self.headers = {"Retry-After": str(retry_after)}


class SlidingWindowRateLimiter:
    """Sliding window rate limiter by client IP or subject."""

    def __init__(self, requests_per_minute: int = 120, window_seconds: int = 60) -> None:
        self.requests_per_minute = requests_per_minute
        self.window_seconds = window_seconds
        self._history: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def check(self, key: str) -> None:
        """Check if request is permitted under rate limit key, or raise RateLimitExceeded."""
        if self.requests_per_minute <= 0:
            return

        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            timestamps = [ts for ts in self._history[key] if ts > cutoff]
            if len(timestamps) >= self.requests_per_minute:
                oldest = timestamps[0]
                retry_after = max(1, int(self.window_seconds - (now - oldest)))
                raise RateLimitExceeded(retry_after=retry_after)

            timestamps.append(now)
            self._history[key] = timestamps

            # Periodic cleanup of stagnant keys
            if len(self._history) > 1000:
                expired_keys = [
                    k for k, v in self._history.items() if not v or v[-1] <= cutoff
                ]
                for k in expired_keys:
                    del self._history[k]


def extract_client_ip(headers: Mapping[str, str], default_host: str = "127.0.0.1") -> str:
    """Extract client IP from headers dictionary without framework dependencies."""
    forwarded = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return default_host


__all__ = ["RateLimitExceeded", "SlidingWindowRateLimiter", "extract_client_ip"]
