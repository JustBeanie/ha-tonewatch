"""ToneWatch tone-set test buttons."""

from __future__ import annotations

from typing import Any, cast

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .api import ToneWatchCoordinator
from .entity import ToneWatchEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry[dict[str, object]], async_add_entities: Any
) -> None:
    coordinator = cast("ToneWatchCoordinator", entry.runtime_data)
    async_add_entities(
        [
            ToneSetTestButton(coordinator, item["id"])
            for item in coordinator.latest_state.get("tonesets", [])
        ]
    )


class ToneSetTestButton(ToneWatchEntity, ButtonEntity):
    def __init__(self, coordinator: ToneWatchCoordinator, item_id: str) -> None:
        super().__init__(coordinator, "button", item_id)
        self._attr_translation_key = "tone_set_test"
        self._attr_translation_placeholders = {"name": self._toneset().get("name", item_id)}

    async def async_press(self) -> None:
        try:
            await self.coordinator.async_request("POST", f"/api/tonesets/{self.item_id}/test")
        except Exception as err:
            raise HomeAssistantError("Unable to test the ToneWatch tone set") from err
