"""Dual sliding-window async rate limiter for Finnhub API."""

from __future__ import annotations

import asyncio
import time
from collections import deque


class RateLimiter:
    """
    Enforce two rate limits simultaneously.

      - minute window: max 55 calls per 60 seconds (safety buffer under 60)
      - burst window:  max 28 calls per 1 second  (safety buffer under 30)
    Both windows must have capacity before a call is allowed through.
    """

    def __init__(
        self,
        max_calls: int = 55,
        period: float = 60.0,
        max_burst: int = 28,
        burst_period: float = 1.0,
    ) -> None:
        self.max_calls = max_calls
        self.period = period
        self.max_burst = max_burst
        self.burst_period = burst_period
        self._calls: deque[float] = deque()  # minute window
        self._burst: deque[float] = deque()  # burst window
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until both the minute and burst windows have capacity."""
        async with self._lock:
            now = time.monotonic()

            # --- Minute window ---
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

            # --- Burst window ---
            while self._burst and now - self._burst[0] >= self.burst_period:
                self._burst.popleft()

            if len(self._burst) >= self.max_burst:
                sleep_for = self.burst_period - (now - self._burst[0])
                await asyncio.sleep(sleep_for)
                now = time.monotonic()
                while self._burst and now - self._burst[0] >= self.burst_period:
                    self._burst.popleft()

            # Claim the slot in both windows atomically
            now = time.monotonic()
            self._calls.append(now)
            self._burst.append(now)
