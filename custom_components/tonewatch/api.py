"""ToneWatch WebSocket client and push data coordinator."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    BASE_BACKOFF,
    DOMAIN,
    EVENT_TOPICS,
    MAX_BACKOFF,
    WS_PATH,
)

_LOGGER = logging.getLogger(__name__)

type Sleep = Callable[[float], Awaitable[None]]
type Random = Callable[[], float]
type EventData = dict[str, Any]


def _base_url(host: str, port: int) -> str:
    """Return the HTTP origin used by the API client."""
    formatted_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"http://{formatted_host}:{port}"


def _websocket_url(base_url: str) -> str:
    """Convert an HTTP origin into the ToneWatch WebSocket endpoint."""
    parsed = urlsplit(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunsplit((scheme, parsed.netloc, WS_PATH, "", ""))


class ToneWatchCoordinator(DataUpdateCoordinator[EventData]):
    """Maintain the latest event state from ToneWatch's push stream."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry[dict[str, object]],
        *,
        sleep: Sleep = asyncio.sleep,
        random_fn: Random = random.random,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_method=self._async_no_poll,
            config_entry=entry,
        )
        self.entry = entry
        self._sleep = sleep
        self._random = random_fn
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self.latest_state: EventData = {"events": [], "last_event": None, "by_type": {}}

    async def _async_api_json(
        self, method: str, path: str, *, json: dict[str, Any] | None = None
    ) -> Any:
        """Make an authenticated API request without exposing credentials."""
        session = async_get_clientsession(self.hass)
        async with session.request(
            method,
            f"{self.base_url}{path}",
            headers={"Authorization": self.authorization},
            json=json,
        ) as response:
            response.raise_for_status()
            return await response.json()

    async def async_request(
        self, method: str, path: str, *, json: dict[str, Any] | None = None
    ) -> Any:
        """Expose authenticated REST writes to entities."""
        return await self._async_api_json(method, path, json=json)

    async def _async_initial_fetch(self) -> None:
        """Hydrate configuration and health once before the push stream starts."""
        tonesets = await self._async_api_json("GET", "/api/tonesets")
        health = await self._async_api_json("GET", "/api/admin/health")
        sources = health if isinstance(health, list) else health.get("sources", [])
        health_by_source = {
            str(item["id"]): bool(item["feed_health_history"][-1]["healthy"])
            if item.get("feed_health_history")
            else None
            for item in sources
            if isinstance(item, dict) and item.get("id") is not None
        }
        self.latest_state.update(
            {
                "tonesets": tonesets if isinstance(tonesets, list) else [],
                "sources": sources if isinstance(sources, list) else [],
                "health": {
                    source_id: value
                    for source_id, value in health_by_source.items()
                    if value is not None
                },
            }
        )
        self.async_set_updated_data(self.latest_state)

    async def _async_no_poll(self) -> EventData:
        """Provide the coordinator's initial push-backed value."""
        return self.latest_state

    @property
    def base_url(self) -> str:
        """Return the configured API origin."""
        return _base_url(str(self.entry.data["host"]), int(self.entry.data["port"]))

    @property
    def websocket_url(self) -> str:
        """Return the configured WebSocket URL."""
        return _websocket_url(self.base_url)

    @property
    def authorization(self) -> str:
        """Return the bearer authorization value without logging it."""
        return f"Bearer {self.entry.data['api_token']}"

    async def async_start(self) -> None:
        """Start the reconnecting WebSocket task."""
        if self._task is None or self._task.done():
            self._stopped.clear()
            try:
                await self._async_initial_fetch()
            except (
                aiohttp.ClientError,
                OSError,
                RuntimeError,
                TimeoutError,
                AttributeError,
            ) as err:
                self.async_set_update_error(err)
                _LOGGER.warning("ToneWatch initial fetch failed: %s", err)
            self._task = asyncio.create_task(self._run(), name=f"tonewatch-{self.entry.entry_id}")

    async def async_stop(self) -> None:
        """Stop the WebSocket task and release its resources."""
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _run(self) -> None:
        """Connect, consume events, and retry with bounded jittered backoff."""
        attempt = 0
        session = async_get_clientsession(self.hass)
        while not self._stopped.is_set():
            try:
                async with session.ws_connect(
                    self.websocket_url,
                    headers={"Authorization": self.authorization},
                ) as websocket:
                    await websocket.send_json({"type": "subscribe", "topics": EVENT_TOPICS})
                    self.async_set_updated_data(self.latest_state)
                    await self._consume(websocket)
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, OSError, RuntimeError, TimeoutError) as err:
                if self._stopped.is_set():
                    return
                self.async_set_update_error(err)
                _LOGGER.warning("ToneWatch WebSocket disconnected: %s", err)
            if self._stopped.is_set():
                return
            delay = min(MAX_BACKOFF, BASE_BACKOFF * (2**attempt))
            delay *= 0.5 + self._random() * 0.5
            attempt = min(attempt + 1, 30)
            await self._sleep(delay)

    async def _consume(self, websocket: aiohttp.ClientWebSocketResponse) -> None:
        """Consume server messages until the socket closes."""
        async for message in websocket:
            if message.type is aiohttp.WSMsgType.TEXT:
                payload = message.json()
                if isinstance(payload, dict):
                    if payload.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                        continue
                    await self._handle_message(payload)
            elif message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                return

    async def _handle_message(self, payload: dict[str, Any]) -> None:
        """Update state for a protocol message and answer server heartbeats."""
        message_type = payload.get("type")
        if message_type == "ping":
            return
        if message_type in {"subscribed", "pong"}:
            return
        event = {"type": message_type, "data": payload.get("data", {})}
        events = self.latest_state.setdefault("events", [])
        if isinstance(events, list):
            events.append(event)
            del events[:-100]
        by_type = self.latest_state.setdefault("by_type", {})
        if isinstance(by_type, dict) and isinstance(message_type, str):
            by_type[message_type] = event["data"]
        self.latest_state["last_event"] = event
        self._apply_event(event)
        self.async_set_updated_data(self.latest_state)

    def _apply_event(self, event: EventData) -> None:
        """Apply a protocol event to the small state projection used by entities."""
        data = event.get("data")
        if not isinstance(data, dict):
            return
        event_type = event.get("type")
        if event_type == "ToneDetected":
            self.latest_state["call_active"] = True
            self.latest_state["last_call"] = data
            bus_data = {
                key: data.get(key)
                for key in ("call_id", "toneset_id", "source_id", "test", "drill")
            }
            bus_data["recording_url"] = self._recording_url(
                data.get("recording_id") or data.get("path")
            )
            self.hass.bus.async_fire("tonewatch_detected", bus_data)
        elif event_type == "RecordingReady":
            self.latest_state["last_call"] = {**self.latest_state.get("last_call", {}), **data}
        elif event_type == "CallClosed":
            self.latest_state["call_active"] = False
        elif event_type == "FeedHealthChanged":
            health = self.latest_state.setdefault("health", {})
            if isinstance(health, dict) and data.get("source_id") is not None:
                health[str(data["source_id"])] = bool(data.get("healthy"))
        elif event_type == "ConfigChanged":
            self.hass.async_create_task(self._async_refresh_config())

    async def _async_refresh_config(self) -> None:
        """Refresh tone sets after a pushed configuration change."""
        try:
            tonesets = await self._async_api_json("GET", "/api/tonesets")
        except (aiohttp.ClientError, OSError, RuntimeError, TimeoutError, AttributeError):
            return
        self.latest_state["tonesets"] = tonesets if isinstance(tonesets, list) else []
        self.async_set_updated_data(self.latest_state)

    def _recording_url(self, value: Any) -> str | None:
        """Build a token-free absolute recording URL."""
        if value in (None, ""):
            return None
        return f"{self.base_url}/api/recordings/{value}"
