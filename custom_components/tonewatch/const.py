"""Constants for the ToneWatch Home Assistant integration."""

from __future__ import annotations

DOMAIN = "tonewatch"
NAME = "ToneWatch"
DEFAULT_PORT = 8099
CONF_API_TOKEN = "api_token"  # noqa: S105 - this is a configuration key, not a secret.
CONF_INSTANCE_ID = "instance_id"
CONF_HOST = "host"
CONF_PORT = "port"
WS_PATH = "/api/ws"
API_VALIDATION_PATH = "/api/devices"
EVENT_TOPICS = ["events"]
BASE_BACKOFF = 1.0
MAX_BACKOFF = 60.0
