"""ToneWatch recordings as an authenticated Home Assistant media source."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlencode, urljoin

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
PAGE_SIZE = 200


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


def _mime(fmt: str) -> str:
    return {"mp3": "audio/mpeg", "ogg": "audio/ogg", "opus": "audio/ogg"}.get(
        fmt, "application/octet-stream"
    )


def _playable(identifier: str, title: str, mime_type: str) -> BrowseMediaSource:
    return BrowseMediaSource(
        domain=DOMAIN,
        identifier=identifier,
        media_class=MediaClass.MUSIC,
        media_content_type=mime_type,
        title=title,
        can_play=True,
        can_expand=False,
    )


class ToneWatchMediaSource(MediaSource):
    """Browse ToneWatch calls and recordings."""

    name = "ToneWatch"

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(DOMAIN)
        self.hass = hass

    def _coordinator(self, entry_id: str) -> Any:
        coordinator = self.hass.data.get(DOMAIN, {}).get(entry_id)
        if coordinator is None:
            raise Unresolvable("ToneWatch instance is not configured")
        return coordinator

    async def _calls(self, coordinator: Any, **filters: str) -> list[dict[str, Any]]:
        cursor = 0
        result: list[dict[str, Any]] = []
        while True:
            query = urlencode({"limit": PAGE_SIZE, "cursor": cursor, **filters})
            payload = await coordinator._async_api_json("GET", f"/api/calls?{query}")
            if not isinstance(payload, dict):
                break
            items = payload.get("items", [])
            if not isinstance(items, list):
                break
            result.extend(item for item in items if isinstance(item, dict))
            next_cursor = payload.get("next_cursor")
            if next_cursor is None:
                break
            try:
                new_cursor = int(next_cursor)
            except (TypeError, ValueError):
                break
            if new_cursor <= cursor:
                break
            cursor = new_cursor
        return result

    async def _discovered(self, coordinator: Any) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        offset = 0
        while True:
            payload = await coordinator._async_api_json(
                "GET", f"/api/discovered-tones?limit={PAGE_SIZE}&offset={offset}"
            )
            items = payload.get("items", []) if isinstance(payload, dict) else []
            if not isinstance(items, list) or not items:
                break
            result.extend(item for item in items if isinstance(item, dict))
            if len(items) < PAGE_SIZE:
                break
            offset += len(items)
        return result

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        identifier = item.identifier.strip("/")
        if not identifier:
            result = _folder(self.hass, "", "ToneWatch")
            result.children = [
                _folder(self.hass, f"instance/{entry_id}", str(entry.data.get("host", entry_id)))
                for entry_id, entry in (
                    (key, value.entry)
                    for key, value in self.hass.data.get(DOMAIN, {}).items()
                    if hasattr(value, "entry")
                )
            ]
            return result
        parts = identifier.split("/")
        if len(parts) < 2 or parts[0] != "instance":
            raise Unresolvable(f"Unknown ToneWatch media id: {identifier}")
        entry_id = parts[1]
        coordinator = self._coordinator(entry_id)
        if len(parts) == 2:
            result = _folder(self.hass, identifier, "ToneWatch")
            result.children = [
                _folder(self.hass, f"{identifier}/recordings", "Recordings"),
                _folder(self.hass, f"{identifier}/live", "Live feeds"),
                _folder(self.hass, f"{identifier}/discovered", "Discovered tone clips"),
            ]
            return result
        section = parts[2]
        if section == "live" and len(parts) == 3:
            result = _folder(self.hass, identifier, "Live feeds")
            result.children = [
                _playable(
                    f"live/{entry_id}/{source['id']}",
                    str(source.get("name", source["id"])),
                    "audio/mpeg",
                )
                for source in coordinator.latest_state.get("configured_sources", [])
                if isinstance(source, dict)
                and source.get("id")
                and source.get("live_stream_enabled")
            ]
            return result
        if section == "discovered" and len(parts) == 3:
            result = _folder(self.hass, identifier, "Discovered tone clips")
            result.children = [
                _playable(
                    f"clip/{entry_id}/{tone['id']}",
                    f"Tone {tone['id']} · {tone.get('count', 1)} observations",
                    "audio/mpeg",
                )
                for tone in await self._discovered(coordinator)
                if tone.get("id") is not None and tone.get("best_clip_recording_path")
            ]
            return result
        if section != "recordings" or len(parts) > 6:
            raise Unresolvable(f"Unknown ToneWatch media id: {identifier}")
        date_parts = parts[3:]
        if any(not part.isdigit() for part in date_parts):
            raise Unresolvable(f"Unknown ToneWatch media id: {identifier}")
        try:
            if date_parts:
                year = int(date_parts[0])
                month = int(date_parts[1]) if len(date_parts) > 1 else 1
                day = int(date_parts[2]) if len(date_parts) > 2 else 1
                start = datetime(year, month, day, tzinfo=UTC)
                if len(date_parts) == 1:
                    end = datetime(year + 1, 1, 1, tzinfo=UTC)
                elif len(date_parts) == 2:
                    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=UTC)
                else:
                    end = start + timedelta(days=1)
                calls = await self._calls(
                    coordinator, since=start.isoformat(), until=end.isoformat()
                )
                calls = [call for call in calls if start <= _parse_started(call)[3] < end]
            else:
                calls = await self._calls(coordinator)
        except (ValueError, KeyError) as err:
            raise Unresolvable(f"Invalid ToneWatch date: {identifier}") from err
        result = _folder(self.hass, identifier, date_parts[-1] if date_parts else "Recordings")
        if len(date_parts) < 3:
            values = sorted({_date_parts(call)[len(date_parts)] for call in calls}, reverse=True)
            result.children = [
                _folder(self.hass, f"{identifier}/{value}", value) for value in values
            ]
            return result
        semaphore = asyncio.Semaphore(8)

        async def fetch_detail(call: dict[str, Any]) -> dict[str, Any] | None:
            async with semaphore:
                detail = await coordinator._async_api_json(
                    "GET", f"/api/calls/{quote(str(call['id']), safe='')}"
                )
                return detail if isinstance(detail, dict) else None

        ordered = sorted(calls, key=lambda value: value["started_at"], reverse=True)
        details = await asyncio.gather(*(fetch_detail(call) for call in ordered))
        children = []
        for call, detail in zip(ordered, details, strict=True):
            if not isinstance(detail, dict):
                continue
            for recording in detail.get("recordings", []):
                if not isinstance(recording, dict) or not isinstance(recording.get("id"), int):
                    continue
                names = [
                    self._toneset_name(coordinator, tone.get("toneset_id"))
                    for tone in detail.get("tone_sets", [])
                    if isinstance(tone, dict)
                ]
                fmt = str(recording.get("format", "mp3"))
                title = (
                    f"{_parse_started(call)[3]:%H:%M:%S} · "
                    f"{', '.join(names) or 'ToneWatch'} · "
                    f"{recording.get('duration_s', 0)} s"
                )
                children.append(
                    _playable(f"recording/{entry_id}/{recording['id']}/{fmt}", title, _mime(fmt))
                )
        result.children = children
        return result

    @staticmethod
    def _toneset_name(coordinator: Any, toneset_id: Any) -> str:
        for item in coordinator.latest_state.get("tonesets", []):
            if isinstance(item, dict) and str(item.get("id")) == str(toneset_id):
                return str(item.get("name", toneset_id))
        return str(toneset_id)

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        parts = item.identifier.split("/")
        if len(parts) < 3 or (not parts[2].isdigit() and parts[0] != "live"):
            raise Unresolvable(f"Unknown ToneWatch media id: {item.identifier}")
        coordinator = self._coordinator(parts[1])
        if parts[0] == "recording" and len(parts) == 4:
            return PlayMedia(
                url=f"/api/tonewatch/media/{parts[1]}/{parts[2]}", mime_type=_mime(parts[3])
            )
        if parts[0] == "clip" and len(parts) == 3:
            return PlayMedia(
                url=f"/api/tonewatch/clip/{parts[1]}/{parts[2]}", mime_type="audio/mpeg"
            )
        if parts[0] == "live" and len(parts) == 3:
            payload = await coordinator._async_api_json(
                "POST", f"/api/sources/{quote(parts[2])}/live-url?external=true"
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("url"), str):
                raise Unresolvable("ToneWatch live feed is unavailable")
            return PlayMedia(
                url=urljoin(f"{coordinator.base_url}/", payload["url"]), mime_type="audio/mpeg"
            )
        raise Unresolvable(f"Unknown ToneWatch media id: {item.identifier}")


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

    def upstream_url(self, coordinator: Any, recording_id: str) -> str | None:
        """Build the upstream URL without putting its token in a client URL."""
        return recording_url(coordinator.base_url, recording_id)

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
        upstream_url = self.upstream_url(coordinator, recording_id)
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


class ToneWatchClipView(ToneWatchMediaView):
    """Proxy discovered-tone evidence clips through Home Assistant."""

    url = "/api/tonewatch/clip/{entry_id}/{recording_id}"
    name = "api:tonewatch:clip"

    def upstream_url(self, coordinator: Any, recording_id: str) -> str:
        return f"{coordinator.base_url}/api/discovered-tones/{recording_id}/clip"


async def async_get_media_source(hass: HomeAssistant) -> ToneWatchMediaSource:
    """Return the ToneWatch media source and register its proxy view."""
    marker = f"{DOMAIN}_media_view_registered"
    if not hass.data.get(marker):
        hass.http.register_view(ToneWatchMediaView(hass))
        hass.http.register_view(ToneWatchClipView(hass))
        hass.data[marker] = True
    return ToneWatchMediaSource(hass)
