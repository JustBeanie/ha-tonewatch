"""Shared fixtures for the ToneWatch integration tests."""

import pytest
from homeassistant import loader
from homeassistant.core import HomeAssistant


@pytest.fixture(autouse=True)
def _enable_custom_integrations(hass: HomeAssistant) -> None:
    """Allow the HA harness to discover integrations from this checkout."""
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
