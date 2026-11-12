"""A per-account sliding window for the routes that cost money or rows.

`/v1/speak` spends voice-provider credits and `/v1/telemetry` inserts a row per call,
so one signed-in client in a loop could run up a bill or fill a table. The app runs
as one process, so the window lives in memory: a restart forgets it, which only ever
lets someone through early, never locks anyone out.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable

from app.common.api_error import ApiError


class RateLimiter:
    WINDOW_SECONDS = 60.0

    def __init__(self, per_minute: int, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.per_minute = per_minute
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, account_id: str) -> None:
        """Count one call, or refuse it with `rate_limited` and the seconds to wait."""
        now = self.clock()
        with self._lock:
            hits = self._hits.setdefault(account_id, deque())
            while hits and now - hits[0] >= self.WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= self.per_minute:
                wait = int(self.WINDOW_SECONDS - (now - hits[0])) + 1
                raise ApiError(429, "rate_limited", "Too many requests. Try again shortly.",
                               {"retry_after_seconds": wait})
            hits.append(now)
