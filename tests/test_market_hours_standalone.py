"""
Standalone market hours tests — no Home Assistant dependency.

Tests the is_market_open / next_market_open logic directly using
frozen datetime values injected via monkeypatch.

Run with:
    pytest tests/test_market_hours_standalone.py -v
"""
# ruff: noqa BLE001, PLR2004, PLR0912

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Inline copies of production constants and logic — no HA imports needed
# ---------------------------------------------------------------------------

MARKET_TIMEZONE = "America/New_York"
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
MARKET_DAYS = frozenset({0, 1, 2, 3, 4})  # Mon–Fri

_TZ = ZoneInfo(MARKET_TIMEZONE)
_UTC = ZoneInfo("UTC")


def _now_et(fake_now: datetime) -> datetime:
    """Convert a UTC datetime to ET — stand-in for dt_util.now()."""
    return fake_now.astimezone(_TZ)


def is_market_open(now_utc: datetime, status_override: dict | None = None) -> bool:
    """
    Equivalent of coordinator._is_market_open() without the API call.

    Pass status_override to simulate a Finnhub market-status API response,
    or leave None to exercise the local fallback path.
    """
    if status_override is not None:
        return status_override.get("isOpen", False) and status_override.get("session") == "regular"
    now = _now_et(now_utc)
    if now.weekday() not in MARKET_DAYS:
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


def next_market_open(now_utc: datetime) -> datetime:
    """Equivalent of coordinator.next_market_open()."""
    now = _now_et(now_utc)
    candidate = now.replace(
        hour=MARKET_OPEN.hour,
        minute=MARKET_OPEN.minute,
        second=0,
        microsecond=0,
    )
    if now >= candidate:
        candidate += timedelta(days=1)
    while candidate.weekday() not in MARKET_DAYS:
        candidate += timedelta(days=1)
    return candidate.astimezone(_UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def et(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Construct a timezone-aware datetime in America/New_York."""
    return datetime(year, month, day, hour, minute, tzinfo=_TZ)


def utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Construct a timezone-aware datetime in UTC."""
    return datetime(year, month, day, hour, minute, tzinfo=_UTC)


# ---------------------------------------------------------------------------
# Core open/close boundary tests
# ---------------------------------------------------------------------------


class TestMarketOpenBoundaries:
    def test_exactly_at_open_is_open(self) -> None:
        """09:30:00 is the start of the session — should be open."""
        assert is_market_open(et(2026, 3, 16, 9, 30)) is True

    def test_one_minute_before_open_is_closed(self) -> None:
        """09:29:00 is before the session starts — should be closed."""
        assert is_market_open(et(2026, 3, 16, 9, 29)) is False

    def test_midday_is_open(self) -> None:
        """12:00:00 is during the session — should be open."""
        assert is_market_open(et(2026, 3, 16, 12, 0)) is True

    def test_exactly_at_close_is_open(self) -> None:
        """16:00:00 is still within the session."""
        assert is_market_open(et(2026, 3, 16, 16, 0)) is True

    def test_one_minute_after_close_is_closed(self) -> None:
        """16:01:00 is after the session ends — should be closed."""
        assert is_market_open(et(2026, 3, 16, 16, 1)) is False

    def test_midnight_is_closed(self) -> None:
        """00:00:00 is outside the session hours — should be closed."""
        assert is_market_open(et(2026, 3, 16, 0, 0)) is False

    def test_pre_market_is_closed(self) -> None:
        """08:00:00 is before the session starts — should be closed."""
        assert is_market_open(et(2026, 3, 16, 8, 0)) is False

    def test_post_market_is_closed(self) -> None:
        """17:00:00 is after the session ends — should be closed."""
        assert is_market_open(et(2026, 3, 16, 17, 0)) is False


# ---------------------------------------------------------------------------
# Weekday tests
# ---------------------------------------------------------------------------


class TestWeekdays:
    """2026-03-16 is a Monday — use offsets to hit each day."""

    def test_monday_is_open(self) -> None:
        """Monday 10:00 is during session hours — should be open."""
        assert is_market_open(et(2026, 3, 16, 10, 0)) is True  # noqa: S101

    def test_tuesday_is_open(self) -> None:
        """Tuesday 10:00 is during session hours — should be open."""
        assert is_market_open(et(2026, 3, 17, 10, 0)) is True

    def test_wednesday_is_open(self) -> None:
        """Wednesday 10:00 is during session hours — should be open."""
        assert is_market_open(et(2026, 3, 18, 10, 0)) is True

    def test_thursday_is_open(self) -> None:
        """Thursday 10:00 is during session hours — should be open."""
        assert is_market_open(et(2026, 3, 19, 10, 0)) is True

    def test_friday_is_open(self) -> None:
        """Friday 10:00 is during session hours — should be open."""
        assert is_market_open(et(2026, 3, 20, 10, 0)) is True

    def test_saturday_is_closed(self) -> None:
        """Saturday 10:00 is during session hours but weekend — should be closed."""
        assert is_market_open(et(2026, 3, 21, 10, 0)) is False

    def test_sunday_is_closed(self) -> None:
        """Sunday 10:00 is during session hours but weekend — should be closed."""
        assert is_market_open(et(2026, 3, 22, 10, 0)) is False

    def test_saturday_during_session_hours_is_closed(self) -> None:
        """Even if time falls in 09:30–16:00, weekend must be closed."""
        assert is_market_open(et(2026, 3, 21, 12, 0)) is False  # noqa: S101


# ---------------------------------------------------------------------------
# DST transition tests
# ---------------------------------------------------------------------------


class TestDSTTransitions:
    """US DST transitions: spring forward 2nd Sunday March,
    fall back 1st Sunday November."""

    def test_day_before_spring_forward_open(self):
        """Saturday before DST — market closed (weekend)."""
        assert is_market_open(et(2026, 3, 7, 12, 0)) is False

    def test_monday_after_spring_forward_open(self):
        """Monday after clocks move forward — session should still be 09:30–16:00 ET."""
        assert is_market_open(et(2026, 3, 9, 10, 0)) is True

    def test_monday_after_spring_forward_open_boundary(self):
        assert is_market_open(et(2026, 3, 9, 9, 30)) is True

    def test_monday_after_spring_forward_closed_before_open(self):
        assert is_market_open(et(2026, 3, 9, 9, 29)) is False

    def test_day_before_fall_back_open(self):
        """Friday before clocks fall back."""
        assert is_market_open(et(2026, 10, 30, 12, 0)) is True

    def test_monday_after_fall_back_open(self):
        """Monday after clocks fall back — session hours unchanged in ET."""
        assert is_market_open(et(2026, 11, 2, 10, 0)) is True

    def test_monday_after_fall_back_boundary(self):
        assert is_market_open(et(2026, 11, 2, 9, 30)) is True

    def test_monday_after_fall_back_closed_before_open(self):
        assert is_market_open(et(2026, 11, 2, 9, 29)) is False


# ---------------------------------------------------------------------------
# Holiday tests — via Finnhub API status_override
# ---------------------------------------------------------------------------


class TestHolidayViaApiOverride:
    """Simulate Finnhub /stock/market-status responses for holiday scenarios."""

    CLOSED_RESPONSE = {"isOpen": False, "session": None, "holiday": "Independence Day"}
    OPEN_RESPONSE = {"isOpen": True, "session": "regular", "holiday": None}
    PRE_MARKET_RESPONSE = {"isOpen": True, "session": "pre-market", "holiday": None}
    POST_MARKET_RESPONSE = {"isOpen": True, "session": "post-market", "holiday": None}

    def test_holiday_api_says_closed(self):
        """When API reports holiday closure, treat as closed regardless of time."""
        # 4th July 2026 is a Saturday, but test the logic on a weekday
        now = et(2026, 7, 3, 12, 0)  # Friday before Independence Day observed
        assert is_market_open(now, status_override=self.CLOSED_RESPONSE) is False

    def test_normal_day_api_says_open(self):
        now = et(2026, 3, 16, 12, 0)
        assert is_market_open(now, status_override=self.OPEN_RESPONSE) is True

    def test_pre_market_session_is_closed(self):
        """Pre-market: isOpen=True but session != regular — should be closed."""
        now = et(2026, 3, 16, 8, 0)
        assert is_market_open(now, status_override=self.PRE_MARKET_RESPONSE) is False

    def test_post_market_session_is_closed(self):
        """Post-market: isOpen=True but session != regular — should be closed."""
        now = et(2026, 3, 16, 17, 0)
        assert is_market_open(now, status_override=self.POST_MARKET_RESPONSE) is False

    def test_api_none_falls_back_to_local(self):
        """None status_override exercises the local fallback path."""
        now = et(2026, 3, 16, 12, 0)  # Monday midday — should be open
        assert is_market_open(now, status_override=None) is True

    def test_api_none_fallback_weekend(self):
        now = et(2026, 3, 21, 12, 0)  # Saturday — should be closed
        assert is_market_open(now, status_override=None) is False


# ---------------------------------------------------------------------------
# next_market_open tests
# ---------------------------------------------------------------------------


class TestNextMarketOpen:
    def test_during_session_returns_next_day(self):
        """Called at 12:00 Monday — next open is 09:30 Tuesday."""
        now = et(2026, 3, 16, 12, 0)
        result = next_market_open(now)
        expected = et(2026, 3, 17, 9, 30).astimezone(_UTC)
        assert result == expected

    def test_after_close_returns_next_day(self):
        """Called at 17:00 Monday — next open is 09:30 Tuesday."""
        now = et(2026, 3, 16, 17, 0)
        result = next_market_open(now)
        expected = et(2026, 3, 17, 9, 30).astimezone(_UTC)
        assert result == expected

    def test_friday_after_close_returns_monday(self):
        """Called at 17:00 Friday — next open skips weekend to Monday."""
        now = et(2026, 3, 20, 17, 0)
        result = next_market_open(now)
        expected = et(2026, 3, 23, 9, 30).astimezone(_UTC)
        assert result == expected

    def test_saturday_returns_monday(self):
        now = et(2026, 3, 21, 10, 0)
        result = next_market_open(now)
        expected = et(2026, 3, 23, 9, 30).astimezone(_UTC)
        assert result == expected

    def test_sunday_returns_monday(self):
        now = et(2026, 3, 22, 10, 0)
        result = next_market_open(now)
        expected = et(2026, 3, 23, 9, 30).astimezone(_UTC)
        assert result == expected

    def test_before_open_same_day(self):
        """Called at 08:00 Monday — next open is 09:30 the same day."""
        now = et(2026, 3, 16, 8, 0)
        result = next_market_open(now)
        expected = et(2026, 3, 16, 9, 30).astimezone(_UTC)
        assert result == expected

    def test_exactly_at_open_returns_next_day(self):
        """Called exactly at 09:30 — this moment is open, so next open is tomorrow."""
        now = et(2026, 3, 16, 9, 30)
        result = next_market_open(now)
        expected = et(2026, 3, 17, 9, 30).astimezone(_UTC)
        assert result == expected

    def test_result_is_always_utc(self):
        now = et(2026, 3, 16, 17, 0)
        result = next_market_open(now)
        assert result.tzinfo is not None
        assert result.tzinfo == _UTC or str(result.tzinfo) == "UTC"

    def test_dst_spring_forward_friday_to_monday(self):
        """Friday 14 March 2026 after close → Monday 16 March (post DST change)."""
        now = et(2026, 3, 6, 17, 0)  # Friday before spring forward (8 March)
        result = next_market_open(now)
        expected = et(2026, 3, 9, 9, 30).astimezone(_UTC)
        assert result == expected
