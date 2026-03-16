"""Config flow and options flow for Finnhub integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_API_KEY
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_SYMBOLS, DOMAIN, FINNHUB_QUOTE_URL

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_symbols(raw: str) -> list[str]:
    """Split a comma/space/newline-separated string into a clean symbol list."""
    import re
    tokens = re.split(r"[\s,;]+", raw.upper())
    return [t.strip() for t in tokens if t.strip()]


def _symbols_to_str(symbols: list[str]) -> str:
    return ", ".join(symbols)


async def _validate_api_key(hass, api_key: str) -> str | None:
    """Return an error key string if the key is invalid, else None."""
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            FINNHUB_QUOTE_URL,
            params={"symbol": "AAPL", "token": api_key},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 401:
                return "invalid_api_key"
            if resp.status == 429:
                return "rate_limit"
            resp.raise_for_status()
    except aiohttp.ClientError:
        return "cannot_connect"
    except Exception:  # noqa: BLE001
        return "unknown"
    return None


# ---------------------------------------------------------------------------
# Config flow (initial setup)
# ---------------------------------------------------------------------------

class FinnhubConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle initial configuration via the UI."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key: str = user_input[CONF_API_KEY].strip()
            symbols_raw: str = user_input[CONF_SYMBOLS]
            symbols = _parse_symbols(symbols_raw)

            if not symbols:
                errors[CONF_SYMBOLS] = "no_symbols"
            else:
                error = await _validate_api_key(self.hass, api_key)
                if error:
                    errors["base"] = error
                else:
                    # Prevent duplicate entries
                    await self.async_set_unique_id(api_key[:8])
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title="Finnhub Stock Quotes",
                        data={
                            CONF_API_KEY: api_key,
                            CONF_SYMBOLS: symbols,
                        },
                    )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_API_KEY,
                    description={"suggested_value": user_input.get(CONF_API_KEY, "") if user_input else ""},
                ): str,
                vol.Required(
                    CONF_SYMBOLS,
                    description={"suggested_value": user_input.get(CONF_SYMBOLS, "AAPL, MSFT, GOOGL") if user_input else "AAPL, MSFT, GOOGL"},
                ): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "symbol_hint": "Enter symbols separated by commas, e.g. AAPL, MSFT, TSLA"
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return FinnhubOptionsFlow()


# ---------------------------------------------------------------------------
# Options flow (reconfigure after setup)
# ---------------------------------------------------------------------------

class FinnhubOptionsFlow(OptionsFlow):
    """Allow editing API key and symbols after initial setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        # Current stored values
        current_api_key: str = self.config_entry.data.get(CONF_API_KEY, "")
        current_symbols: list[str] = self.config_entry.data.get(CONF_SYMBOLS, [])

        if user_input is not None:
            api_key: str = user_input[CONF_API_KEY].strip()
            symbols_raw: str = user_input[CONF_SYMBOLS]
            symbols = _parse_symbols(symbols_raw)

            if not symbols:
                errors[CONF_SYMBOLS] = "no_symbols"
            else:
                error = await _validate_api_key(self.hass, api_key)
                if error:
                    errors["base"] = error
                else:
                    # Persist updated values back into config entry data
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data={
                            CONF_API_KEY: api_key,
                            CONF_SYMBOLS: symbols,
                        },
                    )
                    return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY, default=current_api_key): str,
                vol.Required(
                    CONF_SYMBOLS,
                    default=_symbols_to_str(current_symbols),
                ): str,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "symbol_hint": "Separate symbols with commas, e.g. AAPL, MSFT, TSLA"
            },
        )
