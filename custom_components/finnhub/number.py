"""Number entities for Finnhub integration."""

import contextlib
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ALL_LEVELS,
    CONF_LEVELS,
    CONF_SYMBOLS,
    DEFAULT_HYSTERESIS,
    DOMAIN,
    MAX_HYSTERESIS,
    MIN_HYSTERESIS,
)
from .coordinator import FinnhubCoordinator
from .sensor import _ticker_device


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Finnhub number entities from a config entry."""
    coordinator: FinnhubCoordinator = hass.data[DOMAIN][entry.entry_id]
    symbols: list[str] = entry.data[CONF_SYMBOLS]
    levels: dict = entry.data.get(CONF_LEVELS, {})

    entities: list[NumberEntity] = []
    for symbol in symbols:
        symbol_levels = levels.get(symbol, {})
        for level_key in ALL_LEVELS:
            initial = symbol_levels.get(level_key, 0.0)
            entities.append(FinnhubLevelNumber(coordinator, symbol, level_key, initial))
        entities.append(FinnhubHysteresisNumber(coordinator, symbol))
    async_add_entities(entities)


class FinnhubLevelNumber(CoordinatorEntity[FinnhubCoordinator], NumberEntity, RestoreEntity):
    """A configurable price level per ticker."""

    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100000.0
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = "mdi:target"
    _attr_has_entity_name = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FinnhubCoordinator,
        symbol: str,
        level_key: str,
        initial_value: float,
    ) -> None:
        """Initialize the price level number entity."""
        super().__init__(coordinator)
        self._symbol = symbol.upper()
        self._level_key = level_key
        self._attr_unique_id = f"{DOMAIN}_{self._symbol.lower()}_{level_key}"
        self._attr_name = f"{self._symbol} {level_key.replace('_', ' ').title()}"
        self.entity_id = f"number.market_{self._symbol.lower()}_{level_key}"
        self._attr_native_value = initial_value
        self._attr_device_info = _ticker_device(self._symbol)

    async def async_added_to_hass(self) -> None:
        """Restore the last known value on startup."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            with contextlib.suppress(ValueError, TypeError):
                self._attr_native_value = float(last_state.state)

    async def async_set_native_value(self, value: float) -> None:
        """Set a new price level value from the UI."""
        self._attr_native_value = value
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Calculate distance from current price and enrich attributes."""
        current = self._current_price
        value = self._attr_native_value
        if not current or not value:
            return {"level": self._level_key, "symbol": self._symbol}
        distance = round(current - value, 2)
        distance_pct = round((current - value) / value * 100, 2)
        return {
            "level": self._level_key,
            "symbol": self._symbol,
            "current_price": current,
            "distance": distance,
            "distance_pct": distance_pct,
            "price_above_level": current > value,
        }

    @property
    def _current_price(self) -> float | None:
        """Helper to get the current price for this entity's symbol."""
        if not self.coordinator.data:
            return None
        quote = self.coordinator.data.get(self._symbol, {})
        return quote.get("c") or None


class FinnhubHysteresisNumber(CoordinatorEntity[FinnhubCoordinator], NumberEntity, RestoreEntity):
    """
    Hysteresis band per ticker.

    Price must retrace this many USD
    before a level can re-alert after being triggered.
    entity_id: number.market_spy_hysteresis
    """

    _attr_mode = NumberMode.BOX
    _attr_native_min_value = MIN_HYSTERESIS
    _attr_native_max_value = MAX_HYSTERESIS
    _attr_native_step = 0.25
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = "mdi:arrow-expand-horizontal"
    _attr_has_entity_name = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FinnhubCoordinator,
        symbol: str,
    ) -> None:
        """Initialize the hysteresis number entity."""
        super().__init__(coordinator)
        self._symbol = symbol.upper()
        self._attr_unique_id = f"{DOMAIN}_{self._symbol.lower()}_hysteresis"
        self._attr_name = f"{self._symbol} Hysteresis"
        self.entity_id = f"number.market_{self._symbol.lower()}_hysteresis"
        self._attr_native_value = DEFAULT_HYSTERESIS
        self._attr_device_info = _ticker_device(self._symbol)

    async def async_added_to_hass(self) -> None:
        """Restore the last known value on startup."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            with contextlib.suppress(ValueError, TypeError):
                self._attr_native_value = float(last_state.state)

    async def async_set_native_value(self, value: float) -> None:
        """Set a new hysteresis value from the UI."""
        self._attr_native_value = value
        self.async_write_ha_state()
