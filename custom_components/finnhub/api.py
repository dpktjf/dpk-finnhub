"""Finnhub REST API client — all HTTP calls live here."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TypedDict

import aiohttp

from .const import (
    RETRY_ATTEMPTS,
    RETRY_BASE_DELAY,
    RETRY_JITTER,
    RETRY_MAX_DELAY,
    FINNHUB_MARKET_STATUS_URL,
    FINNHUB_QUOTE_URL,
    MARKET_EXCHANGE,
)

_LOGGER = logging.getLogger(__name__)


class MarketStatus(TypedDict):
    exchange: str
    holiday: str | None
    isOpen: bool
    session: str | None  # pre-market | regular | post-market | null
    t: int
    timezone: str


class QuoteResult(TypedDict):
    c: float  # current price
    o: float  # open
    h: float  # high
    l: float  # low
    pc: float  # previous close
    d: float  # change
    dp: float  # change percent
    t: int  # timestamp


class FinnhubApiError(Exception):
    """Raised when the Finnhub API returns an unrecoverable error."""


async def _with_backoff(coro_fn, attempts: int, base_delay: float, max_delay: float):
    """
    Retry an async callable with exponential backoff and jitter.

    coro_fn must be a zero-argument callable that returns a coroutine,
    e.g. lambda: session.get(...) — called fresh on each attempt so the
    coroutine is not reused.

    Raises the last exception if all attempts are exhausted.
    Does NOT retry FinnhubApiError (401, 429) — those are not transient.
    """
    last_err: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            return await coro_fn()
        except FinnhubApiError:
            raise  # never retry auth/rate errors
        except Exception as err:
            last_err = err
            if attempt == attempts:
                break
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            jitter = delay * RETRY_JITTER * (2 * random.random() - 1)
            sleep_for = max(0.0, delay + jitter)
            _LOGGER.debug(
                "Finnhub: attempt %d/%d failed (%s) — retrying in %.2fs",
                attempt,
                attempts,
                err,
                sleep_for,
            )
            await asyncio.sleep(sleep_for)

    if last_err is not None:
        raise last_err
    # Should be unreachable — attempts must be >= 1
    raise RuntimeError("_with_backoff called with zero attempts")


class FinnhubClient:
    """Thin async wrapper around the Finnhub REST API."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._session = session
        self._api_key = api_key

    async def get_quote(self, symbol: str) -> QuoteResult | None:
        """
        Fetch a single equity quote.

        Returns None if the symbol is unknown or returns empty data.
        Raises FinnhubApiError on authentication or rate-limit failures.
        """

        async def _fetch():
            async with self._session.get(
                FINNHUB_QUOTE_URL,
                params={"symbol": symbol, "token": self._api_key},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 401:
                    raise FinnhubApiError(f"API key rejected by Finnhub (HTTP 401)")
                if resp.status == 429:
                    raise FinnhubApiError("Rate limit exceeded (HTTP 429)")
                resp.raise_for_status()
                data: QuoteResult = await resp.json()

                if data.get("c", 0) == 0 and data.get("t", 0) == 0:
                    _LOGGER.warning(
                        "Finnhub returned empty quote for '%s' — "
                        "check the ticker is valid",
                        symbol,
                    )
                    return None

                return data

        try:
            return await _with_backoff(
                _fetch,
                attempts=RETRY_ATTEMPTS,
                base_delay=RETRY_BASE_DELAY,
                max_delay=RETRY_MAX_DELAY,
            )
        except FinnhubApiError:
            raise
        except Exception as err:
            _LOGGER.warning(
                "Finnhub: all %d attempts failed for %s: %s",
                RETRY_ATTEMPTS,
                symbol,
                err,
            )
            return None

    async def get_market_status(self) -> MarketStatus | None:
        """
        Fetch current US market status.

        Returns None on any failure — callers should fall back to local
        time-based check when this returns None.
        """
        try:
            async with self._session.get(
                FINNHUB_MARKET_STATUS_URL,
                params={"exchange": MARKET_EXCHANGE, "token": self._api_key},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 401:
                    raise FinnhubApiError("API key rejected by Finnhub (HTTP 401)")
                resp.raise_for_status()
                data: MarketStatus = await resp.json()
                _LOGGER.debug(
                    "Finnhub market status: isOpen=%s session=%s holiday=%s",
                    data.get("isOpen"),
                    data.get("session"),
                    data.get("holiday"),
                )
                return data
        except FinnhubApiError:
            raise
        except aiohttp.ClientError as err:
            _LOGGER.warning("Finnhub: could not fetch market status: %s", err)
            return None
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Finnhub: unexpected error fetching market status: %s", err)
            return None
