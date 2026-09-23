"""ToneWatch call and feed-health binary sensors."""

from __future__ import annotations

from typing import Any, cast

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import ToneWatchCoordinator
from .entity import ToneWatchEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry[dict[str, object]], async_add_entities: Any
) -> None:
    coordinator = cast("ToneWatchCoordinator", entry.runtime_data)
    entities: list[BinarySensorEntity] = [CallActiveSensor(coordinator)]
    entities.extend(
        FeedHealthySensor(coordinator, item["id"], item.get("name", item["id"]))
        for item in coordinator.latest_state.get("sources", [])
    )
    async_add_entities(entities)


class CallActiveSensor(ToneWatchEntity, BinarySensorEntity):
    _attr_translation_key = "call_active"
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
        self._attr_translation_key = "feed_healthy"
        self._attr_translation_placeholders = {"name": name}

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.latest_state.get("health", {}).get(self.item_id)
        return value if isinstance(value, bool) else None
