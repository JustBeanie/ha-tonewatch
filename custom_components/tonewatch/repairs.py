"""Runtime repair issues for the ToneWatch integration."""

from __future__ import annotations

from awesomeversion import AwesomeVersion
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry

from .const import DISCONNECT_REPAIR_AFTER, DOMAIN, MIN_APP_VERSION

APP_VERSION_ISSUE = "app_version_outdated"
WEBSOCKET_ISSUE = "websocket_disconnected"


def async_update_repairs(
    hass: HomeAssistant, app_version: str | None, disconnected_for: float
) -> None:
    """Create or clear version and WebSocket repair issues."""
    if app_version is not None and AwesomeVersion(app_version) < AwesomeVersion(MIN_APP_VERSION):
        issue_registry.async_create_issue(
            hass,
            DOMAIN,
            APP_VERSION_ISSUE,
            is_fixable=False,
            severity=issue_registry.IssueSeverity.ERROR,
            translation_key=APP_VERSION_ISSUE,
            translation_placeholders={
                "minimum_version": MIN_APP_VERSION,
                "app_version": app_version,
            },
        )
    else:
        issue_registry.async_delete_issue(hass, DOMAIN, APP_VERSION_ISSUE)
    if disconnected_for > DISCONNECT_REPAIR_AFTER:
        issue_registry.async_create_issue(
            hass,
            DOMAIN,
            WEBSOCKET_ISSUE,
            is_fixable=False,
            severity=issue_registry.IssueSeverity.WARNING,
            translation_key=WEBSOCKET_ISSUE,
            translation_placeholders={"minutes": str(round(disconnected_for / 60))},
        )
    else:
        issue_registry.async_delete_issue(hass, DOMAIN, WEBSOCKET_ISSUE)
