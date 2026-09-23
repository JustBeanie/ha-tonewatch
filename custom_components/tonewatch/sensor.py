"""ToneWatch last-call sensor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import ToneWatchCoordinator
from .entity import ToneWatchEntity, parse_datetime


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry[dict[str, object]], async_add_entities: Any
) -> None:
    async_add_entities([LastCallSensor(hass.data["tonewatch"][entry.entry_id])])


class LastCallSensor(ToneWatchEntity, SensorEntity):
    _attr_name = "Last call"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: ToneWatchCoordinator) -> None:
        super().__init__(coordinator, "last_call", "")

    @property
    def native_value(self) -> Any:
        return parse_datetime(self.coordinator.latest_state.get("last_call", {}).get("detected_at"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        value = self.coordinator.latest_state.get("last_call", {})
        return {key: value.get(key) for key in ("toneset_names", "source_id", "call_id")}
