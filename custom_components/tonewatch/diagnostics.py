"""Diagnostics for ToneWatch."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from .const import DOMAIN

_REDACT = {
    "api_token",
    "api_password",
    "password",
    "live_secret",
    "live_stream_secret",
    "secret",
    "ui_password",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry[dict[str, object]]
) -> dict[str, Any]:
    """Return redacted config and coordinator health."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    state = coordinator.connection_state if coordinator else "not_loaded"
    last_error = (
        str(coordinator.last_exception) if coordinator and coordinator.last_exception else None
    )
    latest = coordinator.latest_state if coordinator else {}
    return {
        "entry": async_redact_data(dict(entry.data), _REDACT),
        "connection_state": state,
        "last_error": last_error,
        "tone_set_count": len(latest.get("tonesets", [])),
        "source_count": len(latest.get("sources", [])),
        "app_version": coordinator.app_version if coordinator else None,
    }
