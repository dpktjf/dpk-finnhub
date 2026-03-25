"""Switch platform for Finnhub per-ticker alert enable/disable."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SYMBOLS, DOMAIN
from .coordinator import FinnhubCoordinator
from .sensor import _ticker_device

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up per-ticker alert switches."""
    coordinator: FinnhubCoordinator = hass.data[DOMAIN][entry.entry_id]
    symbols: list[str] = entry.data[CONF_SYMBOLS]
    async_add_entities(FinnhubAlertSwitch(coordinator, symbol) for symbol in symbols)


class FinnhubAlertSwitch(CoordinatorEntity[FinnhubCoordinator], SwitchEntity, RestoreEntity):
    """
    Enable/disable price level alerts for a ticker.

    entity_id: switch.market_spy_alerts
    Default: on — alerts enabled.
    Persists across restarts via RestoreEntity.
    """

    _attr_icon = "mdi:bell"
    _attr_has_entity_name = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FinnhubCoordinator,
        symbol: str,
    ) -> None:
        """Initialize the switch with coordinator and symbol."""
        super().__init__(coordinator)
        self._symbol = symbol.upper()
        self._attr_unique_id = f"{DOMAIN}_{self._symbol.lower()}_alerts"
        self._attr_name = f"{self._symbol} Alerts"
        self.entity_id = f"switch.market_{self._symbol.lower()}_alerts"
        self._attr_is_on = True  # default enabled
        self._attr_device_info = _ticker_device(self._symbol)

    async def async_added_to_hass(self) -> None:
        """Restore last known state on HA restart."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == "on"

    async def async_turn_on(self, **kwargs: object) -> None:  # noqa: ARG002
        """Enable alerts for this ticker."""
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: object) -> None:  # noqa: ARG002
        """Disable alerts for this ticker."""
        self._attr_is_on = False
        self.async_write_ha_state()
