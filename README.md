![ToneWatch for Home Assistant](docs/banner.svg)

[![CI](https://github.com/JustBeanie/ha-tonewatch/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/JustBeanie/ha-tonewatch/actions/workflows/ci.yml)
[![Home Assistant 2026.2+](https://img.shields.io/badge/Home%20Assistant-2026.2%2B-2563eb)](https://www.home-assistant.io/)
[![ToneWatch 0.6.3+](https://img.shields.io/badge/ToneWatch-0.6.3%2B-2563eb)](https://github.com/JustBeanie/tonewatch/releases)
[![HACS custom repository](https://img.shields.io/badge/HACS-custom%20repository-41bdf5)](https://www.hacs.dev/docs/publish/integration/)
[![Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-35465f)](LICENSE)

ToneWatch detects radio paging tones, records the following dispatch, and sends alerts. This custom integration connects a ToneWatch app to Home Assistant over the local API and a push WebSocket. It adds event entities, operational status, and a **ToneWatch** entry in Home Assistant's **Media** tab.

> ToneWatch is a supplemental notification tool, not a certified primary alerting system. Keep an independently supervised and tested path for emergency notifications.

## Get started

You need Home Assistant **2026.2 or newer**, ToneWatch **0.6.3 or newer**, and a ToneWatch API token. The Home Assistant host must be able to reach the ToneWatch API, normally on port `8099`.

1. In HACS, add `https://github.com/JustBeanie/ha-tonewatch` as a **custom integration repository**.
2. Install **ToneWatch** and restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → ToneWatch**.
4. Enter the ToneWatch host, API port, and token. A discovered local instance or Home Assistant App can also start the setup flow; confirm it with the token.

The integration validates the token before saving. If it expires, Home Assistant offers reauthentication. For the ToneWatch application itself, see the [app repository](https://github.com/JustBeanie/tonewatch) or [Home Assistant App repository](https://github.com/JustBeanie/ha-addons).

To change the host, port, or token later, open **Settings → Devices & services → ToneWatch → Reconfigure**. Zeroconf rediscovery also updates the address of an instance with the same stable ID.

## What appears in Home Assistant

| Area | What it provides |
| --- | --- |
| Events | `pre_alert` and `recording_ready` for each tone set, plus discovered tones and CAD-enriched calls. |
| Status | Last call, active call, feed health, CAD feed connectivity and active incidents, alert delivery failures, and optional squelch and storage diagnostics. |
| Controls | A switch to enable each tone set and a button to run its test. |
| Media | Recordings by date, discovered-tone evidence clips, and enabled live feeds, separated by ToneWatch instance. |

ToneWatch pushes detection and configuration changes over WebSocket. Health details refresh every minute. Entities become unavailable when the connection is down and recover when it returns. New ToneWatch configurations are reflected after a configuration-change event.

### Media tab

Open **Media → ToneWatch → your instance**. Browse **Recordings** by year, month, and day, open **Discovered tone clips**, or select an enabled **Live feed**. A live stream must first be enabled in ToneWatch for both the app and that source. A fresh, short-lived URL is issued when playback starts; it is never stored in an entity state.

Recordings and clips pass through an authenticated Home Assistant proxy. The ToneWatch API token stays on the Home Assistant server. Playback on a separate speaker requires that speaker to reach the Home Assistant URL; live playback requires it to reach the ToneWatch stream URL. The Home Assistant App may also show its shared `/media/tonewatch` files as a separate Media folder.

## Automations

Import a bundled blueprint by pasting its source URL into **Settings → Automations & scenes → Blueprints → Import blueprint**:

- [Play dispatch audio](blueprints/automation/tonewatch/play_dispatch_audio.yaml) on a selected media player.
- [Notify with audio](blueprints/automation/tonewatch/notify_with_audio.yaml) on a mobile device.

Select a ToneWatch event entity for the tone set. Both blueprints act on `recording_ready`, after ToneWatch has stored the recording and assigned its playable ID. iOS Companion can attach supported audio; Android receives a link in the notification. Audio attachments have platform and size limits described in the [Companion documentation](https://companion.home-assistant.io/docs/notifications/notification-attachments/).

For a custom automation on Home Assistant 2026.2, trigger on a state change of the event entity and inspect its `event_type` attribute. The state itself is a timestamp, not `recording_ready`:

```yaml
triggers:
  - trigger: state
    entity_id: event.your_tonewatch_tone_set
conditions:
  - condition: template
    value_template: >-
      {{ trigger.to_state is not none
         and trigger.to_state.attributes.get('event_type') == 'recording_ready'
         and trigger.to_state.attributes.get('recording_proxy_url') }}
actions:
  - action: media_player.play_media
    target:
      entity_id: media_player.your_speaker
    data:
      media_content_id: "{{ trigger.to_state.attributes.recording_proxy_url }}"
      media_content_type: audio/mpeg
mode: queued
```

The `tonewatch_detected` event remains available on Home Assistant's event bus for each detection. It contains the call, tone-set, and source IDs plus test and drill flags. Event entities also carry agency or CAD details when ToneWatch supplies them.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Setup cannot connect | Confirm host, port, and that Home Assistant can reach ToneWatch's `/api/devices` endpoint. |
| Invalid token | Create a current ToneWatch API token and complete the reauthentication flow. |
| Entities unavailable | Check the ToneWatch app, network, integration diagnostics, and any Home Assistant repair issue. |
| Media folder empty | Check the selected instance and whether ToneWatch has stored calls or discovered-tone evidence clips. |
| Speaker cannot play | Confirm the player can reach Home Assistant, supports the recording format, and can follow its signed media URL. |
| Live feed missing | Enable global live streaming and the source's live-stream setting in ToneWatch. |

Use **Settings → Devices & services → ToneWatch → Diagnostics** for a redacted connection summary. Do not post API tokens, signed live URLs, recordings, or CAD addresses in public issues. For help, [open an issue](https://github.com/JustBeanie/ha-tonewatch/issues); for vulnerabilities, see [SECURITY.md](SECURITY.md).

## Remove or contribute

Remove the integration under **Settings → Devices & services**. Remove the HACS custom repository if no longer needed. Imported blueprints and automations are separate and must be removed individually. See [CONTRIBUTING.md](CONTRIBUTING.md) for development and pull requests.
