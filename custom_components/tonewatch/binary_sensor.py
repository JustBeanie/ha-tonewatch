"""ToneWatch call and feed-health binary sensors."""

from __future__ import annotations

from typing import Any, cast

# BinarySensorDeviceClass moved to binary_sensor.const in 2026.x but is still re-exported here;
# importing from .const would break the 2026.2 minimum.
from homeassistant.components.binary_sensor import (  # type: ignore[attr-defined,unused-ignore]
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from .api import ToneWatchCoordinator
from .entity import ToneWatchEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry[dict[str, object]], async_add_entities: Any
) -> None:
    coordinator = cast("ToneWatchCoordinator", entry.runtime_data)
    async_add_entities([CallActiveSensor(coordinator)])
    known: set[tuple[str, str]] = set()

    def add_new() -> None:
        entities: list[BinarySensorEntity] = []
        for item in coordinator.latest_state.get("sources", []):
            if not isinstance(item, dict) or not item.get("id"):
                continue
            item_id = str(item["id"])
            name = str(item.get("name", item_id))
            for kind, factory in (
                ("feed_healthy", FeedHealthySensor),
                ("squelch_open", SquelchOpenSensor),
            ):
                if (kind, item_id) not in known:
                    known.add((kind, item_id))
                    entities.append(factory(coordinator, item_id, name))
        for item in coordinator.latest_state.get("cad_feeds", []):
            if not isinstance(item, dict) or not item.get("id"):
                continue
            item_id = str(item["id"])
            if ("cad_connected", item_id) not in known:
                known.add(("cad_connected", item_id))
                entities.append(
                    CadFeedConnectedSensor(coordinator, item_id, str(item.get("name", item_id)))
                )
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(coordinator.async_add_listener(add_new))
    add_new()


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


class SquelchOpenSensor(ToneWatchEntity, BinarySensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: ToneWatchCoordinator, item_id: str, name: str) -> None:
        super().__init__(coordinator, "squelch_open", item_id)
        self._attr_translation_key = "squelch_open"
        self._attr_translation_placeholders = {"name": name}

    @property
    def is_on(self) -> bool | None:
        source: dict[str, Any] = next(
            (
                item
                for item in self.state_data.get("sources", [])
                if str(item.get("id")) == self.item_id
            ),
            {},
        )
        value = source.get("squelch_open")
        return value if isinstance(value, bool) else None


class CadFeedConnectedSensor(ToneWatchEntity, BinarySensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: ToneWatchCoordinator, item_id: str, name: str) -> None:
        super().__init__(coordinator, "cad_connected", item_id)
        self._attr_translation_key = "cad_connected"
        self._attr_translation_placeholders = {"name": name}

    @property
    def is_on(self) -> bool | None:
        feed: dict[str, Any] = next(
            (
                item
                for item in self.state_data.get("cad_feeds", [])
                if str(item.get("id")) == self.item_id
            ),
            {},
        )
        value = feed.get("connected")
        return value if isinstance(value, bool) else None
