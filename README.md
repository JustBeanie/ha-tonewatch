# ToneWatch Home Assistant integration

ToneWatch is a local Home Assistant custom integration for the ToneWatch API.
It discovers local instances over zeroconf, supports Supervisor add-on discovery,
and receives state updates over the authenticated WebSocket stream.

The integration fires a `tonewatch_detected` Home Assistant bus event for every
detection. Its data contains `call_id`, `toneset_id`, `source_id`,
`recording_url`, `test`, and `drill`. The recording URL is absolute but carries
no API token; authenticated media access is handled by Home Assistant.

## Media browser and diagnostics

Open Media in Home Assistant and choose ToneWatch to browse recordings by
year, month, and day. Each recording is resolved through an authenticated
Home Assistant proxy, so the ToneWatch API token is never sent to a browser or
media player. Byte ranges are forwarded for players that stream or seek.

The integration diagnostics page includes redacted entry data, connection
state, the last connection error, tone-set/source counts, and the ToneWatch
app version. Repair issues are raised when the app is below the supported
version or the WebSocket has been disconnected for more than five minutes,
and clear automatically when fixed.

## Blueprints

Copy either YAML file from `blueprints/automation/tonewatch/` into Home
Assistant's blueprints directory, or use the file's `source_url` in the
blueprint import UI. Create an automation from:

- `play_dispatch_audio.yaml`, selecting a ToneWatch event entity and a
  `media_player`.
- `notify_with_audio.yaml`, selecting the event entity, a
  `notify.mobile_app_*` service, and a title.

The notification blueprint uses the iOS Companion app's `attachment` field
for audio and points it at the authenticated HA proxy. The current Companion
documentation lists audio attachments for iOS, not Android; Android receives
the authenticated proxy URL as a link in the message. This was verified
against the Companion notification attachment support table when M11.7 was
written.

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
