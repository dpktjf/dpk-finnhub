"""DataUpdateCoordinator for Finnhub — single shared polling hub."""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import FinnhubApiError, FinnhubClient, MarketStatus, QuoteResult
from .const import (
    DOMAIN,
    MARKET_CLOSE,
    MARKET_DAYS,
    MARKET_OPEN,
    MARKET_STATUS_CACHE_SECONDS,
    MARKET_TIMEZONE,
    RATE_LIMIT_BURST,
    RATE_LIMIT_BURST_PERIOD,
    RATE_LIMIT_CALLS,
    RATE_LIMIT_PERIOD,
)
from .rate_limiter import RateLimiter

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
_TZ = ZoneInfo(MARKET_TIMEZONE)


def _safe_scan_interval(symbol_count: int) -> timedelta:
    """
    Return the minimum safe polling interval for the given symbol count.

    Finnhub free tier: 60 req/min (we use 55 as a safety buffer).
    We need at least one full minute per 55 symbols to stay under quota.
    """
    minutes_needed = math.ceil(symbol_count / RATE_LIMIT_CALLS)
    return timedelta(minutes=max(1, minutes_needed))


def next_market_open() -> datetime:
    """Return the datetime of the next NYSE market open in UTC."""
    now = dt_util.now().astimezone(_TZ)
    candidate = now.replace(
        hour=MARKET_OPEN.hour, minute=MARKET_OPEN.minute, second=0, microsecond=0
    )
    # If we're already past open today, start from tomorrow
    if now >= candidate:
        candidate = candidate + timedelta(days=1)
    # Skip forward over weekends
    while candidate.weekday() not in MARKET_DAYS:
        candidate = candidate + timedelta(days=1)
    return candidate.astimezone(dt_util.UTC)


class FinnhubCoordinator(DataUpdateCoordinator[dict[str, QuoteResult]]):
    """Fetch quotes for all configured symbols in a single update cycle."""

    def __init__(
        self,
        hass: HomeAssistant,
        api_key: str,
        symbols: list[str],
    ) -> None:
        self.api_key = api_key
        self.symbols = [s.upper().strip() for s in symbols if s.strip()]
        self._rate_limiter = RateLimiter(
            max_calls=RATE_LIMIT_CALLS,
            period=RATE_LIMIT_PERIOD,
            max_burst=RATE_LIMIT_BURST,
            burst_period=RATE_LIMIT_BURST_PERIOD,
        )

        scan_interval = _safe_scan_interval(len(self.symbols))
        self._unsub_market_open: Callable[[], None] | None = None
        self._market_status: MarketStatus | None = None
        self._market_status_fetched_at: float = 0.0
        self._trading_today: bool | None = None  # None = not yet checked today
        self._trading_today_date: date | None = None  # date it was last checked
        self.last_update_success_time: datetime | None = None

        self._client: FinnhubClient | None = None

        _LOGGER.debug(
            "Finnhub coordinator: %d symbols, update interval %s",
            len(self.symbols),
            scan_interval,
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=scan_interval,
        )

    def _get_client(self) -> FinnhubClient:
        """Return a FinnhubClient, creating it if needed."""
        if self._client is None:
            self._client = FinnhubClient(
                session=async_get_clientsession(self.hass),
                api_key=self.api_key,
            )
        return self._client

    def update_config(self, api_key: str, symbols: list[str]) -> None:
        """Apply updated configuration and recalculate the scan interval."""
        self.api_key = api_key
        self.symbols = [s.upper().strip() for s in symbols if s.strip()]
        self.update_interval = _safe_scan_interval(len(self.symbols))
        # Force client rebuild with new api_key
        self._client = None
        self._market_status = None
        self._market_status_fetched_at = 0.0

    async def _fetch_market_status(self) -> MarketStatus | None:
        """Delegate to FinnhubClient with a short-lived cache."""
        now = dt_util.now().timestamp()
        if (
            self._market_status is not None
            and now - self._market_status_fetched_at < MARKET_STATUS_CACHE_SECONDS
        ):
            _LOGGER.debug("Finnhub: returning cached market status")
            return self._market_status

        data = await self._get_client().get_market_status()
        if data is not None:
            self._market_status = data
            self._market_status_fetched_at = now
        else:
            _LOGGER.warning(
                "Finnhub: market status unavailable, falling back to local time check"
            )
        return data

    def _invalidate_daily_cache(self) -> None:
        """Clear the trading-day cache so next open re-checks the API."""
        self._trading_today = None
        self._trading_today_date = None
        self._market_status = None
        self._market_status_fetched_at = 0.0

    async def _is_market_open(self) -> bool:
        """
        Check if the US market is currently open, using a two-stage approach.

        Two-stage check:
        1. Local time/weekday check — cheap, runs every tick
        2. API holiday check — runs once per trading day at most
        """
        # Stage 1: fast local check — no API call

        # Fallback: local calendar check (no holiday awareness)
        _LOGGER.debug("Finnhub: using local fallback for market hours check")
        now = dt_util.now().astimezone(_TZ)
        if now.weekday() not in MARKET_DAYS:
            return False
        if not (MARKET_OPEN <= now.time() <= MARKET_CLOSE):
            return False

        # Stage 2: we're within session hours on a weekday — check holiday
        # but only once per calendar day
        today = now.date()
        if self._trading_today is not None and self._trading_today_date == today:
            _LOGGER.debug(
                "Finnhub: using cached trading day status for %s: trading=%s",
                today,
                self._trading_today,
            )
            return self._trading_today

        # First check of this calendar day — hit the API
        _LOGGER.debug("Finnhub: checking market status for %s", today)
        status = await self._fetch_market_status()
        if status is not None:
            is_open = status.get("isOpen", False) and status.get("session") == "regular"
        else:
            _LOGGER.warning(
                "Finnhub: market status API unavailable, assuming market is open"
            )
            is_open = (
                True  # optimistic fallback — better to poll than to miss a session
            )

        self._trading_today = is_open
        self._trading_today_date = today
        return is_open

    async def async_shutdown(self) -> None:
        """Cancel the market-open wakeup listener on unload."""
        if self._unsub_market_open:
            self._unsub_market_open()
            self._unsub_market_open = None
        await super().async_shutdown()

    def _schedule_market_open_wakeup(self) -> None:
        """Register a one-shot callback at the next market open."""
        if self._unsub_market_open:
            self._unsub_market_open()
        open_at = next_market_open()
        _LOGGER.debug("Finnhub: next market open scheduled for %s", open_at)

        async def _on_market_open(now: datetime) -> None:
            self._unsub_market_open = None
            self._invalidate_daily_cache()
            _LOGGER.debug("Finnhub: market open — resuming polling")
            await self.async_refresh()

        self._unsub_market_open = async_track_point_in_time(
            self.hass, _on_market_open, open_at
        )

    async def _async_update_data(self) -> dict[str, QuoteResult]:
        """Fetch all symbol quotes, respecting the rate limit."""
        if not await self._is_market_open():
            _LOGGER.debug(
                "Finnhub: outside market hours — pausing polling until %s",
                next_market_open(),
            )
            # Pause the coordinator's own update loop
            self.update_interval = None
            # Schedule a wakeup at next market open
            self._schedule_market_open_wakeup()
            if self.data:
                return self.data
            return {}

        # We're inside market hours — make sure polling is active
        if self.update_interval is None:
            self.update_interval = _safe_scan_interval(len(self.symbols))
            _LOGGER.debug("Finnhub: polling resumed, interval %s", self.update_interval)

        client = self._get_client()
        results: dict[str, QuoteResult] = {}

        for symbol in self.symbols:
            await self._rate_limiter.acquire()
            _LOGGER.debug("Fetching quote for %s", symbol)
            try:
                quote = await client.get_quote(symbol)
                if quote is not None:
                    results[symbol] = quote
            except FinnhubApiError as err:
                raise UpdateFailed(str(err)) from err

        self.last_update_success_time = dt_util.now()
        next_call = dt_util.now() + self.update_interval
        _LOGGER.debug(
            "Finnhub: fetch complete — %d/%d symbols updated, next call at %s",
            len(results),
            len(self.symbols),
            next_call.astimezone(ZoneInfo(MARKET_TIMEZONE)).strftime("%H:%M:%S %Z"),
        )

        return results
