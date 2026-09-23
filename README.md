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

## Installation

Install the `ToneWatch` custom repository through HACS:

1. Open HACS and select **Integrations**.
2. Add `https://github.com/JustBeanie/ha-tonewatch` as a custom repository of type **Integration**.
3. Install ToneWatch, restart Home Assistant, and add **ToneWatch** from **Settings > Devices & services**.

The current integration release is **0.2.0**. ToneWatch requires Home Assistant
2026.2 or newer and a ToneWatch API token. It has no runtime dependencies beyond
Home Assistant.

## Configuration

For manual setup, enter the ToneWatch host name or IP address, API port (the
default is `8099`), and API token. The integration tests the authenticated
`/api/devices` endpoint before saving the entry. Local ToneWatch instances can
also be discovered over zeroconf; ToneWatch add-ons can be discovered through
Supervisor. If a token expires, Home Assistant opens the reauthentication flow.

## Entities and actions

Each configured ToneWatch instance provides:

- One **event** entity for each tone set. It emits `pre_alert` and
  `recording_ready` events and includes call and recording attributes.
- One **timestamp sensor** for the last detected call.
- One **running binary sensor** for whether a call is active.
- One **connectivity binary sensor** for each configured feed.
- One **switch** for enabling or disabling each tone set.
- One **button** for testing each tone set.

Writes that cannot reach ToneWatch raise a Home Assistant error and restore the
previous switch state. ToneWatch uses a push WebSocket connection; entities are
marked unavailable while that connection is down and recover automatically.

## Troubleshooting and removal

If setup reports that it cannot connect, check the host, port, API token, and
that `/api/devices` is reachable from the Home Assistant host. An invalid token
is reported separately. During an outage, check the integration diagnostics and
the ToneWatch app; a persistent WebSocket outage creates a repair issue. The
integration logs one disconnect and one reconnect transition, rather than one
message per retry.

To remove ToneWatch, open **Settings > Devices & services**, select the
ToneWatch integration, choose the entry menu, and select **Delete**. Remove the
custom repository from HACS if it is no longer needed, then restart Home
Assistant if HACS requests it. Existing blueprints and automations are not
deleted automatically; remove them separately if desired.

## Development

Install the pinned toolchain with `uv sync --python 3.13.13`, then run `just check`.
The integration uses no runtime Python dependencies beyond Home Assistant.
