"""ToneWatch call and feed-health binary sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import ToneWatchCoordinator
from .entity import ToneWatchEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry[dict[str, object]], async_add_entities: Any
) -> None:
    coordinator: ToneWatchCoordinator = hass.data["tonewatch"][entry.entry_id]
    entities: list[BinarySensorEntity] = [CallActiveSensor(coordinator)]
    entities.extend(
        FeedHealthySensor(coordinator, item["id"], item.get("name", item["id"]))
        for item in coordinator.latest_state.get("sources", [])
    )
    async_add_entities(entities)


class CallActiveSensor(ToneWatchEntity, BinarySensorEntity):
    _attr_name = "Call active"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: ToneWatchCoordinator) -> None:
        super().__init__(coordinator, "call_active", "")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.latest_state.get("call_active", False))


class FeedHealthySensor(ToneWatchEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: ToneWatchCoordinator, item_id: str, name: str) -> None:
        super().__init__(coordinator, "feed_healthy", item_id)
        self._attr_name = f"{name} feed healthy"

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.latest_state.get("health", {}).get(self.item_id)
        return value if isinstance(value, bool) else None
