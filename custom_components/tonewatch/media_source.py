"""ToneWatch recordings as an authenticated Home Assistant media source."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp
from aiohttp import web
from homeassistant.components.media_player.const import MediaClass, MediaType
from homeassistant.components.media_source import MediaSource
from homeassistant.components.media_source.error import Unresolvable
from homeassistant.components.media_source.models import (
    BrowseMediaSource,
    MediaSourceItem,
    PlayMedia,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.http import KEY_AUTHENTICATED, HomeAssistantView

from .const import DOMAIN
from .urls import recording_url

_LOGGER = logging.getLogger(__name__)
MAX_CHILDREN = 100


def _folder(hass: HomeAssistant, identifier: str, title: str) -> BrowseMediaSource:
    return BrowseMediaSource(
        domain=DOMAIN,
        identifier=identifier,
        media_class=MediaClass.DIRECTORY,
        media_content_type=MediaType.APP,
        title=title,
        can_play=False,
        can_expand=True,
        children_media_class=MediaClass.DIRECTORY,
    )


class ToneWatchMediaSource(MediaSource):
    """Browse ToneWatch calls and recordings."""

    name = "ToneWatch"

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(DOMAIN)
        self.hass = hass

    @property
    def coordinator(self) -> Any:
        entries = self.hass.data.get(DOMAIN, {})
        coordinator = next(
            (value for value in entries.values() if hasattr(value, "_async_api_json")), None
        )
        if coordinator is None:
            raise Unresolvable("ToneWatch is not configured")
        return coordinator

    async def _calls(self, **filters: str) -> list[dict[str, Any]]:
        cursor = 0
        result: list[dict[str, Any]] = []
        while len(result) < MAX_CHILDREN:
            query = "&".join(
                [
                    "limit=200",
                    f"cursor={cursor}",
                    *[f"{key}={value}" for key, value in filters.items()],
                ]
            )
            payload = await self.coordinator._async_api_json("GET", f"/api/calls?{query}")
            if not isinstance(payload, dict):
                break
            items = payload.get("items", [])
            if not isinstance(items, list):
                break
            result.extend(item for item in items if isinstance(item, dict))
            next_cursor = payload.get("next_cursor")
            if next_cursor is None:
                break
            cursor = int(next_cursor)
        return result[:MAX_CHILDREN]

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        identifier = item.identifier.strip("/")
        if not identifier:
            calls = await self._calls()
            years = sorted({str(_parse_started(call)[0]) for call in calls}, key=int)
            result = _folder(self.hass, "", "ToneWatch recordings")
            result.children = [_folder(self.hass, year, year) for year in years[-MAX_CHILDREN:]]
            return result

        parts = identifier.split("/")
        if len(parts) < 1 or len(parts) > 3 or not all(part.isdigit() for part in parts[:3]):
            raise Unresolvable(f"Unknown ToneWatch media id: {identifier}")
        if len(parts) < 3:
            prefix = "/".join(parts)
            calls = await self._calls()
            expected = tuple(parts)
            values = sorted(
                {
                    part[len(parts)]
                    for call in calls
                    if (part := _date_parts(call))[0 : len(parts)] == expected
                }
            )
            result = _folder(self.hass, prefix, parts[-1])
            result.children = [_folder(self.hass, f"{prefix}/{value}", value) for value in values]
            return result

        year, month, day = parts
        start = datetime(int(year), int(month), int(day), tzinfo=UTC).isoformat()
        end = (
            datetime(int(year), int(month), int(day), tzinfo=UTC) + timedelta(days=1)
        ).isoformat()
        calls = await self._calls(since=start, until=end)
        result = _folder(self.hass, identifier, f"{year}-{month}-{day}")
        children: list[BrowseMediaSource] = []
        for call in calls:
            detail = await self.coordinator._async_api_json("GET", f"/api/calls/{call['id']}")
            for recording in detail.get("recordings", []) if isinstance(detail, dict) else []:
                if not isinstance(recording, dict) or recording.get("id") is None:
                    continue
                timestamp = _parse_started(call)[3].strftime("%H:%M:%S")
                names = [
                    self._toneset_name(item.get("toneset_id"))
                    for item in detail.get("tone_sets", [])
                    if isinstance(item, dict)
                ]
                title = (
                    f"{timestamp} - {', '.join(names) or 'ToneWatch'} - "
                    f"{recording.get('duration_s', 0)} s"
                )
                child = BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=f"recording/{recording['id']}",
                    media_class=MediaClass.MUSIC,
                    media_content_type=MediaType.MUSIC,
                    title=title,
                    can_play=True,
                    can_expand=False,
                )
                children.append(child)
        result.children = children[:MAX_CHILDREN]
        result.not_shown = max(0, len(children) - MAX_CHILDREN)
        return result

    def _toneset_name(self, toneset_id: Any) -> str:
        for item in self.coordinator.latest_state.get("tonesets", []):
            if isinstance(item, dict) and item.get("id") == toneset_id:
                return str(item.get("name", toneset_id))
        return str(toneset_id)

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        parts = item.identifier.split("/")
        if len(parts) != 2 or parts[0] != "recording" or not parts[1].isdigit():
            raise Unresolvable(f"Unknown ToneWatch media id: {item.identifier}")
        recording_id = int(parts[1])
        for call in await self._calls():
            detail = await self.coordinator._async_api_json("GET", f"/api/calls/{call['id']}")
            recordings = detail.get("recordings", []) if isinstance(detail, dict) else []
            if any(
                isinstance(recording, dict) and recording.get("id") == recording_id
                for recording in recordings
            ):
                break
        else:
            raise Unresolvable(f"Unknown ToneWatch recording id: {recording_id}")
        entry_id = self.coordinator.entry.entry_id
        return PlayMedia(
            url=f"/api/tonewatch/media/{entry_id}/{parts[1]}",
            mime_type="audio/mpeg",
        )


def _parse_started(call: dict[str, Any]) -> tuple[int, int, int, datetime]:
    value = datetime.fromisoformat(str(call["started_at"]))
    return value.year, value.month, value.day, value


def _date_parts(call: dict[str, Any]) -> tuple[str, str, str]:
    year, month, day, _ = _parse_started(call)
    return str(year), f"{month:02d}", f"{day:02d}"


class ToneWatchMediaView(HomeAssistantView):
    """Proxy recordings through HA without exposing the ToneWatch token."""

    url = "/api/tonewatch/media/{entry_id}/{recording_id}"
    name = "api:tonewatch:media"

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(
        self, request: web.Request, entry_id: str, recording_id: str
    ) -> web.StreamResponse:
        if not request.get(KEY_AUTHENTICATED, False):
            raise web.HTTPUnauthorized
        coordinator = self.hass.data.get(DOMAIN, {}).get(entry_id)
        if coordinator is None or not recording_id.isdigit():
            raise web.HTTPNotFound
        headers = {
            "Authorization": coordinator.authorization,
            "Accept-Encoding": "identity",
        }
        if request.headers.get("Range"):
            headers["Range"] = request.headers["Range"]
        if request.headers.get("If-Range"):
            headers["If-Range"] = request.headers["If-Range"]
        session = async_get_clientsession(self.hass)
        upstream_url = recording_url(coordinator.base_url, recording_id)
        if upstream_url is None:
            raise web.HTTPNotFound
        try:
            timeout = aiohttp.ClientTimeout(total=30, sock_read=30)
            async with session.get(upstream_url, headers=headers, timeout=timeout) as upstream:
                if upstream.status == 404:
                    raise web.HTTPNotFound
                safe_headers = {
                    key: value
                    for key, value in upstream.headers.items()
                    if key.lower()
                    in {"content-type", "content-length", "content-range", "accept-ranges"}
                }
                response = web.StreamResponse(status=upstream.status, headers=safe_headers)
                await response.prepare(request)
                async for chunk in upstream.content.iter_chunked(64 * 1024):
                    await response.write(chunk)
                await response.write_eof()
                return response
        except web.HTTPException:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("ToneWatch recording proxy upstream failed: %s", err)
            raise web.HTTPBadGateway from err


async def async_get_media_source(hass: HomeAssistant) -> ToneWatchMediaSource:
    """Return the ToneWatch media source and register its proxy view."""
    marker = f"{DOMAIN}_media_view_registered"
    if not hass.data.get(marker):
        hass.http.register_view(ToneWatchMediaView(hass))
        hass.data[marker] = True
    return ToneWatchMediaSource(hass)
