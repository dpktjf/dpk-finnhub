"""Finnhub Stock Quotes integration."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.const import Platform

from .const import DOMAIN
from .coordinator import FinnhubCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NUMBER, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Finnhub from a config entry."""
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

        _LOGGER.info(
            "Finnhub: installed/updated frontend asset: %s",
            target,
        )
