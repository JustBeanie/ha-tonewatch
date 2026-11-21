"""Media source, proxy, and recording URL tests."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from homeassistant.components.media_source import Unresolvable
from homeassistant.components.media_source.models import MediaSourceItem
from homeassistant.helpers.http import KEY_AUTHENTICATED
from pytest_homeassistant.common import MockConfigEntry

from custom_components.tonewatch import media_source
from custom_components.tonewatch.api import ToneWatchCoordinator
from custom_components.tonewatch.const import DOMAIN


@pytest.fixture
def media_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id="media-entry",
        data={"host": "tonewatch.local", "port": 8099, "api_token": "fixture-token"},
    )


async def test_media_source_browse_and_resolve(
    hass: Any, media_entry: MockConfigEntry, monkeypatch: Any
) -> None:
    coordinator = ToneWatchCoordinator(hass, media_entry)
    coordinator.latest_state["tonesets"] = [{"id": "ems", "name": "EMS"}]
    calls = [
        {"id": "call-1", "started_at": "2026-01-02T03:04:05+00:00"},
        {"id": "call-2", "started_at": "2025-12-31T23:59:00+00:00"},
    ]
    details = {
        "call-1": {
            **calls[0],
            "tone_sets": [{"toneset_id": "ems"}],
            "recordings": [{"id": 42, "format": "mp3", "duration_s": 12.5}],
        },
        "call-2": {
            **calls[1],
            "tone_sets": [],
            "recordings": [{"id": 43, "format": "mp3", "duration_s": 4}],
        },
    }

    async def fake_json(_method: str, path: str, **_kwargs: Any) -> Any:
        if path.startswith("/api/calls/"):
            return details[path.rsplit("/", 1)[-1]]
        query = parse_qs(urlsplit(path).query)
        filtered = calls
        if "since" in query:
            filtered = [
                call
                for call in filtered
                if datetime.fromisoformat(call["started_at"])
                >= datetime.fromisoformat(query["since"][0])
            ]
        if "until" in query:
            filtered = [
                call
                for call in filtered
                if datetime.fromisoformat(call["started_at"])
                <= datetime.fromisoformat(query["until"][0])
            ]
        return {"items": filtered, "next_cursor": None}

    monkeypatch.setattr(coordinator, "_async_api_json", fake_json)
    hass.data.setdefault(DOMAIN, {})[media_entry.entry_id] = coordinator
    source = media_source.ToneWatchMediaSource(hass)

    root = await source.async_browse_media(MediaSourceItem(hass, DOMAIN, "", None))
    assert [child.title for child in root.children or []] == ["tonewatch.local"]
    instance = await source.async_browse_media(
        MediaSourceItem(hass, DOMAIN, "instance/media-entry", None)
    )
    assert [child.title for child in instance.children or []] == [
        "Recordings",
        "Live feeds",
        "Discovered tone clips",
    ]
    archive = await source.async_browse_media(
        MediaSourceItem(hass, DOMAIN, "instance/media-entry/recordings", None)
    )
    assert [child.title for child in archive.children or []] == ["2026", "2025"]
    day = await source.async_browse_media(
        MediaSourceItem(hass, DOMAIN, "instance/media-entry/recordings/2026/01/02", None)
    )
    assert len(day.children or []) == 1
    assert "03:04" in day.children[0].title
    assert "EMS" in day.children[0].title
    assert "12.5" in day.children[0].title

    resolved = await source.async_resolve_media(
        MediaSourceItem(hass, DOMAIN, "recording/media-entry/42/mp3", None)
    )
    assert resolved.url == "/api/tonewatch/media/media-entry/42"
    with pytest.raises(Unresolvable):
        await source.async_resolve_media(
            MediaSourceItem(hass, DOMAIN, "recording/media-entry/nope/mp3", None)
        )


async def test_media_source_paginates_and_separates_instances(
    hass: Any, media_entry: MockConfigEntry, monkeypatch: Any
) -> None:
    first = ToneWatchCoordinator(hass, media_entry)
    second_entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="second-entry",
        data={"host": "second.local", "port": 8099, "api_token": "another-token"},
    )
    second = ToneWatchCoordinator(hass, second_entry)
    calls = [
        {"id": f"call-{index}", "started_at": "2026-11-18T12:00:00+00:00"} for index in range(205)
    ]

    async def first_json(_method: str, path: str, **_kwargs: Any) -> Any:
        query = parse_qs(urlsplit(path).query)
        if path.startswith("/api/calls/"):
            return {
                "tone_sets": [],
                "recordings": [{"id": int(path.rsplit("-", 1)[-1]) + 1, "format": "ogg"}],
            }
        cursor = int(query.get("cursor", ["0"])[0])
        page = calls[cursor : cursor + 200]
        return {
            "items": page,
            "next_cursor": str(cursor + 200) if cursor + 200 < len(calls) else None,
        }

    async def second_json(_method: str, _path: str, **_kwargs: Any) -> Any:
        return {"items": [], "next_cursor": None}

    monkeypatch.setattr(first, "_async_api_json", first_json)
    monkeypatch.setattr(second, "_async_api_json", second_json)
    hass.data.setdefault(DOMAIN, {}).update(
        {media_entry.entry_id: first, second_entry.entry_id: second}
    )
    source = media_source.ToneWatchMediaSource(hass)
    root = await source.async_browse_media(MediaSourceItem(hass, DOMAIN, "", None))
    assert {child.title for child in root.children or []} == {"tonewatch.local", "second.local"}
    day = await source.async_browse_media(
        MediaSourceItem(hass, DOMAIN, "instance/media-entry/recordings/2026/11/18", None)
    )
    assert len(day.children or []) == 205
    assert day.children[0].media_content_type == "audio/ogg"
    empty = await source.async_browse_media(
        MediaSourceItem(hass, DOMAIN, "instance/second-entry/recordings", None)
    )
    assert empty.children == []


async def test_media_source_live_and_discovered_clips(
    hass: Any, media_entry: MockConfigEntry, monkeypatch: Any
) -> None:
    coordinator = ToneWatchCoordinator(hass, media_entry)
    coordinator.latest_state["configured_sources"] = [
        {"id": "north", "name": "North", "live_stream_enabled": True},
        {"id": "south", "name": "South", "live_stream_enabled": False},
    ]
    requests: list[tuple[str, str]] = []

    async def fake_json(method: str, path: str, **_kwargs: Any) -> Any:
        requests.append((method, path))
        if path.startswith("/api/discovered-tones?"):
            return {
                "items": [
                    {"id": 7, "count": 3, "best_clip_recording_path": "discovered/7.mp3"},
                    {"id": 8, "count": 1, "best_clip_recording_path": None},
                ]
            }
        if path.endswith("live-url?external=true"):
            return {"url": "/api/sources/north/live.mp3?t=signed"}
        raise AssertionError(path)

    monkeypatch.setattr(coordinator, "_async_api_json", fake_json)
    hass.data.setdefault(DOMAIN, {})[media_entry.entry_id] = coordinator
    source = media_source.ToneWatchMediaSource(hass)
    live = await source.async_browse_media(
        MediaSourceItem(hass, DOMAIN, "instance/media-entry/live", None)
    )
    assert [child.title for child in live.children or []] == ["North"]
    played = await source.async_resolve_media(
        MediaSourceItem(hass, DOMAIN, "live/media-entry/north", None)
    )
    assert played.url == "http://tonewatch.local:8099/api/sources/north/live.mp3?t=signed"
    clips = await source.async_browse_media(
        MediaSourceItem(hass, DOMAIN, "instance/media-entry/discovered", None)
    )
    assert len(clips.children or []) == 1
    clip = await source.async_resolve_media(
        MediaSourceItem(hass, DOMAIN, "clip/media-entry/7", None)
    )
    assert clip.url == "/api/tonewatch/clip/media-entry/7"
    assert ("POST", "/api/sources/north/live-url?external=true") in requests


# HA's KEY_AUTHENTICATED is still a plain str; aiohttp 3.13+ warns on str request keys.
@pytest.mark.filterwarnings("ignore::aiohttp.web_exceptions.NotAppKeyWarning")
async def test_media_proxy_requires_ha_auth_forwards_range_and_redacts_token(
    hass: Any, media_entry: MockConfigEntry, monkeypatch: Any, caplog: Any
) -> None:
    coordinator = ToneWatchCoordinator(hass, media_entry)
    hass.data.setdefault(DOMAIN, {})[media_entry.entry_id] = coordinator
    captured: dict[str, Any] = {}

    class Response:
        status = 206

        def __init__(self) -> None:
            self.headers = {
                "Content-Type": "audio/mpeg",
                "Content-Length": "2",
                "Content-Range": "bytes 2-3/4",
            }

        async def __aenter__(self) -> Response:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def read(self) -> bytes:
            return b"cd"

        class Content:
            async def iter_chunked(self, _size: int) -> Any:
                yield b"cd"

        content = Content()

    class Session:
        def get(self, url: str, **kwargs: Any) -> Response:
            captured.update(url=url, kwargs=kwargs)
            return Response()

    monkeypatch.setattr(media_source, "async_get_clientsession", lambda _hass: Session())
    view = media_source.ToneWatchMediaView(hass)
    request = make_mocked_request("GET", "/api/tonewatch/media/media-entry/42")
    request[KEY_AUTHENTICATED] = False
    with pytest.raises(web.HTTPUnauthorized):
        await view.get(request, media_entry.entry_id, "42")

    request[KEY_AUTHENTICATED] = True
    request._headers = {  # type: ignore[attr-defined]
        "Range": "bytes=2-3",
        "If-Range": "fixture-etag",
        "Accept-Encoding": "gzip",
    }
    response = await view.get(request, media_entry.entry_id, "42")
    assert captured["kwargs"]["headers"] == {
        "Authorization": "Bearer fixture-token",
        "Range": "bytes=2-3",
        "If-Range": "fixture-etag",
        "Accept-Encoding": "identity",
    }
    assert captured["kwargs"]["timeout"].total == 30
    assert captured["kwargs"]["timeout"].sock_read == 30
    assert response.status == 206
    assert "fixture-token" not in json.dumps(dict(response.headers))
    assert "fixture-token" not in caplog.text


@pytest.mark.parametrize(
    ("upstream_status", "expected_status"),
    [(404, 404), (416, 416)],
)
async def test_media_proxy_maps_not_found_and_forwards_range_status(
    hass: Any,
    media_entry: MockConfigEntry,
    monkeypatch: Any,
    upstream_status: int,
    expected_status: int,
) -> None:
    coordinator = ToneWatchCoordinator(hass, media_entry)
    hass.data.setdefault(DOMAIN, {})[media_entry.entry_id] = coordinator

    class Response:
        status = upstream_status

        def __init__(self) -> None:
            self.headers = {"Content-Range": "bytes */4"}

        class Content:
            async def iter_chunked(self, _size: int) -> Any:
                yield b""

        content = Content()

        async def __aenter__(self) -> Response:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    class Session:
        def get(self, _url: str, **_kwargs: Any) -> Response:
            return Response()

    monkeypatch.setattr(media_source, "async_get_clientsession", lambda _hass: Session())
    view = media_source.ToneWatchMediaView(hass)
    request = make_mocked_request("GET", "/api/tonewatch/media/media-entry/42")
    request[KEY_AUTHENTICATED] = True
    if upstream_status == 416:
        request._headers = {"Range": "bytes=99-100"}  # type: ignore[attr-defined]
        response = await view.get(request, media_entry.entry_id, "42")
        assert response.status == expected_status
    else:
        with pytest.raises(web.HTTPNotFound) as raised:
            await view.get(request, media_entry.entry_id, "42")
        assert raised.value.status == expected_status


async def test_media_proxy_maps_upstream_client_error(
    hass: Any, media_entry: MockConfigEntry, monkeypatch: Any
) -> None:
    coordinator = ToneWatchCoordinator(hass, media_entry)
    hass.data.setdefault(DOMAIN, {})[media_entry.entry_id] = coordinator

    class Session:
        def get(self, _url: str, **_kwargs: Any) -> Any:
            raise aiohttp.ClientConnectionError

    monkeypatch.setattr(media_source, "async_get_clientsession", lambda _hass: Session())
    view = media_source.ToneWatchMediaView(hass)
    request = make_mocked_request("GET", "/api/tonewatch/media/media-entry/42")
    request[KEY_AUTHENTICATED] = True
    with pytest.raises(web.HTTPBadGateway) as raised:
        await view.get(request, media_entry.entry_id, "42")
    assert raised.value.status == 502
