"""ToneWatch Home Assistant integration."""

from __future__ import annotations

from typing import Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import ToneWatchCoordinator
from .const import DOMAIN
from .const import PLATFORMS as PLATFORM_NAMES

PLATFORMS: list[Platform] = [Platform(value) for value in PLATFORM_NAMES]

type ToneWatchConfigEntry = ConfigEntry[dict[str, object]]


async def async_setup(hass: HomeAssistant, _config: dict[str, object]) -> bool:
    """Set up the integration domain."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ToneWatchConfigEntry) -> bool:
    """Set up ToneWatch from a config entry."""
    coordinator = ToneWatchCoordinator(hass, entry)
    entry.runtime_data = cast("Any", coordinator)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await coordinator.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ToneWatchConfigEntry) -> bool:
    """Unload a ToneWatch config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unloaded:
        return False
    coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if coordinator is not None:
        await coordinator.async_stop()
    return True
