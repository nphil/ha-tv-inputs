# TV Inputs

Gives any media player a real input list and a working remote, so an Android TV
box, projector or streaming stick appears in Apple Home the way an Apple TV
does — app tiles you can pick, and a D-pad that moves.

Exposed directly, an `androidtv_remote` player gives HomeKit a bare power
switch: it never advertises `SELECT_SOURCE`, and the keys HomeKit fires on the
event bus are dropped. This integration wraps it and supplies both.

- Your apps as the source list; picking one launches it
- The running app reported back, so Apple Home highlights it
- Remote keys forwarded to your `remote.*` entity, with an overridable keycode map
- A constant feature set, so the HomeKit accessory is not rebuilt when the TV
  turns on or off
- Power, volume, transport, casting and the media browser pass through

Replaces the usual hand-written `universal` player + `input_select` + template +
automation. Configured entirely in the UI. No YAML.
