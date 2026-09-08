"""Pure decision logic for TV Inputs.

Nothing in this module imports Home Assistant, so the tests can exercise it
with plain pytest: input normalisation, label <-> input resolution, the HomeKit
remote key map and the supported-feature computation all live here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

CONF_LABEL: Final = "label"
CONF_LAUNCH_TYPE: Final = "launch_type"
CONF_LAUNCH_TARGET: Final = "launch_target"
CONF_APP_ID: Final = "app_id"

LAUNCH_TYPE_URL: Final = "url"
LAUNCH_TYPE_APP: Final = "app"
LAUNCH_TYPES: Final = (LAUNCH_TYPE_URL, LAUNCH_TYPE_APP)

# MediaPlayerEntityFeature bit values, homeassistant/components/media_player/const.py
# in Core 2026.9.1. Mirrored as integers so this module stays importable
# without Core; media_player.py wraps the result back into the IntFlag.
FEATURE_PAUSE: Final = 1
FEATURE_VOLUME_SET: Final = 4
FEATURE_VOLUME_MUTE: Final = 8
FEATURE_PREVIOUS_TRACK: Final = 16
FEATURE_NEXT_TRACK: Final = 32
FEATURE_TURN_ON: Final = 128
FEATURE_TURN_OFF: Final = 256
FEATURE_PLAY_MEDIA: Final = 512
FEATURE_VOLUME_STEP: Final = 1024
FEATURE_SELECT_SOURCE: Final = 2048
FEATURE_STOP: Final = 4096
FEATURE_PLAY: Final = 16384
FEATURE_BROWSE_MEDIA: Final = 131072

# The fixed feature set. HomeKit tears down and rebuilds the accessory whenever
# supported_features changes (homekit/accessories.py RELOAD_ON_CHANGE_ATTRS), so
# the wrapper always advertises the same set regardless of the child's power state.
BASE_FEATURES: Final = (
    FEATURE_TURN_ON
    | FEATURE_TURN_OFF
    | FEATURE_SELECT_SOURCE
    | FEATURE_VOLUME_STEP
    | FEATURE_VOLUME_MUTE
    | FEATURE_PLAY
    | FEATURE_PAUSE
    | FEATURE_STOP
    | FEATURE_NEXT_TRACK
    | FEATURE_PREVIOUS_TRACK
    | FEATURE_PLAY_MEDIA
    | FEATURE_BROWSE_MEDIA
)

# HomeKit key names (homeassistant/components/homekit/const.py) -> Android TV
# keycodes accepted by remote.send_command on androidtv_remote. Proven live on
# the onn 4K box behind the master bedroom projector.
DEFAULT_KEY_MAP: Final[Mapping[str, str]] = {
    "arrow_up": "DPAD_UP",
    "arrow_down": "DPAD_DOWN",
    "arrow_left": "DPAD_LEFT",
    "arrow_right": "DPAD_RIGHT",
    "select": "DPAD_CENTER",
    "back": "BACK",
    "exit": "HOME",
    "information": "INFO",
    "rewind": "MEDIA_REWIND",
    "fast_forward": "MEDIA_FAST_FORWARD",
    "next_track": "MEDIA_NEXT",
    "previous_track": "MEDIA_PREVIOUS",
    "play_pause": "MEDIA_PLAY_PAUSE",
}
HOMEKIT_KEYS: Final = tuple(DEFAULT_KEY_MAP)


class InputError(ValueError):
    """An input record cannot be used; ``code`` is a translation error key."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class TvInput:
    """One HomeKit input: what it is called and how the child launches it."""

    label: str
    launch_type: str
    launch_target: str
    app_id: str | None = None

    def as_dict(self) -> dict[str, str]:
        record = {
            CONF_LABEL: self.label,
            CONF_LAUNCH_TYPE: self.launch_type,
            CONF_LAUNCH_TARGET: self.launch_target,
        }
        if self.app_id:
            record[CONF_APP_ID] = self.app_id
        return record


def _clean(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def normalise_input(raw: Mapping[str, Any]) -> TvInput:
    """Validate and trim one input record.

    Raises ``InputError`` with a translation key when the label or target is
    blank, or the launch type is not one this integration knows how to send.
    """
    label = _clean(raw.get(CONF_LABEL))
    if not label:
        raise InputError("blank_label")
    launch_type = _clean(raw.get(CONF_LAUNCH_TYPE)) or LAUNCH_TYPE_URL
    if launch_type not in LAUNCH_TYPES:
        raise InputError("invalid_launch_type")
    launch_target = _clean(raw.get(CONF_LAUNCH_TARGET))
    if not launch_target:
        raise InputError("blank_target")
    app_id = _clean(raw.get(CONF_APP_ID)) or None
    return TvInput(label, launch_type, launch_target, app_id)


def normalise_inputs(
    raw: Iterable[Any] | None,
) -> tuple[list[TvInput], list[tuple[int, str]]]:
    """Normalise a stored list, keeping every usable record.

    Returns the usable inputs in their stored order plus ``(index, code)`` for
    each record that was dropped, so setup can log and carry on rather than
    fail because one entry was hand-edited into nonsense.
    """
    inputs: list[TvInput] = []
    rejected: list[tuple[int, str]] = []
    for index, record in enumerate(raw or ()):
        if not isinstance(record, Mapping):
            rejected.append((index, "invalid_record"))
            continue
        try:
            inputs.append(normalise_input(record))
        except InputError as err:
            rejected.append((index, err.code))
    return inputs, rejected


def duplicate_labels(inputs: Iterable[TvInput]) -> list[str]:
    """Labels that appear more than once, in first-seen order.

    HomeKit keys its input services by name, so a duplicate would collapse
    into one tile and ``source`` could never name the second input.
    """
    seen: set[str] = set()
    duplicates: list[str] = []
    for tv_input in inputs:
        if tv_input.label in seen and tv_input.label not in duplicates:
            duplicates.append(tv_input.label)
        seen.add(tv_input.label)
    return duplicates


def source_list(inputs: Iterable[TvInput]) -> list[str]:
    return [tv_input.label for tv_input in inputs]


def resolve_label(inputs: Iterable[TvInput], label: str) -> TvInput | None:
    """The input HomeKit meant by ``label``; the first match wins on duplicates."""
    for tv_input in inputs:
        if tv_input.label == label:
            return tv_input
    return None


def current_source(
    inputs: Iterable[TvInput], app_id: str | None, app_name: str | None
) -> str | None:
    """The label matching what the child reports as running, or ``None``.

    An explicit ``app_id`` option is the strongest evidence, then the launch
    target itself (a deep link the child echoes back, or the package id), and
    finally the child's own display name for the app. All comparisons are
    exact after trimming; the child decides the casing of what it reports.
    """
    reported = tuple(
        value for value in (_clean(app_id), _clean(app_name)) if value
    )
    if not reported:
        return None
    ranked = list(inputs)
    for pick in (
        lambda item: item.app_id,
        lambda item: item.launch_target,
    ):
        for tv_input in ranked:
            if (value := pick(tv_input)) and value in reported:
                return tv_input.label
    for tv_input in ranked:
        if tv_input.label in reported:
            return tv_input.label
    return None


def normalise_key_map_overrides(raw: Mapping[str, Any] | None) -> dict[str, str]:
    """Keep only overrides for keys HomeKit can actually send, trimmed."""
    overrides: dict[str, str] = {}
    for key, keycode in (raw or {}).items():
        if key in DEFAULT_KEY_MAP and (cleaned := _clean(keycode)):
            overrides[key] = cleaned
    return overrides


def effective_key_map(overrides: Mapping[str, str] | None) -> dict[str, str]:
    return {**DEFAULT_KEY_MAP, **normalise_key_map_overrides(overrides)}


def keycode_for(key_map: Mapping[str, str], key_name: Any) -> str | None:
    """The Android keycode for a HomeKit key name, ``None`` if unknown."""
    if not isinstance(key_name, str):
        return None
    return key_map.get(key_name)


def supported_features(child_features: int | None) -> int:
    """Fixed feature bits, plus VOLUME_SET only if the child advertises it.

    Computed once from the child's capabilities at construction; never from
    its live state, so the value does not change when the child powers off.
    """
    features = BASE_FEATURES
    if child_features and child_features & FEATURE_VOLUME_SET:
        features |= FEATURE_VOLUME_SET
    return features
