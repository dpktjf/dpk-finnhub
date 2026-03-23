"""Finnhub Stock Quotes integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.const import Platform

from .const import DOMAIN
from .coordinator import FinnhubCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Finnhub from a config entry."""
    coordinator = FinnhubCoordinator(hass, entry)

    # Schedule the first fetch in the background so HA startup is not
    # blocked. Sensors will show unavailable briefly until the first
    # successful update completes.
    entry.async_create_background_task(
        hass,
        coordinator.async_refresh(),
        name="finnhub_initial_fetch",
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for options/data updates so live edits take effect without restart
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry updates (options flow saves)."""
    coordinator: FinnhubCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.update_config(entry)

    # Reload platform so sensor entities are added/removed as needed
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
