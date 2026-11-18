"""ToneWatch event entities."""

from __future__ import annotations

from typing import Any, cast

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import ToneWatchCoordinator
from .entity import ToneWatchEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry[dict[str, object]], async_add_entities: Any
) -> None:
    coordinator = cast("ToneWatchCoordinator", entry.runtime_data)
    known: set[str] = set()
    async_add_entities(
        [
            ToneWatchActivityEvent(coordinator, "tone_discovered"),
            ToneWatchActivityEvent(coordinator, "call_enriched"),
        ]
    )

    def add_new() -> None:
        ids = {
            str(item["id"])
            for item in coordinator.latest_state.get("tonesets", [])
            if isinstance(item, dict) and item.get("id")
        }
        new = ids - known
        known.update(new)
        if new:
            async_add_entities([ToneWatchEvent(coordinator, item_id) for item_id in sorted(new)])

    entry.async_on_unload(coordinator.async_add_listener(add_new))
    add_new()


class ToneWatchEvent(ToneWatchEntity, EventEntity):
    """One event entity per tone set."""

    def __init__(self, coordinator: ToneWatchCoordinator, item_id: str) -> None:
        super().__init__(coordinator, "event", item_id)
        self._attr_event_types = ["pre_alert", "recording_ready"]
        self._attr_translation_key = "tone_set_event"
        self._attr_translation_placeholders = {"name": self._toneset().get("name", item_id)}
        self._last_triggered: tuple[Any, Any, Any] | None = None

    def _handle_coordinator_update(self) -> None:
        data = self._event_data()
        event_type = self.coordinator.latest_state.get("last_event", {}).get("type")
        if event_type == "RecordingStored":
            data = self.coordinator.latest_state.get("recording_events", {}).get(self.item_id)
        else:
            data = self._event_data()
        if (
            data
            and (event_type == "RecordingStored" or str(data.get("toneset_id")) == self.item_id)
            and event_type in {"ToneDetected", "RecordingStored"}
            and (data.get("call_id"), event_type, data.get("recording_id")) != self._last_triggered
        ):
            self._last_triggered = (data.get("call_id"), event_type, data.get("recording_id"))
            attrs = {
                key: data.get(key) for key in ("call_id", "test", "drill", "source_id", "agency")
            }
            attrs["toneset_id"] = self.item_id
            attrs["recording_proxy_url"] = self._recording_proxy_url(data.get("recording_id"))
            attrs["recording_url"] = attrs["recording_proxy_url"]
            attrs["recording_id"] = data.get("recording_id")
            attrs["format"] = data.get("format")
            self._trigger_event(
                "recording_ready" if event_type == "RecordingStored" else "pre_alert", attrs
            )
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self._event_data()
        recording = (
            self.coordinator.latest_state.get("recording_events", {})
            .get(self.item_id, {})
            .get("recording_id")
        )
        proxy_url = self._recording_proxy_url(recording)
        return {
            "call_id": data.get("call_id"),
            "toneset_id": data.get("toneset_id"),
            "recording_url": proxy_url,
            "recording_proxy_url": proxy_url,
            "test": data.get("test", False),
            "drill": data.get("drill", False),
        }

    def _recording_proxy_url(self, value: Any) -> str | None:
        """Return the HA-authenticated recording proxy path when possible."""
        if value in (None, "") or not str(value).isdigit():
            return None
        return f"/api/tonewatch/media/{self.coordinator.entry.entry_id}/{value}"


class ToneWatchActivityEvent(ToneWatchEntity, EventEntity):
    """Expose discovery and CAD enrichment as distinct event entities."""

    def __init__(self, coordinator: ToneWatchCoordinator, event_name: str) -> None:
        super().__init__(coordinator, "activity", event_name)
        self.event_name = event_name
        self._attr_event_types = [event_name]
        self._attr_translation_key = event_name
        self._seen_event: tuple[Any, Any] | None = None

    def _handle_coordinator_update(self) -> None:
        event = self.coordinator.latest_state.get("last_event") or {}
        expected = {"tone_discovered": "tone_discovered", "call_enriched": "call_enriched"}
        if event.get("type") == expected[self.event_name]:
            data = event.get("data", {})
            marker = (
                data.get("cluster_id") or data.get("call_id"),
                data.get("observed_at") or data.get("matched_at"),
            )
            if marker != self._seen_event:
                self._seen_event = marker
                attrs = {
                    key: data.get(key)
                    for key in (
                        "call_id",
                        "source_id",
                        "cluster_id",
                        "count",
                        "feed_id",
                        "incident_id",
                        "incident",
                        "test",
                        "drill",
                    )
                    if key in data
                }
                candidate = data.get("candidate")
                if isinstance(candidate, dict):
                    attrs["frequencies"] = candidate.get("frequencies")
                    attrs["durations"] = candidate.get("durations")
                self._trigger_event(self.event_name, attrs)
        super()._handle_coordinator_update()
