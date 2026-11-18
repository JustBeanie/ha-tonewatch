"""ToneWatch last-call sensor."""

from __future__ import annotations

from typing import Any, cast

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from .api import ToneWatchCoordinator
from .entity import ToneWatchEntity, parse_datetime

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry[dict[str, object]], async_add_entities: Any
) -> None:
    coordinator = cast("ToneWatchCoordinator", entry.runtime_data)
    async_add_entities([LastCallSensor(coordinator), StorageForecastSensor(coordinator)])
    known: set[tuple[str, str]] = set()

    def add_new() -> None:
        entities: list[SensorEntity] = []
        for key, kind, factory in (
            ("cad_feeds", "cad_active", CadActiveIncidentsSensor),
            ("outputs", "alert_failures", AlertFailuresSensor),
        ):
            for item in coordinator.latest_state.get(key, []):
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                item_id = str(item["id"])
                if (kind, item_id) not in known:
                    known.add((kind, item_id))
                    entities.append(factory(coordinator, item_id, str(item.get("name", item_id))))
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(coordinator.async_add_listener(add_new))
    add_new()


class LastCallSensor(ToneWatchEntity, SensorEntity):
    _attr_translation_key = "last_call"
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


class StorageForecastSensor(ToneWatchEntity, SensorEntity):
    _attr_translation_key = "storage_forecast"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = "d"

    def __init__(self, coordinator: ToneWatchCoordinator) -> None:
        super().__init__(coordinator, "storage_forecast", "")

    @property
    def native_value(self) -> float | None:
        storage = self.state_data.get("storage", {})
        value = storage.get("retention_forecast", {}).get("days_until_full")
        return float(value) if isinstance(value, (int, float)) else None


class CadActiveIncidentsSensor(ToneWatchEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ToneWatchCoordinator, item_id: str, name: str) -> None:
        super().__init__(coordinator, "cad_active", item_id)
        self._attr_translation_key = "cad_active"
        self._attr_translation_placeholders = {"name": name}

    @property
    def native_value(self) -> int | None:
        feed: dict[str, Any] = next(
            (
                item
                for item in self.state_data.get("cad_feeds", [])
                if str(item.get("id")) == self.item_id
            ),
            {},
        )
        value = feed.get("active_incidents")
        return value if isinstance(value, int) else None


class AlertFailuresSensor(ToneWatchEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ToneWatchCoordinator, item_id: str, name: str) -> None:
        super().__init__(coordinator, "alert_failures", item_id)
        self._attr_translation_key = "alert_failures"
        self._attr_translation_placeholders = {"name": name}

    @property
    def native_value(self) -> int | None:
        output: dict[str, Any] = next(
            (
                item
                for item in self.state_data.get("outputs", [])
                if str(item.get("id")) == self.item_id
            ),
            {},
        )
        value = output.get("consecutive_failures")
        return value if isinstance(value, int) else None
