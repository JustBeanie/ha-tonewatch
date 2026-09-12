"""Config flow contract tests using Home Assistant's test harness."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from homeassistant.config_entries import SOURCE_HASSIO, SOURCE_REAUTH, SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PORT
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tonewatch import config_flow
from custom_components.tonewatch.const import CONF_API_TOKEN, CONF_INSTANCE_ID, DOMAIN

if TYPE_CHECKING:
    from collections.abc import Mapping


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class FakeSession:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.calls: list[tuple[str, Mapping[str, str]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs["headers"]))
        return FakeResponse(self.status)


@pytest.fixture
def fake_session(monkeypatch: pytest.MonkeyPatch) -> FakeSession:
    session = FakeSession()
    monkeypatch.setattr(config_flow, "async_get_clientsession", lambda _hass: session)
    return session


async def _user_flow(hass: Any) -> dict[str, Any]:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] == "form"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_HOST: "tonewatch.local", CONF_PORT: 8099, CONF_API_TOKEN: "token"},
    )


async def test_user_success_uses_bearer_and_default_port(
    hass: Any, fake_session: FakeSession
) -> None:
    result = await _user_flow(hass)
    assert result["type"] == "create_entry"
    assert result["data"] == {
        CONF_HOST: "tonewatch.local",
        CONF_PORT: 8099,
        CONF_API_TOKEN: "token",
    }
    assert fake_session.calls[0][1] == {"Authorization": "Bearer token"}


@pytest.mark.parametrize(("status", "error"), [(500, "cannot_connect"), (401, "invalid_auth")])
async def test_user_validation_errors(
    hass: Any,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    error: str,
) -> None:
    session = FakeSession(status)
    monkeypatch.setattr(config_flow, "async_get_clientsession", lambda _hass: session)
    result = await _user_flow(hass)
    assert result["type"] == "form"
    assert result["errors"] == {"base": error}


async def test_zeroconf_discovery_confirm_and_duplicate(
    hass: Any, fake_session: FakeSession
) -> None:
    info = {"host": "192.0.2.10", "port": 8099, "properties": {b"instance_id": b"stable-1"}}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "zeroconf"}, data=info
    )
    assert result["step_id"] == "zeroconf_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_API_TOKEN: "token"}
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_INSTANCE_ID] == "stable-1"
    assert fake_session.calls
    entry = MockConfigEntry(domain=DOMAIN, data=result["data"])
    entry.add_to_hass(hass)
    duplicate = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "zeroconf"}, data=info
    )
    assert duplicate["type"] == "abort"
    assert duplicate["reason"] == "already_configured"


async def test_hassio_discovery_confirm(hass: Any, fake_session: FakeSession) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_HASSIO},
        data={"config": {CONF_HOST: "tonewatch", CONF_PORT: 8099}},
    )
    assert result["step_id"] == "hassio_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_API_TOKEN: "token"}
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "ToneWatch add-on"
    assert fake_session.calls


async def test_hassio_duplicate_falls_back_to_host_and_port(
    hass: Any, fake_session: FakeSession
) -> None:
    existing = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "tonewatch", CONF_PORT: 8099})
    existing.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_HASSIO},
        data={"config": {CONF_HOST: "tonewatch", CONF_PORT: 8099}},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_API_TOKEN: "token"}
    )
    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"
    assert fake_session.calls


async def test_reauth_updates_token(hass: Any, fake_session: FakeSession) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "tonewatch.local", CONF_PORT: 8099, CONF_API_TOKEN: "old"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_API_TOKEN: "new"}
    )
    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_TOKEN] == "new"
    assert fake_session.calls
