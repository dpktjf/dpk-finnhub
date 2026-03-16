"""Standalone rate limiter tests — no Home Assistant dependency.

Tests the RateLimiter class and scan interval logic directly.

Run with:
    pytest tests/test_rate_limiter.py -v
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Inline copies of the production classes — no HA imports needed
# ---------------------------------------------------------------------------


class RateLimiter:
    """Sliding-window async rate limiter (copied from rate_limiter.py)."""

    def __init__(self, max_calls: int = 55, period: float = 60.0) -> None:
        self.max_calls = max_calls
        self.period = period
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            while self._calls and now - self._calls[0] >= self.period:
                self._calls.popleft()

            if len(self._calls) >= self.max_calls:
                sleep_for = self.period - (now - self._calls[0])
                await asyncio.sleep(sleep_for)
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= self.period:
                    self._calls.popleft()

            self._calls.append(time.monotonic())


def safe_scan_interval_seconds(symbol_count: int) -> int:
    """Return minimum safe polling interval in seconds (copied from coordinator.py)."""
    minutes_needed = math.ceil(symbol_count / 55)
    return max(1, minutes_needed) * 60


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def run_acquires(limiter: RateLimiter, count: int) -> list[float]:
    """Run `count` acquires and return list of sleep durations triggered."""
    sleep_calls: list[float] = []

    async def mock_sleep(delay: float) -> None:
        sleep_calls.append(delay)
        # Advance the window by evicting timestamps older than (period - delay)
        cutoff = time.monotonic() - (limiter.period - delay)
        while limiter._calls and limiter._calls[0] < cutoff:
            limiter._calls.popleft()

    with patch("asyncio.sleep", side_effect=mock_sleep):
        for _ in range(count):
            await limiter.acquire()
            assert len(limiter._calls) <= limiter.max_calls, (
                f"Deque exceeded {limiter.max_calls} — rate limiter broken"
            )

    return sleep_calls


# ---------------------------------------------------------------------------
# 40 tickers
# ---------------------------------------------------------------------------


class Test40Tickers:
    @pytest.mark.asyncio
    async def test_no_throttling(self):
        """40 calls are under the 55 cap — no sleep should occur."""
        limiter = RateLimiter(max_calls=55, period=60.0)
        sleep_calls = await run_acquires(limiter, 40)

        assert sleep_calls == [], (
            f"Expected no throttling for 40 tickers, got sleeps: {sleep_calls}"
        )

    @pytest.mark.asyncio
    async def test_all_calls_recorded(self):
        """All 40 calls should be in the deque."""
        limiter = RateLimiter(max_calls=55, period=60.0)
        await run_acquires(limiter, 40)

        assert len(limiter._calls) == 40

    def test_scan_interval(self):
        """40 symbols fit in one window — interval should be 60s."""
        assert safe_scan_interval_seconds(40) == 60


# ---------------------------------------------------------------------------
# 60 tickers
# ---------------------------------------------------------------------------


class Test60Tickers:
    @pytest.mark.asyncio
    async def test_throttles_once(self):
        """60 calls against a 55 cap must trigger at least one sleep."""
        limiter = RateLimiter(max_calls=55, period=60.0)
        sleep_calls = await run_acquires(limiter, 60)

        assert len(sleep_calls) >= 1, (
            f"Expected throttling for 60 tickers against 55 cap, got none"
        )

    @pytest.mark.asyncio
    async def test_sleep_duration_is_valid(self):
        """Sleep duration must be positive and no greater than the full window."""
        limiter = RateLimiter(max_calls=55, period=60.0)
        sleep_calls = await run_acquires(limiter, 60)

        for d in sleep_calls:
            assert 0 < d <= 60.0, f"Invalid sleep duration: {d}"

    @pytest.mark.asyncio
    async def test_deque_never_exceeds_cap(self):
        """Invariant: deque never holds more than 55 entries at any point."""
        limiter = RateLimiter(max_calls=55, period=60.0)
        await run_acquires(limiter, 60)

    def test_scan_interval(self):
        """60 symbols need 2 windows — interval should be 120s."""
        assert safe_scan_interval_seconds(60) == 120


# ---------------------------------------------------------------------------
# 80 tickers
# ---------------------------------------------------------------------------


class Test80Tickers:
    @pytest.mark.asyncio
    async def test_throttles_once(self):
        """80 calls: first 55 pass freely, one sleep clears the window,
        remaining 25 fit in the fresh window — exactly 1 sleep expected."""
        limiter = RateLimiter(max_calls=55, period=60.0)
        sleep_calls = await run_acquires(limiter, 80)

        assert len(sleep_calls) == 1, (
            f"Expected exactly 1 throttle sleep for 80 tickers (55+25), got {len(sleep_calls)}"
        )

    @pytest.mark.asyncio
    async def test_all_80_calls_complete(self):
        """All 80 calls must complete — limiter must not deadlock or drop calls."""
        limiter = RateLimiter(max_calls=55, period=60.0)
        completed = 0

        async def mock_sleep(delay: float) -> None:
            cutoff = time.monotonic() - (limiter.period - delay)
            while limiter._calls and limiter._calls[0] < cutoff:
                limiter._calls.popleft()

        with patch("asyncio.sleep", side_effect=mock_sleep):
            for _ in range(80):
                await limiter.acquire()
                completed += 1

        assert completed == 80, f"Only {completed}/80 calls completed"

    @pytest.mark.asyncio
    async def test_deque_never_exceeds_cap(self):
        """Invariant holds at 80 tickers too."""
        limiter = RateLimiter(max_calls=55, period=60.0)
        await run_acquires(limiter, 80)

    def test_scan_interval(self):
        """80 symbols still fit in 2 windows (55+25) — interval should be 120s."""
        assert safe_scan_interval_seconds(80) == 120


# ---------------------------------------------------------------------------
# Boundary / edge cases
# ---------------------------------------------------------------------------


class TestBoundaries:
    def test_exactly_55_tickers_is_one_minute(self):
        assert safe_scan_interval_seconds(55) == 60

    def test_56_tickers_is_two_minutes(self):
        assert safe_scan_interval_seconds(56) == 120

    def test_110_tickers_is_two_minutes(self):
        assert safe_scan_interval_seconds(110) == 120

    def test_111_tickers_is_three_minutes(self):
        assert safe_scan_interval_seconds(111) == 180

    @pytest.mark.asyncio
    async def test_exactly_at_cap_no_throttle(self):
        """55 calls against a 55 cap — the last call should just fit, no sleep."""
        limiter = RateLimiter(max_calls=55, period=60.0)
        sleep_calls = await run_acquires(limiter, 55)
        assert sleep_calls == []

    @pytest.mark.asyncio
    async def test_one_over_cap_throttles(self):
        """56 calls must trigger exactly one sleep."""
        limiter = RateLimiter(max_calls=55, period=60.0)
        sleep_calls = await run_acquires(limiter, 56)
        assert len(sleep_calls) == 1
