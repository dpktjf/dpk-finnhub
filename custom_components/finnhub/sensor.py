"""Sensor platform for Finnhub Stock Quotes."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_CHANGE,
    ATTR_CHANGE_PERCENT,
    ATTR_HIGH,
    ATTR_LOW,
    ATTR_OPEN,
    ATTR_PREVIOUS_CLOSE,
    ATTR_SYMBOL,
    CONF_SYMBOLS,
    DOMAIN,
)
from .coordinator import FinnhubCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .api import QuoteResult

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Finnhub sensors from a config entry."""
    coordinator: FinnhubCoordinator = hass.data[DOMAIN][entry.entry_id]
    symbols: list[str] = entry.data[CONF_SYMBOLS]

    entities: list[SensorEntity] = [
        FinnhubQuoteSensor(coordinator, symbol) for symbol in symbols
    ]
    entities.append(FinnhubHealthSensor(coordinator))
    entities.append(FinnhubRateLimiterSensor(coordinator))
    async_add_entities(entities)


_EMPTY_QUOTE: QuoteResult = {
    "c": 0.0,
    "o": 0.0,
    "h": 0.0,
    "l": 0.0,
    "pc": 0.0,
    "d": 0.0,
    "dp": 0.0,
    "t": 0,
}
_DEVICE_INFO = DeviceInfo(
    identifiers={(DOMAIN, "finnhub")},
    name="Finnhub",
    manufacturer="Finnhub.io",
    model="Stock Quote API",
    entry_type=DeviceEntryType.SERVICE,
)


class FinnhubQuoteSensor(
    CoordinatorEntity[FinnhubCoordinator], SensorEntity, RestoreEntity
):
    """A sensor representing the current price of a single equity symbol."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_info = _DEVICE_INFO
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = "mdi:chart-line"
    _attr_has_entity_name = False
    _last_known_value: float | None = None
    _last_known_attributes: dict = {}

    def __init__(self, coordinator: FinnhubCoordinator, symbol: str) -> None:
        super().__init__(coordinator)
        self._symbol = symbol.upper()
        self._attr_unique_id = f"{DOMAIN}_{self._symbol.lower()}"
        self._attr_name = self._symbol
        self.entity_id = f"sensor.market_{self._symbol.lower()}"

    async def async_added_to_hass(self) -> None:
        """Restore last known state on HA restart."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self._last_known_value = float(last_state.state)
                self._last_known_attributes = dict(last_state.attributes)
            except (ValueError, TypeError):
                pass

    @property
    def native_value(self) -> float | None:
        """Return live price during market hours, last known price outside."""
        live = self._quote.get("c")
        if live:
            self._last_known_value = float(live)
            return self._last_known_value
        return self._last_known_value

    @property
    def extra_state_attributes(self) -> dict:
        q = self._quote
        attrs = {
            ATTR_SYMBOL: self._symbol,
            ATTR_OPEN: q.get("o"),
            ATTR_HIGH: q.get("h"),
            ATTR_LOW: q.get("l"),
            ATTR_PREVIOUS_CLOSE: q.get("pc"),
            ATTR_CHANGE: q.get("d"),
            ATTR_CHANGE_PERCENT: q.get("dp"),
        }
        # Merge in last known values for any keys that are currently None
        # (coordinator returns cached data outside hours, but on first boot
        # before any live fetch the quote may be empty)
        if not any(v for k, v in attrs.items() if k != ATTR_SYMBOL):
            return self._last_known_attributes or attrs
        self._last_known_attributes = attrs
        return attrs

    @property
    def available(self) -> bool:
        """Available if we have any price data — live or cached."""
        return super().available and (
            bool(self._quote.get("c")) or self._last_known_value is not None
        )

    @property
    def _quote(self) -> QuoteResult:
        if self.coordinator.data:
            return self.coordinator.data.get(self._symbol, _EMPTY_QUOTE)
        return _EMPTY_QUOTE


class FinnhubHealthSensor(CoordinatorEntity[FinnhubCoordinator], SensorEntity):
    """Coordinator health — exposes last fetch time, error count, and status."""

    _attr_icon = "mdi:heart-pulse"
    _attr_device_info = _DEVICE_INFO
    _attr_has_entity_name = False
    _attr_name = "finnhub_health"
    _attr_unique_id = f"{DOMAIN}_health"

    @property
    def native_value(self) -> str:
        """Overall status string — ok, degraded, or error."""
        return self.coordinator.health_status

    @property
    def extra_state_attributes(self) -> dict:

        last_success = getattr(self.coordinator, "last_update_success_time", None)
        return {
            "last_update_success": self.coordinator.last_update_success,
            "last_successful_fetch": last_success.isoformat() if last_success else None,
            "symbols_tracked": len(self.coordinator.symbols),
            "symbols_failed": self.coordinator.failed_symbols,
            "symbols_ok": len(self.coordinator.symbols)
            - len(self.coordinator.failed_symbols),
            "update_interval_seconds": (
                int(self.coordinator.update_interval.total_seconds())
                if self.coordinator.update_interval
                else None
            ),
            "trading_today": self.coordinator._trading_today,
            "market_session_active": self.coordinator.update_interval is not None,
        }


class FinnhubRateLimiterSensor(CoordinatorEntity[FinnhubCoordinator], SensorEntity):
    """Diagnostic sensor exposing rate limiter window utilisation."""

    _attr_icon = "mdi:speedometer"
    _attr_has_entity_name = False
    _attr_name = "finnhub_rate_limiter"
    _attr_unique_id = f"{DOMAIN}_rate_limiter"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> int:
        """Calls used in the current 60s window — primary at-a-glance value."""
        return self.coordinator._rate_limiter.minute_window_used

    @property
    def native_unit_of_measurement(self) -> str:
        return "calls"

    @property
    def extra_state_attributes(self) -> dict:
        rl = self.coordinator._rate_limiter
        minute_used = rl.minute_window_used
        burst_used = rl.burst_window_used
        return {
            "minute_window_used": minute_used,
            "minute_window_capacity": rl.minute_window_capacity,
            "minute_window_remaining": rl.minute_window_capacity - minute_used,
            "minute_window_pct": round(
                minute_used / rl.minute_window_capacity * 100, 1
            ),
            "burst_window_used": burst_used,
            "burst_window_capacity": rl.burst_window_capacity,
            "burst_window_remaining": rl.burst_window_capacity - burst_used,
            "burst_window_pct": round(burst_used / rl.burst_window_capacity * 100, 1),
            "symbols_tracked": len(self.coordinator.symbols),
        }
