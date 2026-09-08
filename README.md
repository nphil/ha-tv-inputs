<img src="custom_components/tv_inputs/brand/icon.png" width="96" align="right" alt="">

# TV Inputs

Gives any Home Assistant media player a real **input list** and a working
**remote**, so an Android TV box, projector or streaming stick shows up in Apple
Home the way an Apple TV does — app tiles you can pick, and a D‑pad that moves.

[![hacs][hacs-badge]][hacs] [![release][release-badge]][releases] [![validate][validate-badge]][validate]

## Why this exists

Expose an Android TV box to HomeKit through Home Assistant's `homekit`
integration and you get a power switch. Nothing else. No inputs, and a remote
whose buttons do nothing.

Two upstream facts cause it:

- HomeKit's Television accessory builds its input list from the media player's
  `source_list` and calls `select_source`. The `androidtv_remote` media player
  never advertises `SELECT_SOURCE` — its configured apps only feed `app_name`
  and the media browser — so HomeKit has no inputs to show.
- Every key HomeKit's on-screen remote cannot handle itself (the D‑pad, back,
  home, transport) is fired on the Home Assistant event bus as
  `homekit_tv_remote_key_pressed` and dropped unless something consumes it.

The usual fix is a hand-written `universal` media player, an `input_select` to
hold the app names, a templated `select_source` command, and an automation to
forward the keys — four moving parts in YAML, none of them editable in the UI.

This integration is those four parts, as one config entry you set up and edit in
the UI.

## What you get

- A media player entity wrapping your existing one, with your apps as its
  **source list**; picking one launches it.
- **Current input reported back**, so Apple Home highlights the app that is
  actually running, even when you launched it with the physical remote.
- **Remote keys forwarded** to your `remote.*` entity, with a sane Android
  keycode map you can override per key.
- **A constant feature set.** HomeKit rebuilds an accessory whenever
  `supported_features` changes, which tears the tile down mid-session; this
  entity advertises the same capabilities whether the TV is on or off.
- Power, volume, mute and transport delegated to the wrapped player; casting and
  the media browser keep working.

## Installation

### HACS

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/nphil/ha-tv-inputs`, category **Integration**.
2. Install **TV Inputs**, restart Home Assistant.
3. Settings → Devices & services → **Add integration** → *TV Inputs*.

The entry lives on the **Integrations** tab (it registers a device), not under Helpers.

### Manual

Copy `custom_components/tv_inputs/` into your `config/custom_components/`,
restart, then add the integration from the UI.

## Setup

| Field | What it is |
|---|---|
| Name | What the new entity is called — use the name you want to see in Apple Home |
| Media player | The player being wrapped, e.g. your `androidtv_remote` entity |
| Remote | Optional. The `remote.*` entity used for key presses and play/pause |
| Type | `tv` or `receiver` — decides how Apple Home draws it |

Then add your inputs. Each one is a label plus what to launch:

| Field | Notes |
|---|---|
| Label | What Apple Home shows, and what `source` reports |
| Launch type | **Deep link** (recommended) or **App package** |
| Launch target | The link or package id |
| App id | Optional. The `app_id` the player reports for this app, used to detect it is running |

### Deep links, not package names

Android TV launchers are inconsistent about launching by package id — on a
Projectivy-based box, `play_media` with `media_content_type: app` is accepted and
silently ignored, while a deep link works every time. Prefer deep links:

| App | Deep link |
|---|---|
| Netflix | `https://www.netflix.com/browse` |
| Prime Video | `https://app.primevideo.com` |
| Plex | `plex://` |
| Apple TV | `https://tv.apple.com` |
| YouTube | `https://www.youtube.com` |
| Disney+ | `https://www.disneyplus.com` |

If an app will not start, try its own scheme (`plex://`, `nflx://`) before
falling back to the package id.

## Exposing it to HomeKit

Add a **HomeKit Bridge** entry in *accessory* mode containing only this entity
(accessory mode is what makes Apple Home draw a television rather than a
switch), pair it, and the app tiles and remote appear.

Keep the wrapped player and the remote **out** of any HomeKit bridge — exposing
them as well produces duplicate, less useful tiles.

## Key map

Defaults, overridable per key in the options:

| HomeKit key | Android keycode |
|---|---|
| `arrow_up` / `down` / `left` / `right` | `DPAD_UP` / `DPAD_DOWN` / `DPAD_LEFT` / `DPAD_RIGHT` |
| `select` | `DPAD_CENTER` |
| `back` | `BACK` |
| `exit` | `HOME` |
| `information` | `INFO` |
| `rewind` / `fast_forward` | `MEDIA_REWIND` / `MEDIA_FAST_FORWARD` |
| `next_track` / `previous_track` | `MEDIA_NEXT` / `MEDIA_PREVIOUS` |
| `play_pause` | `MEDIA_PLAY_PAUSE` |

Play/pause is sent as a key rather than a service call because the Android TV
player never reports `playing`, so a service-based toggle always guesses wrong.

## Requirements

- Home Assistant **2026.9.0** or newer.
- A media player to wrap. Anything with `play_media` works; `androidtv_remote`
  is the case this was built for.

## Development

Pure logic — input resolution, key mapping, feature-set computation — lives in
`custom_components/tv_inputs/logic.py` with no Home Assistant imports:

```bash
python3 -m pytest tests
```

## Licence

MIT © nphil

[hacs]: https://github.com/hacs/integration
[hacs-badge]: https://img.shields.io/badge/HACS-custom-41BDF5.svg
[release-badge]: https://img.shields.io/github/v/release/nphil/ha-tv-inputs
[releases]: https://github.com/nphil/ha-tv-inputs/releases
[validate]: https://github.com/nphil/ha-tv-inputs/actions/workflows/validate.yml
[validate-badge]: https://github.com/nphil/ha-tv-inputs/actions/workflows/validate.yml/badge.svg
