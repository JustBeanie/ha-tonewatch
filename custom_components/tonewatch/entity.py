"""Shared ToneWatch entity behavior and state projection."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ToneWatchCoordinator


class ToneWatchEntity(CoordinatorEntity[ToneWatchCoordinator]):
    """Base class for entities backed by the push coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ToneWatchCoordinator, kind: str, item_id: str) -> None:
        super().__init__(coordinator)
        self.item_id = item_id
        instance_id = coordinator.entry.data.get("instance_id", coordinator.entry.entry_id)
        instance_label = str(instance_id)
        self._attr_unique_id = f"{instance_id}_{kind}_{item_id}"
        self._attr_device_info = {
            "identifiers": {
                (
                    "tonewatch",
                    str(coordinator.entry.data.get("instance_id", coordinator.entry.entry_id)),
                )
            },
            "name": f"ToneWatch ({instance_label})",
            "manufacturer": "ToneWatch",
            "configuration_url": coordinator.base_url,
        }

    @property
    def available(self) -> bool:
        return bool(self.coordinator.last_update_success)

    @property
    def state_data(self) -> dict[str, Any]:
        return self.coordinator.latest_state

    def _toneset(self) -> dict[str, Any]:
        return cast(
            "dict[str, Any]",
            next(
                (
                    item
                    for item in self.state_data.get("tonesets", [])
                    if item.get("id") == self.item_id
                ),
                {},
            ),
        )

    def _event_data(self) -> dict[str, Any]:
        last_call = self.state_data.get("last_call", {})
        if last_call.get("toneset_id") == self.item_id:
            return cast("dict[str, Any]", last_call)
        for event in reversed(self.state_data.get("events", [])):
            if event.get("data", {}).get("toneset_id") == self.item_id:
                return cast("dict[str, Any]", event.get("data", {}))
        return cast("dict[str, Any]", {})

    def _recording_url(self, value: Any) -> str | None:
        if value in (None, ""):
            return None
        return f"{self.coordinator.base_url}/api/recordings/{value}"


def parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO timestamp from the WebSocket payload."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None
