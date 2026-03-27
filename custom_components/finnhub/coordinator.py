"""DataUpdateCoordinator for Finnhub — single shared polling hub."""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import aiohttp
from homeassistant.const import CONF_API_KEY
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import FinnhubApiError, FinnhubClient, MarketStatus, QuoteResult
from .const import (
    ALL_LEVELS,
    CONF_SCAN_INTERVAL,
    CONF_SYMBOLS,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    EVENT_PRICE_TRIGGER,
    HEALTH_ERROR,
    HEALTH_OK,
    HEALTH_PARTIAL,
    HEALTH_PAUSED,
    MARKET_CLOSE,
    MARKET_DAYS,
    MARKET_OPEN,
    MARKET_STATUS_CACHE_SECONDS,
    MARKET_TIMEZONE,
    RATE_LIMIT_BURST,
    RATE_LIMIT_BURST_PERIOD,
    RATE_LIMIT_CALLS,
    RATE_LIMIT_PERIOD,
    STATE_ALERTS_ENTITY_SUFFIX,
    STATE_HYSTERESIS_ENTITY_SUFFIX,
)
from .rate_limiter import RateLimiter

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import StateType

_LOGGER = logging.getLogger(__name__)
_TZ = ZoneInfo(MARKET_TIMEZONE)


def _safe_scan_interval(symbol_count: int, requested_minutes: int) -> timedelta:
    """
    Compute safe scan interval based on symbol count and user preference.

    Return the polling interval, respecting both the user's preference
    and the minimum required by the rate limiter for the given symbol count.

    The rate limiter minimum takes precedence — requesting 1 minute with
    80 symbols will be silently floored to 2 minutes to avoid quota breach.
    """
    rate_limit_minimum = math.ceil(symbol_count / RATE_LIMIT_CALLS)
    effective_minutes = max(requested_minutes, rate_limit_minimum)
    if effective_minutes > requested_minutes:
        _LOGGER.warning(
            "Finnhub: requested interval %dm is too short for %d symbols — using %dm to stay within rate limit",
            requested_minutes,
            symbol_count,
            effective_minutes,
        )
    return timedelta(minutes=effective_minutes)
    # return timedelta(seconds=1)  # for testing only — speed up cycles during development  # noqa: ERA001


def next_market_open() -> datetime:
    """Return the datetime of the next NYSE market open in UTC."""
    now = dt_util.now().astimezone(_TZ)
    candidate = now.replace(hour=MARKET_OPEN.hour, minute=MARKET_OPEN.minute, second=0, microsecond=0)
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
        entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        self.api_key = entry.data[CONF_API_KEY]
        self.symbols = [s.upper().strip() for s in entry.data[CONF_SYMBOLS] if s.strip()]
        self._requested_scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES)
        self._rate_limiter = RateLimiter(
            max_calls=RATE_LIMIT_CALLS,
            period=RATE_LIMIT_PERIOD,
            max_burst=RATE_LIMIT_BURST,
            burst_period=RATE_LIMIT_BURST_PERIOD,
        )

        scan_interval = _safe_scan_interval(len(self.symbols), self._requested_scan_interval)
        self._unsub_market_open: Callable[[], None] | None = None
        self._market_status: MarketStatus | None = None
        self._market_status_fetched_at: float = 0.0
        self._trading_today: bool | None = None  # None = not yet checked today
        self._trading_today_date: date | None = None  # date it was last checked
        self.last_update_success_time: datetime | None = None
        self.health_status: str = HEALTH_OK
        self.failed_symbols: list[str] = []
        self._alert_state: dict[str, dict[str, dict[str, object]]] = {}
        self._signal_state: dict[str, dict[str, Any]] = {}
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

    def update_config(self, entry: ConfigEntry) -> None:
        """Update coordinator config from the given entry (e.g. after options flow)."""
        self.api_key = entry.data[CONF_API_KEY]
        self.symbols = [s.upper().strip() for s in entry.data[CONF_SYMBOLS] if s.strip()]
        self._requested_scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES)
        self.update_interval = _safe_scan_interval(len(self.symbols), self._requested_scan_interval)
        self._client = None
        self._market_status = None
        self._alert_state = {symbol: self._alert_state.get(symbol, {}) for symbol in self.symbols}
        self._signal_state = {symbol: self._signal_state.get(symbol, {}) for symbol in self.symbols}
        self._market_status_fetched_at = 0.0

    async def _fetch_market_status(self) -> MarketStatus | None:
        """Delegate to FinnhubClient with a short-lived cache."""
        now = dt_util.now().timestamp()
        if self._market_status is not None and now - self._market_status_fetched_at < MARKET_STATUS_CACHE_SECONDS:
            _LOGGER.debug("Finnhub: returning cached market status")
            return self._market_status

        # FinnhubApiError (e.g. 401) must propagate up to _async_update_data
        # so ConfigEntryAuthFailed can be raised and polling halted
        data = await self._get_client().get_market_status()
        if data is not None:
            self._market_status = data
            self._market_status_fetched_at = now
        else:
            _LOGGER.warning("Finnhub: market status unavailable, falling back to local time check")
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
            _LOGGER.warning("Finnhub: market status API unavailable, assuming market is open")
            is_open = True  # optimistic fallback — better to poll than to miss a session

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

        async def _on_market_open(now: datetime) -> None:  # noqa: ARG001
            self._unsub_market_open = None
            self._invalidate_daily_cache()
            _LOGGER.debug("Finnhub: market open — resuming polling")
            await self.async_refresh()

        self._unsub_market_open = async_track_point_in_time(self.hass, _on_market_open, open_at)

    def _switch_entity_id(self, symbol: str) -> str:
        """Return the alert enable switch entity_id for a symbol."""
        return f"switch.market_{symbol.lower()}{STATE_ALERTS_ENTITY_SUFFIX}"

    def _hysteresis_entity_id(self, symbol: str) -> str:
        """Return the hysteresis number entity_id for a symbol."""
        return f"number.market_{symbol.lower()}{STATE_HYSTERESIS_ENTITY_SUFFIX}"

    def _level_entity_id(self, symbol: str, level_key: str) -> str:
        """Return the configured level number entity_id for a symbol/level."""
        return f"number.market_{symbol.lower()}_{level_key}"

    @staticmethod
    def _state_as_float(value: StateType, default: float = 0.0) -> float:
        """Convert a Home Assistant state value to float safely."""
        if value in (None, "unknown", "unavailable"):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _alerts_enabled(self, symbol: str) -> bool:
        """Return whether alerts are enabled for this symbol."""
        state_obj = self.hass.states.get(self._switch_entity_id(symbol))
        if state_obj is None:
            return True
        return state_obj.state == "on"

    def _get_hysteresis(self, symbol: str) -> float:
        """Return configured hysteresis for this symbol."""
        entity_id = self._hysteresis_entity_id(symbol)
        state_obj = self.hass.states.get(entity_id)
        if state_obj is None:
            _LOGGER.debug("Finnhub: missing hysteresis entity %s for symbol %s", entity_id, symbol)
            return 0.0
        return self._state_as_float(state_obj.state, default=0.0)

    def _get_levels(self, symbol: str) -> dict[str, float]:
        """Return configured levels for this symbol."""
        levels: dict[str, float] = {}

        for level_key in ALL_LEVELS:
            entity_id = self._level_entity_id(symbol, level_key)
            state_obj = self.hass.states.get(entity_id)

            if state_obj is None:
                _LOGGER.debug("Finnhub: missing level entity %s for symbol %s", entity_id, symbol)
                levels[level_key] = 0.0
            else:
                levels[level_key] = self._state_as_float(state_obj.state, default=0.0)

        return levels

    def _ensure_alert_state(self, symbol: str, level_key: str) -> dict[str, object]:
        """Return mutable latch state for a symbol/level pair."""
        symbol_state = self._alert_state.setdefault(symbol, {})
        return symbol_state.setdefault(
            level_key,
            {
                "armed": True,
                "last_triggered_at": None,
                "last_triggered_price": None,
                "last_direction": None,
            },
        )

    def _ensure_signal_state(self, symbol: str) -> dict[str, Any]:
        """Return mutable compact signal state for a symbol."""
        return self._signal_state.setdefault(
            symbol,
            {
                "state": "idle",
                "last_triggered_level": None,
                "last_triggered_at": None,
                "last_triggered_price": None,
                "current_price": None,
                "alerts_enabled": True,
                "hysteresis": 0.0,
                "armed_levels": [],
            },
        )

    def get_signal_state(self, symbol: str) -> dict[str, Any]:
        """Return compact signal state for a symbol."""
        return dict(self._ensure_signal_state(symbol))

    def _update_signal_snapshot(
        self,
        *,
        symbol: str,
        current_price: float | None,
        alerts_enabled: bool,
        hysteresis: float,
        levels: dict[str, float],
    ) -> None:
        """Refresh non-trigger snapshot fields."""
        signal = self._ensure_signal_state(symbol)

        signal["current_price"] = current_price
        signal["alerts_enabled"] = alerts_enabled
        signal["hysteresis"] = hysteresis

        signal["armed_levels"] = [
            level_key
            for level_key, target in levels.items()
            if target > 0 and bool(self._ensure_alert_state(symbol, level_key)["armed"])
        ]

    def _fire_trigger_event(  # noqa: PLR0913
        self,
        *,
        symbol: str,
        level_key: str,
        direction: str,
        price: float,
        target: float,
        hysteresis: float,
    ) -> None:
        """Fire a one-shot HA event when a level crossing is detected."""
        payload = {
            "symbol": symbol,
            "level": level_key,
            "direction": direction,
            "price": price,
            "target": target,
            "hysteresis": hysteresis,
            "triggered_at": dt_util.now().isoformat(),
        }
        _LOGGER.debug("Finnhub: firing %s: %s", EVENT_PRICE_TRIGGER, payload)
        self.hass.bus.async_fire(EVENT_PRICE_TRIGGER, payload)

    async def _process_price_triggers(self, results: dict[str, QuoteResult]) -> None:
        """Evaluate configured levels and fire one-shot trigger events."""
        for symbol, quote in results.items():
            price = quote.get("c")
            if price is None:
                continue

            alerts_enabled = self._alerts_enabled(symbol)
            hysteresis = self._get_hysteresis(symbol)
            levels = self._get_levels(symbol)

            self._update_signal_snapshot(
                symbol=symbol,
                current_price=price,
                alerts_enabled=alerts_enabled,
                hysteresis=hysteresis,
                levels=levels,
            )

            if not alerts_enabled:
                continue

            for level_key, target in levels.items():
                if target <= 0:
                    continue

                state = self._ensure_alert_state(symbol, level_key)
                armed = bool(state["armed"])

                if level_key.startswith("upper"):
                    if armed and price >= target:
                        self._fire_trigger_event(
                            symbol=symbol,
                            level_key=level_key,
                            direction="up",
                            price=price,
                            target=target,
                            hysteresis=hysteresis,
                        )
                        state["armed"] = False
                        state["last_triggered_at"] = dt_util.now().isoformat()
                        state["last_triggered_price"] = price
                        state["last_direction"] = "up"

                        signal = self._ensure_signal_state(symbol)
                        signal["state"] = f"{level_key}_triggered"
                        signal["last_triggered_level"] = level_key
                        signal["last_triggered_at"] = state["last_triggered_at"]
                        signal["last_triggered_price"] = price
                    elif not armed and price <= (target - hysteresis):
                        state["armed"] = True
                elif armed and price <= target:
                    self._fire_trigger_event(
                        symbol=symbol,
                        level_key=level_key,
                        direction="down",
                        price=price,
                        target=target,
                        hysteresis=hysteresis,
                    )
                    state["armed"] = False
                    state["last_triggered_at"] = dt_util.now().isoformat()
                    state["last_triggered_price"] = price
                    state["last_direction"] = "down"

                    signal = self._ensure_signal_state(symbol)
                    signal["state"] = f"{level_key}_triggered"
                    signal["last_triggered_level"] = level_key
                    signal["last_triggered_at"] = state["last_triggered_at"]
                    signal["last_triggered_price"] = price
                elif not armed and price >= (target + hysteresis):
                    state["armed"] = True

            self._update_signal_snapshot(
                symbol=symbol,
                current_price=price,
                alerts_enabled=alerts_enabled,
                hysteresis=hysteresis,
                levels=levels,
            )

    async def _async_update_data(self) -> dict[str, QuoteResult]:  # noqa: PLR0912, PLR0915
        """Fetch all symbol quotes, respecting the rate limit."""
        try:
            market_open = await self._is_market_open()
        except FinnhubApiError as err:
            if "401" in str(err):
                raise ConfigEntryAuthFailed(str(err)) from err
            raise UpdateFailed(str(err)) from err

        if not market_open:
            self.health_status = HEALTH_PAUSED
            self.failed_symbols = []
            _LOGGER.debug(
                "Finnhub: outside market hours — pausing polling until %s",
                next_market_open(),
            )
            # Pause the coordinator's own update loop
            self.update_interval = None
            # Schedule a wakeup at next market open
            self._schedule_market_open_wakeup()
            return self.data or {}

        # We're inside market hours — make sure polling is active
        if self.update_interval is None:
            self.update_interval = _safe_scan_interval(len(self.symbols), self._requested_scan_interval)
            _LOGGER.debug("Finnhub: polling resumed, interval %s", self.update_interval)

        client = self._get_client()
        results: dict[str, QuoteResult] = {}
        failed: list[str] = []

        for symbol in self.symbols:
            await self._rate_limiter.acquire()
            _LOGGER.debug("Fetching quote for %s", symbol)
            try:
                quote = await client.get_quote(symbol)
                if quote is not None:
                    results[symbol] = quote
                else:
                    failed.append(symbol)
            except FinnhubApiError as err:
                if "401" in str(err):
                    raise ConfigEntryAuthFailed(str(err)) from err
                raise UpdateFailed(str(err)) from err
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                _LOGGER.warning("Finnhub: unexpected error fetching quote for %s: %s", symbol, err)
                failed.append(symbol)

        # Carry forward last known data for any symbols that failed this cycle
        # so sensors retain their last value rather than going unavailable
        if failed and self.data:
            for symbol in failed:
                if symbol in self.data:
                    results[symbol] = self.data[symbol]
                    _LOGGER.debug(
                        "Finnhub: carrying forward last known value for %s",
                        symbol,
                    )
                else:
                    _LOGGER.warning(
                        "Finnhub: no previous data to carry forward for %s",
                        symbol,
                    )

        self.failed_symbols = failed
        if failed and len(failed) == len(self.symbols):
            self.health_status = HEALTH_ERROR
        elif failed:
            self.health_status = HEALTH_PARTIAL
        else:
            self.health_status = HEALTH_OK

        self.last_update_success_time = dt_util.now()
        await self._process_price_triggers(results)
        next_call = dt_util.now() + self.update_interval
        _LOGGER.debug(
            "Finnhub: fetch complete — %d/%d symbols updated, next call at %s",
            len(results),
            len(self.symbols),
            next_call.astimezone(ZoneInfo(MARKET_TIMEZONE)).strftime("%H:%M:%S %Z"),
        )

        return results

    @property
    def trading_today(self) -> bool | None:
        """Whether the market is open today — None if not yet checked."""
        return self._trading_today

    @property
    def rate_limiter(self) -> RateLimiter:
        """The coordinator's RateLimiter instance, for diagnostic sensors."""
        return self._rate_limiter
