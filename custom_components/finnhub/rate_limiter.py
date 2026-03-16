"""Sliding-window async rate limiter for Finnhub API."""
from __future__ import annotations

import asyncio
import time
from collections import deque


class RateLimiter:
    """Enforce a maximum number of calls within a rolling time window."""

    def __init__(self, max_calls: int = 55, period: float = 60.0) -> None:
        self.max_calls = max_calls
        self.period = period
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until a call slot is available, then claim it."""
        async with self._lock:
            now = time.monotonic()

            # Remove timestamps that have fallen outside the window
            while self._calls and now - self._calls[0] >= self.period:
                self._calls.popleft()

            if len(self._calls) >= self.max_calls:
                # Wait until the oldest call exits the window
                sleep_for = self.period - (now - self._calls[0])
                await asyncio.sleep(sleep_for)

                # Re-prune after sleeping
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= self.period:
                    self._calls.popleft()

            self._calls.append(time.monotonic())
