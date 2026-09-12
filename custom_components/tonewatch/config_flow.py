"""Config flow for ToneWatch API connections."""

from __future__ import annotations

from collections.abc import Mapping

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_VALIDATION_PATH,
    CONF_API_TOKEN,
    CONF_HOST,
    CONF_INSTANCE_ID,
    CONF_PORT,
    DEFAULT_PORT,
    DOMAIN,
)


def _discovery_value(info: object, key: str, default: object = None) -> object:
    """Read a value from a HA discovery mapping or object."""
    if isinstance(info, Mapping):
        return info.get(key, default)
    return getattr(info, key, default)


def _properties(info: object) -> Mapping[object, object]:
    """Return zeroconf TXT properties from discovery information."""
    value = _discovery_value(info, "properties", {})
    return value if isinstance(value, Mapping) else {}


def _property(properties: Mapping[object, object], key: str) -> str | None:
    """Read a zeroconf property with bytes and string key/value support."""
    for raw_key, raw_value in properties.items():
        normalized_key = (
            raw_key.decode(errors="replace") if isinstance(raw_key, bytes) else str(raw_key)
        )
        if normalized_key != key:
            continue
        return (
            raw_value.decode(errors="replace") if isinstance(raw_value, bytes) else str(raw_value)
        )
    return None


class ToneWatchConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle manual and discovered ToneWatch connections."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, object] = {}

    async def _validate(self, data: dict[str, object]) -> str | None:
        """Validate credentials against an authenticated ToneWatch endpoint."""
        host = str(data[CONF_HOST])
        port = int(str(data[CONF_PORT]))
        token = str(data[CONF_API_TOKEN])
        formatted_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        url = f"http://{formatted_host}:{port}{API_VALIDATION_PATH}"
        try:
            async with async_get_clientsession(self.hass).get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status in (401, 403):
                    return "invalid_auth"
                if response.status >= 400:
                    return "cannot_connect"
        except (aiohttp.ClientError, OSError, TimeoutError):
            return "cannot_connect"
        return None

    def _duplicate(self, data: Mapping[str, object]) -> bool:
        """Detect a configured instance by stable id, with host/port discovery fallback."""
        instance_id = data.get(CONF_INSTANCE_ID)
        for entry in self._async_current_entries():
            if instance_id and entry.data.get(CONF_INSTANCE_ID) == instance_id:
                return True
            if (
                not instance_id
                and entry.data.get(CONF_HOST) == data.get(CONF_HOST)
                and entry.data.get(CONF_PORT) == data.get(CONF_PORT)
            ):
                return True
        return False

    async def async_step_user(
        self, user_input: dict[str, object] | None = None
    ) -> ConfigFlowResult:
        """Handle manual setup."""
        if user_input is not None:
            user_input[CONF_HOST] = str(user_input[CONF_HOST]).strip()
            error = await self._validate(user_input)
            if error:
                return self._form("user", user_input, error)
            if self._duplicate(user_input):
                return self.async_abort(reason="already_configured")
            return self.async_create_entry(title=str(user_input[CONF_HOST]), data=user_input)
        return self._form("user")

    async def async_step_zeroconf(self, discovery_info: object) -> ConfigFlowResult:
        """Handle zeroconf discovery and present a token confirmation form."""
        properties = _properties(discovery_info)
        instance_id = _property(properties, CONF_INSTANCE_ID)
        host = str(_discovery_value(discovery_info, "host", ""))
        port = int(str(_discovery_value(discovery_info, "port", DEFAULT_PORT)))
        self._discovered = {CONF_HOST: host, CONF_PORT: port}
        if instance_id:
            self._discovered[CONF_INSTANCE_ID] = instance_id
            await self.async_set_unique_id(instance_id)
            self._abort_if_unique_id_configured()
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, object] | None = None
    ) -> ConfigFlowResult:
        """Confirm a zeroconf connection and collect its API token."""
        if user_input is not None:
            data = {**self._discovered, **user_input}
            error = await self._validate(data)
            if error:
                return self._form("zeroconf_confirm", user_input, error)
            if self._duplicate(data):
                return self.async_abort(reason="already_configured")
            return self.async_create_entry(title=str(data[CONF_HOST]), data=data)
        return self._form("zeroconf_confirm")

    async def async_step_hassio(self, discovery_info: object) -> ConfigFlowResult:
        """Handle Supervisor discovery and present a token confirmation form."""
        config = _discovery_value(discovery_info, "config", discovery_info)
        if not isinstance(config, Mapping):
            config = {}
        self._discovered = {
            CONF_HOST: str(config.get(CONF_HOST, "tonewatch")),
            CONF_PORT: int(str(config.get(CONF_PORT, DEFAULT_PORT))),
        }
        instance_id = config.get(CONF_INSTANCE_ID)
        if instance_id:
            self._discovered[CONF_INSTANCE_ID] = str(instance_id)
            await self.async_set_unique_id(str(instance_id))
            self._abort_if_unique_id_configured()
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(
        self, user_input: dict[str, object] | None = None
    ) -> ConfigFlowResult:
        """Confirm a Supervisor connection and collect its API token."""
        if user_input is not None:
            data = {**self._discovered, **user_input}
            error = await self._validate(data)
            if error:
                return self._form("hassio_confirm", user_input, error)
            if self._duplicate(data):
                return self.async_abort(reason="already_configured")
            return self.async_create_entry(title="ToneWatch add-on", data=data)
        return self._form("hassio_confirm")

    async def async_step_reauth(self, entry_data: Mapping[str, object]) -> ConfigFlowResult:
        """Start reauthentication for an existing entry."""
        self._discovered = dict(entry_data)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, object] | None = None
    ) -> ConfigFlowResult:
        """Validate and save a replacement API token."""
        if user_input is not None:
            data = {**self._discovered, CONF_API_TOKEN: user_input[CONF_API_TOKEN]}
            error = await self._validate(data)
            if error:
                return self._form("reauth_confirm", user_input, error)
            entry_id = self.context.get("entry_id")
            if entry_id:
                self.hass.config_entries.async_update_entry(
                    self.hass.config_entries.async_get_known_entry(entry_id), data=data
                )
            return self.async_abort(reason="reauth_successful")
        return self._form("reauth_confirm")

    def _form(
        self,
        step_id: str,
        user_input: dict[str, object] | None = None,
        error: str | None = None,
    ) -> ConfigFlowResult:
        """Return a token-safe config form."""
        fields: dict[object, object] = {vol.Required(CONF_API_TOKEN): str}
        if step_id == "user":
            fields = {
                vol.Required(CONF_HOST, default=(user_input or {}).get(CONF_HOST, "")): str,
                vol.Required(
                    CONF_PORT, default=(user_input or {}).get(CONF_PORT, DEFAULT_PORT)
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                **fields,
            }
        schema = vol.Schema(fields)
        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors={"base": error} if error else None,
        )
