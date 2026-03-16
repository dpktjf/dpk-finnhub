"""Sensor platform for Finnhub Stock Quotes."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
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

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Finnhub sensors from a config entry."""
    coordinator: FinnhubCoordinator = hass.data[DOMAIN][entry.entry_id]
    symbols: list[str] = entry.data[CONF_SYMBOLS]

    async_add_entities(
        FinnhubQuoteSensor(coordinator, symbol) for symbol in symbols
    )


class FinnhubQuoteSensor(CoordinatorEntity[FinnhubCoordinator], SensorEntity):
    """A sensor representing the current price of a single equity symbol."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = "mdi:chart-line"
    _attr_has_entity_name = True

    def __init__(self, coordinator: FinnhubCoordinator, symbol: str) -> None:
        super().__init__(coordinator)
        self._symbol = symbol.upper()
        self._attr_unique_id = f"{DOMAIN}_{self._symbol.lower()}"
        self._attr_name = self._symbol

    @property
    def native_value(self) -> float | None:
        """Current price (field 'c' in Finnhub quote response)."""
        return self._quote.get("c") or None

    @property
    def extra_state_attributes(self) -> dict:
        q = self._quote
        return {
            ATTR_SYMBOL: self._symbol,
            ATTR_OPEN: q.get("o"),
            ATTR_HIGH: q.get("h"),
            ATTR_LOW: q.get("l"),
            ATTR_PREVIOUS_CLOSE: q.get("pc"),
            ATTR_CHANGE: q.get("d"),
            ATTR_CHANGE_PERCENT: q.get("dp"),
        }

    @property
    def available(self) -> bool:
        """Mark unavailable if coordinator has no data for this symbol."""
        return (
            super().available
            and self.coordinator.data is not None
            and self._symbol in self.coordinator.data
            and bool(self._quote.get("c"))
        )

    @property
    def _quote(self) -> dict:
        if self.coordinator.data:
            return self.coordinator.data.get(self._symbol, {})
        return {}
