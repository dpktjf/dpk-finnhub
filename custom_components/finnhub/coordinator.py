"""DataUpdateCoordinator for Finnhub — single shared polling hub."""

from __future__ import annotations

import logging
import math
from datetime import timedelta

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    FINNHUB_QUOTE_URL,
    RATE_LIMIT_CALLS,
    RATE_LIMIT_PERIOD,
)
from .rate_limiter import RateLimiter

_LOGGER = logging.getLogger(__name__)


def _safe_scan_interval(symbol_count: int) -> timedelta:
    """
    Return the minimum safe polling interval for the given symbol count.

    Finnhub free tier: 60 req/min (we use 55 as a safety buffer).
    We need at least one full minute per 55 symbols to stay under quota.
    """
    minutes_needed = math.ceil(symbol_count / RATE_LIMIT_CALLS)
    return timedelta(minutes=max(1, minutes_needed))


class FinnhubCoordinator(DataUpdateCoordinator[dict[str, dict]]):
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
            max_calls=RATE_LIMIT_CALLS, period=RATE_LIMIT_PERIOD
        )

        scan_interval = _safe_scan_interval(len(self.symbols))
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

    def update_config(self, api_key: str, symbols: list[str]) -> None:
        """Apply updated configuration and recalculate the scan interval."""
        self.api_key = api_key
        self.symbols = [s.upper().strip() for s in symbols if s.strip()]
        self.update_interval = _safe_scan_interval(len(self.symbols))

    async def _async_update_data(self) -> dict[str, dict]:
        """Fetch all symbol quotes, respecting the rate limit."""
        session: aiohttp.ClientSession = async_get_clientsession(self.hass)
        results: dict[str, dict] = {}

        for symbol in self.symbols:
            await self._rate_limiter.acquire()
            try:
                async with session.get(
                    FINNHUB_QUOTE_URL,
                    params={"symbol": symbol, "token": self.api_key},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status == 401:
                        raise UpdateFailed(
                            "Finnhub API key is invalid or unauthorised (HTTP 401)"
                        )
                    if response.status == 429:
                        raise UpdateFailed(
                            "Finnhub rate limit exceeded (HTTP 429) — "
                            "reduce symbol count or increase update interval"
                        )
                    response.raise_for_status()
                    data: dict = await response.json()

                    # Finnhub returns {"c":0,"d":null,...} for unknown symbols
                    if data.get("c", 0) == 0 and data.get("t", 0) == 0:
                        _LOGGER.warning(
                            "Finnhub returned no data for symbol '%s' — "
                            "check the ticker is valid",
                            symbol,
                        )
                    results[symbol] = data

            except UpdateFailed:
                raise
            except aiohttp.ClientError as err:
                _LOGGER.warning("Network error fetching %s: %s", symbol, err)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Unexpected error fetching %s: %s", symbol, err)

        return results
