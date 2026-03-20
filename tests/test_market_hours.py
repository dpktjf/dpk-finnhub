"""
Market hours tests — imports directly from the integration.

All tests go through coordinator._is_market_open() which is the actual
production path. The local time fallback is exercised by returning None
from _fetch_market_status.

Run with:
    pytest tests/test_market_hours.py -v
"""
# ruff: noqa: BLE001, PLR2004, PLR0912

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from custom_components.finnhub.const import MARKET_TIMEZONE
from custom_components.finnhub.coordinator import FinnhubCoordinator, next_market_open

_TZ = ZoneInfo(MARKET_TIMEZONE)
_UTC = ZoneInfo("UTC")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def et(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Construct a timezone-aware datetime in America/New_York."""
    return datetime(year, month, day, hour, minute, tzinfo=_TZ)


def utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=_UTC)


def freeze(fake_now: datetime):
    """Patch dt_util.now() to return a fixed datetime."""
    return patch(
        "custom_components.finnhub.coordinator.dt_util.now",
        return_value=fake_now,
    )


def no_api() -> AsyncMock:
    """Return an AsyncMock that simulates _fetch_market_status failing.
    Forces _is_market_open() to use the local time/weekday fallback.
    """
    return AsyncMock(return_value=None)


def make_coordinator() -> FinnhubCoordinator:
    """
    Build a FinnhubCoordinator bypassing DataUpdateCoordinator.__init__
    so no HA frame helper or event loop is required.
    """
    coordinator = FinnhubCoordinator.__new__(FinnhubCoordinator)
    # Manually set everything __init__ would have set
    coordinator.api_key = "test_key"
    coordinator.symbols = ["SPY"]
    coordinator._market_status = None
    coordinator._market_status_fetched_at = 0.0
    coordinator._unsub_market_open = None
    coordinator._client = None
    coordinator.data = {}  # type: ignore[assignment]
    coordinator.hass = MagicMock()
    coordinator.logger = MagicMock()
    coordinator.update_interval = None
    coordinator._listeners = {}
    coordinator.last_update_success = True
    return coordinator


async def local_is_open(fake_now: datetime) -> bool:
    """Run _is_market_open() with API disabled and time frozen.
    Exercises the local calendar/time fallback path.
    """
    coordinator = make_coordinator()
    with patch.object(coordinator, "_fetch_market_status", no_api()):
        with freeze(fake_now):
            return await coordinator._is_market_open()


async def api_is_open(fake_now: datetime, status: dict) -> bool:
    """Run _is_market_open() with a fixed API response and time frozen."""
    coordinator = make_coordinator()
    with patch.object(
        coordinator,
        "_fetch_market_status",
        new=AsyncMock(return_value=status),
    ):
        with freeze(fake_now):
            return await coordinator._is_market_open()


# ---------------------------------------------------------------------------
# Core open/close boundary tests — local fallback path
# ---------------------------------------------------------------------------


class TestMarketOpenBoundaries:
    @pytest.mark.asyncio
    async def test_exactly_at_open_is_open(self) -> None:
        assert await local_is_open(et(2026, 3, 16, 9, 30)) is True

    @pytest.mark.asyncio
    async def test_one_minute_before_open_is_closed(self):
        assert await local_is_open(et(2026, 3, 16, 9, 29)) is False

    @pytest.mark.asyncio
    async def test_midday_is_open(self):
        assert await local_is_open(et(2026, 3, 16, 12, 0)) is True

    @pytest.mark.asyncio
    async def test_exactly_at_close_is_open(self):
        """16:00:00 is still within the session."""
        assert await local_is_open(et(2026, 3, 16, 16, 0)) is True

    @pytest.mark.asyncio
    async def test_one_minute_after_close_is_closed(self):
        assert await local_is_open(et(2026, 3, 16, 16, 1)) is False

    @pytest.mark.asyncio
    async def test_midnight_is_closed(self):
        assert await local_is_open(et(2026, 3, 16, 0, 0)) is False

    @pytest.mark.asyncio
    async def test_pre_market_is_closed(self):
        assert await local_is_open(et(2026, 3, 16, 8, 0)) is False

    @pytest.mark.asyncio
    async def test_post_market_is_closed(self):
        assert await local_is_open(et(2026, 3, 16, 17, 0)) is False


# ---------------------------------------------------------------------------
# Weekday tests — local fallback path
# ---------------------------------------------------------------------------


class TestWeekdays:
    """2026-03-16 is a Monday."""

    @pytest.mark.asyncio
    async def test_monday_is_open(self):
        assert await local_is_open(et(2026, 3, 16, 10, 0)) is True

    @pytest.mark.asyncio
    async def test_tuesday_is_open(self):
        assert await local_is_open(et(2026, 3, 17, 10, 0)) is True

    @pytest.mark.asyncio
    async def test_wednesday_is_open(self):
        assert await local_is_open(et(2026, 3, 18, 10, 0)) is True

    @pytest.mark.asyncio
    async def test_thursday_is_open(self):
        assert await local_is_open(et(2026, 3, 19, 10, 0)) is True

    @pytest.mark.asyncio
    async def test_friday_is_open(self):
        assert await local_is_open(et(2026, 3, 20, 10, 0)) is True

    @pytest.mark.asyncio
    async def test_saturday_is_closed(self):
        assert await local_is_open(et(2026, 3, 21, 10, 0)) is False

    @pytest.mark.asyncio
    async def test_sunday_is_closed(self):
        assert await local_is_open(et(2026, 3, 22, 10, 0)) is False

    @pytest.mark.asyncio
    async def test_saturday_during_session_hours_is_closed(self):
        """Even if time falls in 09:30-16:00, weekend must be closed."""
        assert await local_is_open(et(2026, 3, 21, 12, 0)) is False


# ---------------------------------------------------------------------------
# DST transition tests — local fallback path
# ---------------------------------------------------------------------------


class TestDSTTransitions:
    """US DST: spring forward 2nd Sunday March, fall back 1st Sunday November."""

    @pytest.mark.asyncio
    async def test_saturday_before_spring_forward_is_closed(self):
        assert await local_is_open(et(2026, 3, 7, 12, 0)) is False

    @pytest.mark.asyncio
    async def test_monday_after_spring_forward_open(self):
        assert await local_is_open(et(2026, 3, 9, 10, 0)) is True

    @pytest.mark.asyncio
    async def test_monday_after_spring_forward_open_boundary(self):
        assert await local_is_open(et(2026, 3, 9, 9, 30)) is True

    @pytest.mark.asyncio
    async def test_monday_after_spring_forward_closed_before_open(self):
        assert await local_is_open(et(2026, 3, 9, 9, 29)) is False

    @pytest.mark.asyncio
    async def test_friday_before_fall_back_open(self):
        assert await local_is_open(et(2026, 10, 30, 12, 0)) is True

    @pytest.mark.asyncio
    async def test_monday_after_fall_back_open(self):
        assert await local_is_open(et(2026, 11, 2, 10, 0)) is True

    @pytest.mark.asyncio
    async def test_monday_after_fall_back_boundary(self):
        assert await local_is_open(et(2026, 11, 2, 9, 30)) is True

    @pytest.mark.asyncio
    async def test_monday_after_fall_back_closed_before_open(self):
        assert await local_is_open(et(2026, 11, 2, 9, 29)) is False


# ---------------------------------------------------------------------------
# Holiday / session tests — API response path
# ---------------------------------------------------------------------------


class TestHolidayViaApiOverride:
    """Patch _fetch_market_status to simulate Finnhub API responses."""

    CLOSED_HOLIDAY = {"isOpen": False, "session": None, "holiday": "Independence Day"}
    OPEN_REGULAR = {"isOpen": True, "session": "regular", "holiday": None}
    PRE_MARKET = {"isOpen": True, "session": "pre-market", "holiday": None}
    POST_MARKET = {"isOpen": True, "session": "post-market", "holiday": None}

    @pytest.mark.asyncio
    async def test_holiday_api_says_closed(self):
        result = await api_is_open(et(2026, 7, 3, 12, 0), self.CLOSED_HOLIDAY)
        assert result is False

    @pytest.mark.asyncio
    async def test_normal_day_api_says_open(self):
        result = await api_is_open(et(2026, 3, 16, 12, 0), self.OPEN_REGULAR)
        assert result is True

    @pytest.mark.asyncio
    async def test_pre_market_session_is_closed(self):
        """isOpen=True but session != regular — should be treated as closed."""
        result = await api_is_open(et(2026, 3, 16, 8, 0), self.PRE_MARKET)
        assert result is False

    @pytest.mark.asyncio
    async def test_post_market_session_is_closed(self):
        """isOpen=True but session != regular — should be treated as closed."""
        result = await api_is_open(et(2026, 3, 16, 17, 0), self.POST_MARKET)
        assert result is False

    @pytest.mark.asyncio
    async def test_api_failure_falls_back_to_local_open(self):
        """None from _fetch_market_status triggers local fallback — weekday midday."""
        result = await local_is_open(et(2026, 3, 16, 12, 0))
        assert result is True

    @pytest.mark.asyncio
    async def test_api_failure_falls_back_to_local_weekend(self):
        """None from _fetch_market_status triggers local fallback — Saturday."""
        result = await local_is_open(et(2026, 3, 21, 12, 0))
        assert result is False


# ---------------------------------------------------------------------------
# next_market_open tests
# ---------------------------------------------------------------------------


class TestNextMarketOpen:
    def test_during_session_returns_next_day(self):
        """Called at 12:00 Monday — next open is 09:30 Tuesday."""
        with freeze(et(2026, 3, 16, 12, 0)):
            result = next_market_open()
        assert result == et(2026, 3, 17, 9, 30).astimezone(_UTC)

    def test_after_close_returns_next_day(self):
        with freeze(et(2026, 3, 16, 17, 0)):
            result = next_market_open()
        assert result == et(2026, 3, 17, 9, 30).astimezone(_UTC)

    def test_friday_after_close_returns_monday(self):
        with freeze(et(2026, 3, 20, 17, 0)):
            result = next_market_open()
        assert result == et(2026, 3, 23, 9, 30).astimezone(_UTC)

    def test_saturday_returns_monday(self):
        with freeze(et(2026, 3, 21, 10, 0)):
            result = next_market_open()
        assert result == et(2026, 3, 23, 9, 30).astimezone(_UTC)

    def test_sunday_returns_monday(self):
        with freeze(et(2026, 3, 22, 10, 0)):
            result = next_market_open()
        assert result == et(2026, 3, 23, 9, 30).astimezone(_UTC)

    def test_before_open_same_day(self):
        """Called at 08:00 Monday — next open is 09:30 the same day."""
        with freeze(et(2026, 3, 16, 8, 0)):
            result = next_market_open()
        assert result == et(2026, 3, 16, 9, 30).astimezone(_UTC)

    def test_exactly_at_open_returns_next_day(self):
        """Called exactly at 09:30 — this moment is open so next open is tomorrow."""
        with freeze(et(2026, 3, 16, 9, 30)):
            result = next_market_open()
        assert result == et(2026, 3, 17, 9, 30).astimezone(_UTC)

    def test_result_is_always_utc(self):
        with freeze(et(2026, 3, 16, 17, 0)):
            result = next_market_open()
        assert str(result.tzinfo) in ("UTC", "utc")

    def test_dst_spring_forward_friday_to_monday(self):
        """Friday 6 March after close → Monday 9 March (post DST change)."""
        with freeze(et(2026, 3, 6, 17, 0)):
            result = next_market_open()
        assert result == et(2026, 3, 9, 9, 30).astimezone(_UTC)
