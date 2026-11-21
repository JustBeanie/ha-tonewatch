"""WebSocket client tests with a fully mocked aiohttp session."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from pytest_homeassistant.common import MockConfigEntry

from custom_components.tonewatch import api
from custom_components.tonewatch.const import DOMAIN


class FakeWebSocket:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self.messages = messages
        self.sent: list[dict[str, object]] = []

    async def send_json(self, value: dict[str, object]) -> None:
        self.sent.append(value)

    def __aiter__(self) -> FakeWebSocket:
        return self

    async def __anext__(self) -> aiohttp.WSMessage:
        if self.messages:
            value = self.messages.pop(0)
            return aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, str(value).replace("'", '"'), None)
        raise aiohttp.ClientConnectionError("disconnected")


class FakeSocketContext:
    def __init__(self, websocket: FakeWebSocket) -> None:
        self.websocket = websocket

    async def __aenter__(self) -> FakeWebSocket:
        return self.websocket

    async def __aexit__(self, *_args: object) -> None:
        return None


class FakeSession:
    def __init__(self) -> None:
        self.websockets: list[FakeWebSocket] = []
        self.calls: list[tuple[str, dict[str, object]]] = []

    def ws_connect(self, url: str, **kwargs: object) -> FakeSocketContext:
        self.calls.append((url, kwargs))
        websocket = FakeWebSocket(
            [{"type": "ping", "data": {}}, {"type": "ToneDetected", "data": {"id": 1}}]
        )
        self.websockets.append(websocket)
        return FakeSocketContext(websocket)


async def test_websocket_auth_event_update_and_reconnect(hass: Any, monkeypatch: Any) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "tonewatch.local", "port": 8099, "api_token": "secret"},
    )
    session = FakeSession()
    sleeps: list[float] = []
    coordinator: api.ToneWatchCoordinator | None = None

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        assert coordinator is not None
        if len(sleeps) == 3:
            coordinator._stopped.set()

    monkeypatch.setattr(api, "async_get_clientsession", lambda _hass: session)
    coordinator = api.ToneWatchCoordinator(hass, entry, sleep=fake_sleep, random_fn=lambda: 0)

    async def initial_fetch() -> None:
        return None

    coordinator._async_initial_fetch = initial_fetch
    await coordinator.async_start()
    assert coordinator._task is not None
    await coordinator._task
    assert session.calls[0] == (
        "ws://tonewatch.local:8099/api/ws",
        {"headers": {"Authorization": "Bearer secret"}},
    )
    assert session.websockets[0].sent[0] == {"type": "subscribe", "topics": ["events"]}
    assert session.websockets[0].sent[1] == {"type": "pong"}
    assert coordinator.data is not None
    assert coordinator.data["last_event"] == {"type": "ToneDetected", "data": {"id": 1}}
    assert sleeps == [0.5, 1.0, 2.0]
    await coordinator.async_stop()


async def test_clean_unload_cancels_pending_connection(hass: Any, monkeypatch: Any) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "tonewatch.local", "port": 8099, "api_token": "secret"},
    )

    async def wait_forever(_delay: float) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(api, "async_get_clientsession", lambda _hass: FakeSession())
    coordinator = api.ToneWatchCoordinator(hass, entry, sleep=wait_forever)

    async def initial_fetch() -> None:
        return None

    coordinator._async_initial_fetch = initial_fetch
    await coordinator.async_start()
    await coordinator.async_stop()
    assert coordinator._task is None


async def test_stored_recording_resolves_all_tone_sets(hass: Any) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={"host": "tonewatch.local", "port": 8099, "api_token": "secret"}
    )
    coordinator = api.ToneWatchCoordinator(hass, entry)
    paths: list[str] = []

    async def detail(_method: str, path: str, **_kwargs: Any) -> Any:
        paths.append(path)
        return {
            "source_id": "north",
            "tone_sets": [
                {"toneset_id": "fire", "agency": {"name": "Fire"}},
                {"toneset_id": "ems", "agency": {"name": "EMS"}},
            ],
            "recordings": [{"id": 88, "format": "ogg"}],
        }

    coordinator._async_api_json = detail
    await coordinator._handle_message(
        {
            "type": "RecordingStored",
            "data": {"call_id": "call-1", "recording_id": 88, "format": "ogg"},
        }
    )
    assert paths == ["/api/calls/call-1"]
    assert set(coordinator.latest_state["recording_events"]) == {"fire", "ems"}
    assert coordinator.latest_state["recording_events"]["fire"]["recording_id"] == 88
    assert coordinator.latest_state["recording_events"]["ems"]["agency"] == {"name": "EMS"}


async def test_uncommitted_recording_does_not_publish_playable_event(hass: Any) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={"host": "tonewatch.local", "port": 8099, "api_token": "secret"}
    )
    coordinator = api.ToneWatchCoordinator(hass, entry)
    await coordinator._handle_message(
        {
            "type": "RecordingReady",
            "data": {"call_id": "call-1", "path": "private/call.mp3"},
        }
    )
    assert coordinator.latest_state["recording_events"] == {}


async def test_periodic_health_refresh_updates_diagnostics_and_version(hass: Any) -> None:
    """Operational state must not freeze after the initial API fetch."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={"host": "tonewatch.local", "port": 8099, "api_token": "secret"}
    )
    intervals: list[float] = []
    coordinator: api.ToneWatchCoordinator

    async def sleep(delay: float) -> None:
        intervals.append(delay)
        if len(intervals) > 1:
            coordinator._stopped.set()

    coordinator = api.ToneWatchCoordinator(hass, entry, health_sleep=sleep)
    coordinator.latest_state["health"] = {"north": False}

    async def health(_method: str, _path: str, **_kwargs: Any) -> Any:
        return {
            "build": {"version": "0.6.3"},
            "sources": [
                {"id": "north", "feed_health_history": [{"healthy": True}]},
                {"id": "south", "feed_health_history": []},
            ],
            "cad_feeds": [{"id": 2, "connected": True}],
            "outputs": [],
            "storage": {"days_remaining": 12},
        }

    coordinator._async_api_json = health
    await coordinator._poll_health()
    assert intervals == [60, 60]
    assert coordinator.latest_state["health"] == {"north": True}
    assert coordinator.latest_state["storage"] == {"days_remaining": 12}
    assert coordinator.latest_state["cad_feeds"][0]["connected"] is True
    assert coordinator.app_version == "0.6.3"


async def test_stored_recording_rejects_missing_detail(hass: Any) -> None:
    """An unavailable detail row must never produce a broken playback event."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={"host": "tonewatch.local", "port": 8099, "api_token": "secret"}
    )
    coordinator = api.ToneWatchCoordinator(hass, entry)

    async def missing(_method: str, _path: str, **_kwargs: Any) -> Any:
        return {"recordings": [], "tone_sets": [{"toneset_id": "fire"}]}

    coordinator._async_api_json = missing
    await coordinator._handle_message(
        {"type": "RecordingStored", "data": {"call_id": "call-1", "recording_id": 7}}
    )
    assert coordinator.latest_state["recording_events"] == {}


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (aiohttp.ClientConnectionError("offline"), ConfigEntryNotReady),
        (
            aiohttp.ClientResponseError(None, (), status=401),
            ConfigEntryAuthFailed,
        ),
    ],
)
async def test_initial_fetch_failure_has_no_orphan_tasks(
    hass: Any, error: Exception, expected: type[Exception]
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={"host": "tonewatch.local", "port": 8099, "api_token": "secret"}
    )
    coordinator = api.ToneWatchCoordinator(hass, entry)

    async def fail() -> None:
        raise error

    coordinator._async_initial_fetch = fail
    with pytest.raises(expected):
        await coordinator.async_start()
    assert coordinator._task is None
    assert coordinator._health_task is None


async def test_disconnect_and_reconnect_are_logged_once(hass: Any, caplog: Any) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "tonewatch.local", "port": 8099, "api_token": "secret"},
    )
    coordinator = api.ToneWatchCoordinator(hass, entry)
    caplog.set_level(logging.INFO, logger="custom_components.tonewatch.api")
    coordinator._mark_connected()
    coordinator._mark_disconnected(RuntimeError("offline"))
    coordinator._mark_disconnected(RuntimeError("still offline"))
    coordinator._mark_connected()
    coordinator._mark_connected()
    assert caplog.messages.count("ToneWatch WebSocket connected") == 2
    assert (
        sum(message.startswith("ToneWatch WebSocket disconnected") for message in caplog.messages)
        == 1
    )
