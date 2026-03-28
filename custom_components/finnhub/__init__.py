"""Finnhub Stock Quotes integration."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import CONF_SYMBOLS, DOMAIN
from .coordinator import FinnhubCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NUMBER, Platform.SWITCH]
_ENTITY_SUFFIXES = (
    "_signal",
    "_lower_2",
    "_lower_1",
    "_upper_1",
    "_upper_2",
    "_hysteresis",
    "_alerts",
)


def _configured_symbols(entry: ConfigEntry) -> set[str]:
    """Return normalized configured symbols from options or data."""
    symbols = entry.options.get(CONF_SYMBOLS, entry.data.get(CONF_SYMBOLS, []))
    return {str(symbol).strip().lower() for symbol in symbols if str(symbol).strip()}


def _symbol_from_entity_id(entity_id: str) -> str | None:
    """Extract the tracked symbol from a Finnhub entity_id."""
    if not entity_id.startswith(("sensor.market_", "number.market_", "switch.market_")):
        return None

    _, object_id = entity_id.split(".", 1)
    if not object_id.startswith("market_"):
        return None

    tail = object_id[len("market_") :]

    # Order matters: check suffixed entities before base quote sensor.
    for suffix in _ENTITY_SUFFIXES:
        if tail.endswith(suffix):
            return tail[: -len(suffix)]

    # Base quote sensor: sensor.market_<symbol>
    return tail if entity_id.startswith("sensor.market_") else None


async def _async_remove_stale_symbol_entities_and_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Remove entities/devices for symbols no longer configured."""
    wanted_symbols = _configured_symbols(entry)
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    stale_entity_ids: list[str] = []
    affected_device_ids: set[str] = set()

    for reg_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        symbol = _symbol_from_entity_id(reg_entry.entity_id)
        if symbol is None:
            continue

        if symbol in wanted_symbols:
            continue

        stale_entity_ids.append(reg_entry.entity_id)
        if reg_entry.device_id is not None:
            affected_device_ids.add(reg_entry.device_id)

    if stale_entity_ids:
        _LOGGER.info(
            "Removing stale Finnhub entities for symbols no longer configured: %s",
            ", ".join(sorted(stale_entity_ids)),
        )

    for entity_id in stale_entity_ids:
        entity_registry.async_remove(entity_id)

    for device_id in affected_device_ids:
        remaining_entities = er.async_entries_for_device(
            entity_registry,
            device_id,
            include_disabled_entities=True,
        )

        # If anything is still attached to the device, leave it alone.
        if remaining_entities:
            continue

        device = device_registry.async_get(device_id)
        if device is None or entry.entry_id not in device.config_entries:
            continue

        _LOGGER.info(
            "Removing stale Finnhub device %s after last entity was removed",
            device_id,
        )
        device_registry.async_update_device(
            device_id=device_id,
            remove_config_entry_id=entry.entry_id,
        )


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: ConfigEntry,  # noqa: ARG001
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow HA UI to remove a Finnhub device when requested."""
    entity_registry = er.async_get(hass)

    for reg_entry in er.async_entries_for_device(
        entity_registry,
        device_entry.id,
        include_disabled_entities=True,
    ):
        entity_registry.async_remove(reg_entry.entity_id)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Finnhub from a config entry."""
    await _async_remove_stale_symbol_entities_and_devices(hass, entry)
    await _ensure_frontend_asset(hass)

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
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

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


async def _ensure_frontend_asset(hass: HomeAssistant) -> None:
    """Install/update the frontend card into /config/www."""
    integration_dir = Path(__file__).parent

    source = integration_dir / "www" / "finnhub-levels-card.js"
    target_dir = Path(hass.config.path("www"))
    target = target_dir / "finnhub-levels-card.js"

    await hass.async_add_executor_job(
        _copy_asset_if_needed,
        source,
        target_dir,
        target,
    )


def _copy_asset_if_needed(source: Path, target_dir: Path, target: Path) -> None:
    """Blocking filesystem logic executed in executor."""
    target_dir.mkdir(exist_ok=True)

    if not source.exists():
        _LOGGER.warning(
            "Finnhub: frontend asset missing: %s",
            source,
        )
        return

    if not target.exists() or source.stat().st_mtime > target.stat().st_mtime:
        shutil.copy2(source, target)

        _LOGGER.debug(
            "Finnhub: installed/updated frontend asset: %s",
            target,
        )
