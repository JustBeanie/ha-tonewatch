"""ToneWatch event entities."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import ToneWatchCoordinator
from .entity import ToneWatchEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry[dict[str, object]], async_add_entities: Any
) -> None:
    coordinator: ToneWatchCoordinator = hass.data["tonewatch"][entry.entry_id]
    async_add_entities(
        [
            ToneWatchEvent(coordinator, item["id"])
            for item in coordinator.latest_state.get("tonesets", [])
        ]
    )


class ToneWatchEvent(ToneWatchEntity, EventEntity):
    """One event entity per tone set."""

    def __init__(self, coordinator: ToneWatchCoordinator, item_id: str) -> None:
        super().__init__(coordinator, "event", item_id)
        self._attr_event_types = ["pre_alert", "recording_ready"]
        self._attr_name = self._toneset().get("name", item_id)
        self._last_triggered: tuple[Any, Any] | None = None

    def _handle_coordinator_update(self) -> None:
        data = self._event_data()
        event_type = self.coordinator.latest_state.get("last_event", {}).get("type")
        if (
            data
            and data.get("toneset_id") == self.item_id
            and event_type in {"ToneDetected", "RecordingReady"}
            and (data.get("call_id"), event_type) != self._last_triggered
        ):
            self._last_triggered = (data.get("call_id"), event_type)
            attrs = {key: data.get(key) for key in ("call_id", "toneset_id", "test", "drill")}
            attrs["recording_url"] = self._recording_url(
                data.get("recording_id") or data.get("path")
            )
            self._trigger_event(
                "recording_ready" if event_type == "RecordingReady" else "pre_alert", attrs
            )
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self._event_data()
        return {
            "call_id": data.get("call_id"),
            "toneset_id": data.get("toneset_id"),
            "recording_url": self._recording_url(data.get("recording_id") or data.get("path")),
            "test": data.get("test", False),
            "drill": data.get("drill", False),
        }
