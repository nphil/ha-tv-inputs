"""Constants for the Home Assistant side of TV Inputs.

The input record vocabulary (labels, launch types, key map) lives in
``logic.py`` so it stays importable without Core.
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "tv_inputs"

CONF_SOURCE_ENTITY: Final = "source_entity"
CONF_REMOTE_ENTITY: Final = "remote_entity"
CONF_DEVICE_CLASS: Final = "device_class"
CONF_INPUTS: Final = "inputs"
CONF_FORWARD_REMOTE_KEYS: Final = "forward_remote_keys"
CONF_KEY_MAP_OVERRIDES: Final = "key_map_overrides"
CONF_BACK_BEHAVIOUR: Final = "back_behaviour"
CONF_INFO_BEHAVIOUR: Final = "info_behaviour"

DEVICE_CLASS_TV: Final = "tv"
DEVICE_CLASS_RECEIVER: Final = "receiver"
DEVICE_CLASSES: Final = (DEVICE_CLASS_TV, DEVICE_CLASS_RECEIVER)

DEFAULT_DEVICE_CLASS: Final = DEVICE_CLASS_TV
DEFAULT_FORWARD_REMOTE_KEYS: Final = True

# Fired by the HomeKit Television accessory for keys it cannot map to a
# media_player service itself (homeassistant/components/homekit/const.py).
EVENT_HOMEKIT_TV_REMOTE_KEY_PRESSED: Final = "homekit_tv_remote_key_pressed"
ATTR_KEY_NAME: Final = "key_name"

# Upper bound on waiting for the child to report on before launching an input.
POWER_ON_TIMEOUT_SECONDS: Final = 15.0

# A box that has just woken reports a non-off state before its launcher can
# accept an intent, so a launch is confirmed against the app the child reports
# and sent again if it did not land.
LAUNCH_ATTEMPTS: Final = 2
LAUNCH_CONFIRM_SECONDS: Final = 6.0
LAUNCH_POLL_SECONDS: Final = 0.5

# How long after a back press a second one counts as "get me out of here".
# Android's own double-back-to-exit prompts use about two seconds; this is
# deliberately shorter so a genuine walk back through an app's own stack at a
# normal pace is never mistaken for it.
BACK_DOUBLE_SECONDS: Final = 1.2

# A single press on Apple's remote can reach the accessory as two RemoteKey
# writes ~0.12 s apart (measured live). A repeat of the same key inside this
# guard is that duplicate, not a second press. Deliberately applied only to
# back and info, whose second press means something different from the first;
# arrow keys are left alone because a genuine burst of them is how a swipe in
# the touch area arrives.
KEY_REPEAT_GUARD_SECONDS: Final = 0.25

# Presses of the info button are collected for this long before the input is
# launched, so three quick taps move three inputs along instead of sitting
# through three launches.
INPUT_CYCLE_DEBOUNCE_SECONDS: Final = 0.9
