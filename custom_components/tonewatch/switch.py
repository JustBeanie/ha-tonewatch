"""ToneWatch tone-set switches."""

from __future__ import annotations

from typing import Any, cast

from homeassistant.components.switch import SwitchEntity
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
            ToneSetSwitch(coordinator, item["id"])
            for item in coordinator.latest_state.get("tonesets", [])
        ]
    )


class ToneSetSwitch(ToneWatchEntity, SwitchEntity):
    def __init__(self, coordinator: ToneWatchCoordinator, item_id: str) -> None:
        super().__init__(coordinator, "switch", item_id)
        self._attr_translation_key = "tone_set"
        self._attr_translation_placeholders = {"name": self._toneset().get("name", item_id)}
        self._optimistic: bool | None = None

    @property
    def is_on(self) -> bool:
        return (
            self._optimistic
            if self._optimistic is not None
            else bool(self._toneset().get("enabled", False))
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set_enabled(False)

    async def _async_set_enabled(self, enabled: bool) -> None:
        previous = bool(self._toneset().get("enabled", False))
        self._optimistic = enabled
        self.async_write_ha_state()
        item = dict(self._toneset())
        item["enabled"] = enabled
        try:
            await self.coordinator.async_request("PUT", f"/api/tonesets/{self.item_id}", json=item)
        except Exception as err:
            self._optimistic = previous
            self.async_write_ha_state()
            raise HomeAssistantError("Unable to update the ToneWatch tone set") from err
        self._optimistic = None
        self.coordinator.latest_state["tonesets"] = [
            item if value.get("id") == self.item_id else value
            for value in self.coordinator.latest_state.get("tonesets", [])
        ]
        self.async_write_ha_state()
