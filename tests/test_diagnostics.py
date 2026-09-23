"""Diagnostics and repair issue tests."""

from __future__ import annotations

import json
from typing import Any

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tonewatch import diagnostics, repairs
from custom_components.tonewatch.api import ToneWatchCoordinator
from custom_components.tonewatch.const import DOMAIN


async def test_diagnostics_redacts_all_secrets_and_includes_connection_state(hass: Any) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "tonewatch.local",
            "port": 8099,
            "api_token": "fixture-token",
            "password": "fixture-password",
            "live_secret": "fixture-live-secret",
        },
    )
    coordinator = ToneWatchCoordinator(hass, entry)
    coordinator.latest_state["tonesets"] = [{"id": "ems"}]
    coordinator.latest_state["sources"] = [{"id": "north"}]
    coordinator.async_set_update_error(RuntimeError("fixture-error"))
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    payload = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
    serialized = json.dumps(payload)
    assert "fixture-token" not in serialized
    assert "fixture-password" not in serialized
    assert "fixture-live-secret" not in serialized
    assert payload["connection_state"] == "disconnected"
    assert payload["tone_set_count"] == 1
    assert payload["source_count"] == 1


async def test_runtime_repairs_create_and_clear_without_diagnostics(
    hass: Any, monkeypatch: Any
) -> None:
    created: list[str] = []
    cleared: list[str] = []
    monkeypatch.setattr(
        repairs.issue_registry,
        "async_create_issue",
        lambda _hass, _domain, issue_id, **_kwargs: created.append(issue_id),
    )
    monkeypatch.setattr(
        repairs.issue_registry,
        "async_delete_issue",
        lambda _hass, _domain, issue_id: cleared.append(issue_id),
    )
    repairs.async_update_repairs(hass, app_version="0.5.0", disconnected_for=301)
    assert set(created) == {repairs.APP_VERSION_ISSUE, repairs.WEBSOCKET_ISSUE}
    repairs.async_update_repairs(hass, app_version="0.6.1", disconnected_for=0)
    assert set(cleared) == {repairs.APP_VERSION_ISSUE, repairs.WEBSOCKET_ISSUE}
