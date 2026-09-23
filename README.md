# ToneWatch Home Assistant integration

ToneWatch is a local Home Assistant custom integration for the ToneWatch API.
It discovers local instances over zeroconf, supports Supervisor add-on discovery,
and receives state updates over the authenticated WebSocket stream.

The integration fires a `tonewatch_detected` Home Assistant bus event for every
detection. Its data contains `call_id`, `toneset_id`, `source_id`,
`recording_url`, `test`, and `drill`. The recording URL is absolute but carries
no API token; authenticated media access is handled by Home Assistant.

ToneWatch is a supplemental notification tool, not a certified primary alerting
system. Keep an independently supervised and tested alerting path for emergency
and life-safety notifications.

## Stable instance identity

ToneWatch publishes its stable `instance_id` in zeroconf TXT records. The current
API does not expose that identifier, and Supervisor discovery currently sends only
host and port, so manually configured and add-on entries use host/port duplicate
detection until the server adds an authenticated identity endpoint or includes the
identifier in Supervisor discovery.

## Development

Install the pinned toolchain with `uv sync --python 3.13.13`, then run `just check`.
The integration uses no runtime Python dependencies beyond Home Assistant.
