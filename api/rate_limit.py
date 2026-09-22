"""A minimal in-process fixed-window rate limiter for the public API.

Faro runs as a single local instance, so a process-local counter is enough
-- no Redis, no extra dependency. The limiter is intentionally coarse: one
window per client key, reset every ``window_seconds``.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int  # seconds until the window resets (0 when allowed)


class FixedWindowRateLimiter:
    def __init__(self, requests_per_window: int, window_seconds: int = 60) -> None:
        self._limit = requests_per_window
        self._window = window_seconds
        self._lock = threading.Lock()
        # client_key -> (window_start_epoch, count)
        self._buckets: dict[str, tuple[float, int]] = {}

    def check(self, client_key: str, *, now: float | None = None) -> RateLimitDecision:
        now = time.monotonic() if now is None else now
        with self._lock:
            window_start, count = self._buckets.get(client_key, (now, 0))
            if now - window_start >= self._window:
                window_start, count = now, 0

            if count >= self._limit:
                retry_after = max(1, int(self._window - (now - window_start)))
                return RateLimitDecision(allowed=False, retry_after=retry_after)

            self._buckets[client_key] = (window_start, count + 1)

            # Opportunistic prune so an idle key set does not grow forever.
            if len(self._buckets) > 4096:
                cutoff = now - self._window
                self._buckets = {
                    key: value for key, value in self._buckets.items() if value[0] >= cutoff
                }

            return RateLimitDecision(allowed=True, retry_after=0)


def client_key_for(*, forwarded_for: str | None, client_host: str | None) -> str:
    """Best-effort client identity. Trusts the first `X-Forwarded-For` hop
    when present (the app is meant to sit behind a local reverse proxy or
    nothing at all); otherwise the socket peer."""
    if forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first
    return client_host or "unknown"
