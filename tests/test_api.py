"""WebSocket client tests with a fully mocked aiohttp session."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
    await coordinator.async_start()
    await coordinator.async_stop()
    assert coordinator._task is None


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
