"""ToneWatch entity and bus-event contract tests."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from homeassistant.const import Platform
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tonewatch import api
from custom_components.tonewatch.const import DOMAIN

TOKEN = "fixture-" + "api-token"


@pytest.fixture
def entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry-1",
        data={
            "host": "tonewatch.local",
            "port": 8099,
            "api_token": TOKEN,
            "instance_id": "instance-1",
        },
    )


@pytest.fixture
def initial_state() -> dict[str, Any]:
    return {
        "tonesets": [
            {"id": "ems", "name": "EMS", "enabled": True},
            {"id": "fire", "name": "Fire", "enabled": False},
        ],
        "sources": [{"id": "north", "name": "North"}, {"id": "south", "name": "South"}],
        "health": {"north": True, "south": False},
        "events": [],
        "last_event": None,
        "by_type": {},
    }


@pytest.fixture
def health_payload() -> dict[str, Any]:
    return {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "sources": [
            {
                "id": "north",
                "name": "North",
                "type": "rtlsdr",
                "realtime_factor": 1.0,
                "dropped_frames": 0,
                "late_frames": 0,
                "restarts": 0,
                "last_restart_at": None,
                "last_error": "stale error that must not determine health",
                "feed_health_history": [{"healthy": True, "at": "2026-01-01T00:00:00+00:00"}],
                "level": None,
                "squelch_open": None,
            },
            {
                "id": "south",
                "name": "South",
                "type": "rtlsdr",
                "realtime_factor": 1.0,
                "dropped_frames": 0,
                "late_frames": 0,
                "restarts": 0,
                "last_restart_at": None,
                "last_error": None,
                "feed_health_history": [],
                "level": None,
                "squelch_open": None,
            },
        ],
        "service": {"subscribers": []},
        "storage": {},
        "outputs": [],
        "cad_feeds": [],
    }


async def test_initial_fetch_uses_admin_health_and_history(
    hass: Any, entry: MockConfigEntry, health_payload: dict[str, Any]
) -> None:
    coordinator = api.ToneWatchCoordinator(hass, entry)
    calls: list[str] = []

    async def fake_json(_method: str, path: str, **_kwargs: Any) -> Any:
        calls.append(path)
        return [] if path == "/api/tonesets" else health_payload

    coordinator._async_api_json = fake_json
    await coordinator._async_initial_fetch()
    assert calls == ["/api/tonesets", "/api/admin/health"]
    assert coordinator.latest_state["health"] == {"north": True}


async def test_initial_fetch_failure_marks_coordinator_unavailable(
    hass: Any, entry: MockConfigEntry
) -> None:
    coordinator = api.ToneWatchCoordinator(hass, entry)

    async def fail(_method: str, _path: str, **_kwargs: Any) -> Any:
        raise RuntimeError

    coordinator._async_api_json = fail
    await coordinator.async_start()
    await hass.async_block_till_done()
    assert coordinator.last_update_success is False
    await coordinator.async_stop()


async def test_setup_creates_expected_entities_and_unloads(
    hass: Any,
    entry: MockConfigEntry,
    initial_state: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry.add_to_hass(hass)
    monkeypatch.setattr(
        api.ToneWatchCoordinator, "async_start", lambda self: _start(self, initial_state)
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert {item.unique_id for item in entities} == {
        "instance-1_event_ems",
        "instance-1_event_fire",
        "instance-1_last_call",
        "instance-1_call_active",
        "instance-1_feed_healthy_north",
        "instance-1_feed_healthy_south",
        "instance-1_switch_ems",
        "instance-1_switch_fire",
        "instance-1_button_ems",
        "instance-1_button_fire",
    }
    assert {item.domain for item in entities} == {
        platform.value
        for platform in Platform
        if platform
        in {
            Platform.EVENT,
            Platform.SENSOR,
            Platform.BINARY_SENSOR,
            Platform.SWITCH,
            Platform.BUTTON,
        }
    }
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not er.async_entries_for_config_entry(registry, entry.entry_id)


async def test_push_events_update_entities_and_fire_bus(
    hass: Any,
    entry: MockConfigEntry,
    initial_state: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry.add_to_hass(hass)
    coordinator = await _setup(hass, entry, initial_state, monkeypatch, api)
    received: list[Any] = []
    hass.bus.async_listen("tonewatch_detected", received.append)
    call_id = str(UUID("12345678-1234-5678-1234-567812345678"))
    await coordinator._handle_message(
        {
            "type": "ToneDetected",
            "data": {
                "call_id": call_id,
                "toneset_id": "ems",
                "source_id": "north",
                "detected_at": "2026-01-01T01:02:03+00:00",
                "test": False,
                "drill": True,
            },
        }
    )
    await hass.async_block_till_done()
    assert hass.states["event.ems"].attributes["call_id"] == call_id
    assert hass.states["event.ems"].state == "pre_alert"
    assert hass.states["binary_sensor.call_active"].state == "on"
    assert hass.states["sensor.last_call"].attributes["source_id"] == "north"
    assert len(received) == 1
    assert received[0].data["call_id"] == call_id
    await coordinator._handle_message(
        {
            "type": "RecordingReady",
            "data": {
                "call_id": call_id,
                "path": "recordings/call.mp3",
                "format": "mp3",
                "test": False,
                "drill": True,
            },
        }
    )
    await hass.async_block_till_done()
    assert hass.states["event.ems"].state == "recording_ready"
    assert (
        hass.states["event.ems"].attributes["recording_url"]
        == "http://tonewatch.local:8099/api/recordings/call.mp3"
    )


async def test_feed_switch_button_disconnect_and_secret_redaction(
    hass: Any,
    entry: MockConfigEntry,
    initial_state: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry.add_to_hass(hass)
    coordinator = await _setup(hass, entry, initial_state, monkeypatch, api)
    await coordinator._handle_message(
        {"type": "FeedHealthChanged", "data": {"source_id": "north", "healthy": False}}
    )
    await hass.async_block_till_done()
    assert hass.states["binary_sensor.feed_healthy_north"].state == "off"
    assert hass.states["binary_sensor.feed_healthy_south"].state == "off"
    coordinator.async_set_update_error(RuntimeError("disconnected"))
    await hass.async_block_till_done()
    assert hass.states["event.ems"].state == "unavailable"
    assert TOKEN not in str(hass.states.async_all())


async def _start(coordinator: Any, state: dict[str, Any]) -> None:
    coordinator.latest_state = state
    coordinator.async_set_updated_data(state)


async def _setup(
    hass: Any, entry: MockConfigEntry, state: dict[str, Any], monkeypatch: Any, api: Any
) -> Any:
    monkeypatch.setattr(api.ToneWatchCoordinator, "async_start", lambda self: _start(self, state))
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.data[DOMAIN][entry.entry_id]
