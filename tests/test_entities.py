"""ToneWatch entity and bus-event contract tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_RESTORED, STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistantError
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from custom_components.tonewatch import api
from custom_components.tonewatch.binary_sensor import CadFeedConnectedSensor, SquelchOpenSensor
from custom_components.tonewatch.const import DOMAIN
from custom_components.tonewatch.sensor import AlertFailuresSensor, CadActiveIncidentsSensor

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


async def test_diagnostic_entities_match_numeric_upstream_ids(
    hass: Any, entry: MockConfigEntry
) -> None:
    coordinator = api.ToneWatchCoordinator(hass, entry)
    coordinator.latest_state.update(
        {
            "sources": [{"id": 7, "squelch_open": True}],
            "cad_feeds": [{"id": 8, "connected": True, "active_incidents": 2}],
            "outputs": [{"id": 9, "consecutive_failures": 1}],
        }
    )
    assert SquelchOpenSensor(coordinator, "7", "Source").is_on is True
    assert CadFeedConnectedSensor(coordinator, "8", "CAD").is_on is True
    assert CadActiveIncidentsSensor(coordinator, "8", "CAD").native_value == 2
    assert AlertFailuresSensor(coordinator, "9", "Output").native_value == 1


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
        return [] if path in {"/api/tonesets", "/api/sources"} else health_payload

    coordinator._async_api_json = fake_json
    await coordinator._async_initial_fetch()
    assert calls == ["/api/tonesets", "/api/sources", "/api/admin/health"]
    assert coordinator.latest_state["health"] == {"north": True}


async def test_initial_fetch_failure_defers_entry_setup(hass: Any, entry: MockConfigEntry) -> None:
    coordinator = api.ToneWatchCoordinator(hass, entry)

    async def fail(_method: str, _path: str, **_kwargs: Any) -> Any:
        raise RuntimeError

    coordinator._async_api_json = fail
    with pytest.raises(ConfigEntryNotReady):
        await coordinator.async_start()
    assert coordinator._task is None


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
    entity_ids = [item.entity_id for item in entities]
    assert {item.unique_id for item in entities} == {
        "instance-1_event_ems",
        "instance-1_event_fire",
        "instance-1_activity_tone_discovered",
        "instance-1_activity_call_enriched",
        "instance-1_last_call",
        "instance-1_storage_forecast",
        "instance-1_call_active",
        "instance-1_feed_healthy_north",
        "instance-1_feed_healthy_south",
        "instance-1_squelch_open_north",
        "instance-1_squelch_open_south",
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
    assert entry.state is ConfigEntryState.NOT_LOADED
    leftover = [entity_id for entity_id in entity_ids if hass.states.get(entity_id)]
    assert leftover == [item.entity_id for item in entities if item.disabled_by is None]
    assert all(hass.states.get(entity_id).state == STATE_UNAVAILABLE for entity_id in leftover)
    assert all(hass.states.get(entity_id).attributes[ATTR_RESTORED] for entity_id in leftover)
    await hass.config_entries.async_remove(entry.entry_id)
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
    registry = er.async_get(hass)
    event_state = _state_for(hass, registry, "event", "instance-1_event_ems")
    call_active_state = _state_for(hass, registry, "binary_sensor", "instance-1_call_active")
    last_call_state = _state_for(hass, registry, "sensor", "instance-1_last_call")
    assert event_state.attributes["call_id"] == call_id
    assert event_state.attributes["event_type"] == "pre_alert"
    datetime.fromisoformat(event_state.state)
    assert call_active_state.state == "on"
    assert last_call_state.attributes["source_id"] == "north"
    assert len(received) == 1
    assert received[0].data["call_id"] == call_id

    async def detail(_method: str, _path: str, **_kwargs: Any) -> Any:
        return {
            "source_id": "north",
            "tone_sets": [{"toneset_id": "ems", "agency": {"name": "EMS"}}],
            "recordings": [{"id": 42, "format": "mp3"}],
        }

    coordinator._async_api_json = detail
    await coordinator._handle_message(
        {
            "type": "RecordingStored",
            "data": {"call_id": call_id, "recording_id": 42, "format": "mp3", "drill": True},
        }
    )
    await hass.async_block_till_done()
    event_state = _state_for(hass, registry, "event", "instance-1_event_ems")
    assert event_state.attributes["event_type"] == "recording_ready"
    datetime.fromisoformat(event_state.state)
    assert event_state.attributes["recording_proxy_url"] == "/api/tonewatch/media/entry-1/42"
    assert event_state.attributes["agency"] == {"name": "EMS"}


async def test_switch_write_reverts_and_button_posts(
    hass: Any,
    entry: MockConfigEntry,
    initial_state: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry.add_to_hass(hass)
    coordinator = await _setup(hass, entry, initial_state, monkeypatch, api)
    calls: list[tuple[str, str, dict[str, Any] | None]] = []
    fail_write = True
    fail_button = False

    async def fake_request(method: str, path: str, *, json: dict[str, Any] | None = None) -> Any:
        calls.append((method, path, json))
        if fail_write or (path.endswith("/test") and fail_button):
            raise RuntimeError
        return {"ok": True}

    coordinator.async_request = fake_request
    registry = er.async_get(hass)
    switch_id = registry.async_get_entity_id("switch", DOMAIN, "instance-1_switch_ems")
    button_id = registry.async_get_entity_id("button", DOMAIN, "instance-1_button_ems")
    assert switch_id is not None
    assert button_id is not None
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": switch_id}, blocking=True
        )
    assert _state_for(hass, registry, "switch", "instance-1_switch_ems").state == "on"
    fail_write = False
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch_id}, blocking=True)
    fail_button = True
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("button", "press", {"entity_id": button_id}, blocking=True)
    fail_button = False
    await hass.services.async_call("button", "press", {"entity_id": button_id}, blocking=True)
    assert calls[0][:2] == ("PUT", "/api/tonesets/ems")
    assert calls[1][:2] == ("PUT", "/api/tonesets/ems")
    assert calls[2][:2] == ("POST", "/api/tonesets/ems/test")


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
    registry = er.async_get(hass)
    north_state = _state_for(hass, registry, "binary_sensor", "instance-1_feed_healthy_north")
    south_state = _state_for(hass, registry, "binary_sensor", "instance-1_feed_healthy_south")
    assert north_state.state == "off"
    assert south_state.state == "off"
    coordinator.async_set_update_error(RuntimeError("disconnected"))
    await hass.async_block_till_done()
    event_state = _state_for(hass, registry, "event", "instance-1_event_ems")
    assert event_state.state == "unavailable"
    for domain, unique_id in (
        ("sensor", "instance-1_last_call"),
        ("binary_sensor", "instance-1_call_active"),
        ("switch", "instance-1_switch_ems"),
        ("button", "instance-1_button_ems"),
    ):
        assert _state_for(hass, registry, domain, unique_id).state == STATE_UNAVAILABLE
    assert TOKEN not in str(hass.states.async_all())


async def test_new_health_and_activity_entities(
    hass: Any,
    entry: MockConfigEntry,
    initial_state: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial_state["cad_feeds"] = [
        {"id": "dispatch", "name": "Dispatch", "connected": True, "active_incidents": 2}
    ]
    initial_state["outputs"] = [{"id": "phone", "name": "Phone", "consecutive_failures": 1}]
    initial_state["storage"] = {"retention_forecast": {"days_until_full": 45.5}}
    entry.add_to_hass(hass)
    coordinator = await _setup(hass, entry, initial_state, monkeypatch, api)
    registry = er.async_get(hass)
    assert (
        _state_for(hass, registry, "binary_sensor", "instance-1_cad_connected_dispatch").state
        == "on"
    )
    assert _state_for(hass, registry, "sensor", "instance-1_cad_active_dispatch").state == "2"
    assert _state_for(hass, registry, "sensor", "instance-1_alert_failures_phone").state == "1"
    await coordinator._handle_message(
        {
            "type": "tone_discovered",
            "data": {"cluster_id": 7, "observed_at": "2026-11-18T00:00:00Z", "count": 3},
        }
    )
    await hass.async_block_till_done()
    discovered = _state_for(hass, registry, "event", "instance-1_activity_tone_discovered")
    assert discovered.attributes["event_type"] == "tone_discovered"
    assert discovered.attributes["cluster_id"] == 7
    await coordinator._handle_message(
        {
            "type": "call_enriched",
            "data": {
                "call_id": "call-1",
                "matched_at": "2026-11-18T00:01:00Z",
                "incident": {"type": "Fire"},
            },
        }
    )
    await hass.async_block_till_done()
    enriched = _state_for(hass, registry, "event", "instance-1_activity_call_enriched")
    assert enriched.attributes["incident"] == {"type": "Fire"}


async def test_config_change_adds_new_tone_set_and_feed(
    hass: Any,
    entry: MockConfigEntry,
    initial_state: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry.add_to_hass(hass)
    coordinator = await _setup(hass, entry, initial_state, monkeypatch, api)

    async def fake_json(_method: str, path: str, **_kwargs: Any) -> Any:
        if path == "/api/tonesets":
            return [*initial_state["tonesets"], {"id": "police", "name": "Police", "enabled": True}]
        if path == "/api/sources":
            return []
        return {"sources": [*initial_state["sources"], {"id": "west", "name": "West"}]}

    coordinator._async_api_json = fake_json
    await coordinator._async_refresh_config()
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    assert _state_for(hass, registry, "event", "instance-1_event_police")
    assert _state_for(hass, registry, "switch", "instance-1_switch_police")
    assert _state_for(hass, registry, "button", "instance-1_button_police")
    assert _state_for(hass, registry, "binary_sensor", "instance-1_feed_healthy_west")


async def _start(coordinator: Any, state: dict[str, Any]) -> None:
    coordinator.latest_state = state
    coordinator.async_set_updated_data(state)


def _state_for(hass: Any, registry: Any, domain: str, unique_id: str) -> Any:
    entity_id = registry.async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    return state


async def _setup(
    hass: Any, entry: MockConfigEntry, state: dict[str, Any], monkeypatch: Any, api: Any
) -> Any:
    monkeypatch.setattr(api.ToneWatchCoordinator, "async_start", lambda self: _start(self, state))
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.data[DOMAIN][entry.entry_id]
