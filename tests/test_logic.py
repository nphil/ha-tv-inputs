"""Behavioural tests for the wrapper's pure decisions.

Everything HomeKit-facing that can go wrong without a running Core: which
input a label means, which label the child's app maps back to, which Android
keycode a HomeKit key sends, and that the advertised feature set never moves.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "custom_components" / "tv_inputs")
)

from logic import (  # noqa: E402
    BACK_BEHAVIOURS,
    BACK_DOUBLE_SENDS_HOME,
    BACK_SENDS_BACK,
    BACK_SENDS_HOME,
    BASE_FEATURES,
    DEFAULT_KEY_MAP,
    FEATURE_VOLUME_SET,
    HOMEKIT_KEYS,
    INFO_BEHAVIOURS,
    INFO_SENDS_INFO,
    InputError,
    TvInput,
    back_press,
    current_source,
    duplicate_labels,
    effective_key_map,
    is_repeat_write,
    keycode_for,
    next_label,
    normalise_behaviour,
    normalise_input,
    normalise_inputs,
    normalise_key_map_overrides,
    resolve_label,
    source_list,
    supported_features,
)

# MediaPlayerEntityFeature.SEEK: something a child may advertise that the
# wrapper deliberately never does.
SEEK = 2

NETFLIX = TvInput("Netflix", "url", "https://www.netflix.com/browse", "com.netflix.ninja")
PRIME = TvInput("Prime Video", "url", "https://app.primevideo.com")
PLEX = TvInput("Plex", "app", "com.plexapp.android")
INPUTS = [NETFLIX, PRIME, PLEX]


# --------------------------------------------------------------------------- #
# Label -> launch
# --------------------------------------------------------------------------- #


def test_select_source_resolves_the_configured_launch():
    assert resolve_label(INPUTS, "Plex") is PLEX
    assert resolve_label(INPUTS, "Prime Video").launch_target == "https://app.primevideo.com"


def test_unknown_or_empty_source_resolves_to_nothing():
    assert resolve_label(INPUTS, "Disney+") is None
    assert resolve_label([], "Netflix") is None
    assert source_list([]) == []


def test_source_list_keeps_configured_order():
    assert source_list(INPUTS) == ["Netflix", "Prime Video", "Plex"]


def test_duplicate_labels_resolve_to_the_first_and_are_reported_once():
    twin = TvInput("Netflix", "app", "com.netflix.ninja")
    inputs = [NETFLIX, twin, PRIME, twin]
    assert resolve_label(inputs, "Netflix") is NETFLIX
    assert duplicate_labels(inputs) == ["Netflix"]
    assert duplicate_labels(INPUTS) == []


# --------------------------------------------------------------------------- #
# Child app -> label
# --------------------------------------------------------------------------- #


def test_child_app_id_option_reports_the_input():
    assert current_source(INPUTS, "com.netflix.ninja", None) == "Netflix"


def test_launch_target_is_the_fallback_when_no_app_id_is_configured():
    assert current_source(INPUTS, "com.plexapp.android", "Plex") == "Plex"
    assert current_source(INPUTS, "https://app.primevideo.com", None) == "Prime Video"


def test_child_app_name_matching_the_label_is_the_last_resort():
    assert current_source(INPUTS, "com.amazon.avod", "Prime Video") == "Prime Video"


def test_unknown_app_reports_no_source():
    assert current_source(INPUTS, "com.google.android.youtube.tv", "YouTube") is None
    assert current_source(INPUTS, None, None) is None
    assert current_source(INPUTS, "  ", "") is None
    assert current_source([], "com.netflix.ninja", "Netflix") is None


def test_explicit_app_id_wins_over_another_inputs_target():
    # Two inputs launch the same package; the one that names it as app_id is meant.
    generic = TvInput("Netflix (package)", "app", "com.netflix.ninja")
    assert current_source([generic, NETFLIX], "com.netflix.ninja", None) == "Netflix"


# --------------------------------------------------------------------------- #
# HomeKit keys -> Android keycodes
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("key", "keycode"),
    [
        ("select", "DPAD_CENTER"),
        ("back", "BACK"),
        ("exit", "HOME"),
        ("play_pause", "MEDIA_PLAY_PAUSE"),
        ("arrow_left", "DPAD_LEFT"),
    ],
)
def test_default_key_map_sends_the_proven_keycodes(key, keycode):
    assert keycode_for(effective_key_map(None), key) == keycode


def test_every_homekit_key_has_a_default():
    assert set(HOMEKIT_KEYS) == set(DEFAULT_KEY_MAP)
    assert len(HOMEKIT_KEYS) == 13


def test_override_replaces_only_its_own_key():
    key_map = effective_key_map({"exit": "MENU"})
    assert key_map["exit"] == "MENU"
    assert {k: v for k, v in key_map.items() if k != "exit"} == {
        k: v for k, v in DEFAULT_KEY_MAP.items() if k != "exit"
    }


def test_overrides_for_unknown_keys_or_blank_codes_are_dropped():
    assert normalise_key_map_overrides({"volume_up": "VOLUME_UP", "back": " ", "select": " ENTER "}) == {
        "select": "ENTER"
    }
    assert effective_key_map({"volume_up": "VOLUME_UP"}) == dict(DEFAULT_KEY_MAP)


def test_unknown_key_names_map_to_nothing_instead_of_raising():
    key_map = effective_key_map(None)
    assert keycode_for(key_map, "volume_up") is None
    assert keycode_for(key_map, None) is None
    assert keycode_for(key_map, 8) is None


# --------------------------------------------------------------------------- #
# Feature set
# --------------------------------------------------------------------------- #


def test_feature_set_matches_the_proven_universal_player_value():
    # 155577 is what the hand-written YAML player advertised on and off.
    assert BASE_FEATURES == 155577
    assert supported_features(None) == 155577
    assert supported_features(0) == 155577


@pytest.mark.parametrize("child_features", [BASE_FEATURES, 0, 1 | 32 | 128, SEEK, None])
def test_child_capabilities_other_than_volume_set_never_change_the_set(child_features):
    assert supported_features(child_features) == BASE_FEATURES


def test_volume_set_is_added_only_when_the_child_advertises_it():
    assert supported_features(FEATURE_VOLUME_SET) == 155581
    assert supported_features(FEATURE_VOLUME_SET | SEEK) == 155581
    assert supported_features(SEEK) == 155577


# --------------------------------------------------------------------------- #
# Input normalisation
# --------------------------------------------------------------------------- #


def test_blank_label_is_rejected():
    with pytest.raises(InputError) as excinfo:
        normalise_input({"label": "   ", "launch_target": "plex://"})
    assert excinfo.value.code == "blank_label"


def test_blank_target_is_rejected():
    with pytest.raises(InputError) as excinfo:
        normalise_input({"label": "Plex", "launch_type": "url", "launch_target": ""})
    assert excinfo.value.code == "blank_target"


def test_unknown_launch_type_is_rejected():
    with pytest.raises(InputError) as excinfo:
        normalise_input({"label": "Plex", "launch_type": "intent", "launch_target": "plex://"})
    assert excinfo.value.code == "invalid_launch_type"


def test_values_are_trimmed_and_launch_type_defaults_to_deep_link():
    tv_input = normalise_input({"label": " Plex ", "launch_target": " plex:// ", "app_id": " "})
    assert tv_input == TvInput("Plex", "url", "plex://", None)
    assert tv_input.as_dict() == {"label": "Plex", "launch_type": "url", "launch_target": "plex://"}


def test_stored_list_keeps_good_records_in_order_and_names_the_bad_ones():
    inputs, rejected = normalise_inputs(
        [
            NETFLIX.as_dict(),
            {"label": "", "launch_target": "x"},
            "not a record",
            PLEX.as_dict(),
            {"label": "Broken", "launch_target": " "},
        ]
    )
    assert inputs == [NETFLIX, PLEX]
    assert rejected == [(1, "blank_label"), (2, "invalid_record"), (4, "blank_target")]
    assert normalise_inputs(None) == ([], [])


# ------------------------------------------------- back button and cycling

KEY_MAP = dict(DEFAULT_KEY_MAP)
WINDOW = 1.2
GUARD = 0.25


def _press(behaviour, gaps):
    """Replay a series of writes through the real state machine.

    ``gaps[0]`` is the first write (nothing before it); each later entry is
    the seconds since the previous write. The two pieces of state mirror the
    entity's: the clock of the last write *acted on* - a dropped duplicate
    deliberately does not move it - and whether the window is open.
    """
    sent, now, last, window = [], 0.0, None, False
    for index, gap in enumerate(gaps):
        if index:
            now += gap
        since = None if last is None else now - last
        decision = back_press(KEY_MAP, behaviour, since, WINDOW, GUARD, window)
        sent.append(decision.keycode)
        if decision.stamp:
            last = now
        window = decision.window_open
    return sent


def test_default_back_always_sends_back_at_any_deliberate_pace():
    assert _press(BACK_SENDS_BACK, [None, 0.5, WINDOW, 99.0]) == ["BACK"] * 4


def test_home_mode_never_sends_back():
    assert _press(BACK_SENDS_HOME, [None, 0.5, 9.0]) == ["HOME"] * 3


def test_double_mode_sends_back_then_home_then_back_again():
    # Third deliberate press starts over: the window closed on the home press.
    assert _press(BACK_DOUBLE_SENDS_HOME, [None, 0.6, 0.6]) == ["BACK", "HOME", "BACK"]


def test_double_mode_treats_a_slow_second_press_as_a_plain_back():
    assert _press(BACK_DOUBLE_SENDS_HOME, [None, WINDOW + 0.01]) == ["BACK", "BACK"]


# One physical press reaches the accessory as two writes 0.11-0.14 s apart
# (measured live; four pairs in one session, deliberate presses >=0.7 s apart).
@pytest.mark.parametrize("gap", [0.0, 0.11, 0.14, GUARD - 0.001])
@pytest.mark.parametrize(
    "behaviour", [BACK_SENDS_BACK, BACK_DOUBLE_SENDS_HOME, BACK_SENDS_HOME]
)
def test_a_press_arriving_twice_acts_once(behaviour, gap):
    assert _press(behaviour, [None, gap])[1] is None


def test_a_duplicate_does_not_consume_the_double_press_window():
    # Press, its duplicate, then a deliberate second press: home must still
    # fire, measured from the first write rather than from the duplicate.
    assert _press(BACK_DOUBLE_SENDS_HOME, [None, 0.12, 0.5]) == ["BACK", None, "HOME"]


def test_the_home_press_own_duplicate_does_not_send_a_stray_back():
    # The bug this guards: clearing the timestamp when the window closes left
    # the home press's duplicate with nothing to compare against, so it sent
    # BACK on the launcher and re-armed the window.
    assert _press(BACK_DOUBLE_SENDS_HOME, [None, 0.6, 0.12]) == ["BACK", "HOME", None]
    assert _press(BACK_DOUBLE_SENDS_HOME, [None, 0.6, 0.12, 0.5]) == [
        "BACK",
        "HOME",
        None,
        "BACK",
    ]


def test_a_lone_home_write_cannot_be_reached_without_an_open_window():
    # Window state, not elapsed time alone, decides: a first press with a
    # stale-looking gap must never open on home.
    decision = back_press(KEY_MAP, BACK_DOUBLE_SENDS_HOME, 0.5, WINDOW, GUARD, False)
    assert decision.keycode == "BACK"


def test_the_guard_never_swallows_a_first_press_or_a_deliberate_one():
    assert not is_repeat_write(None, GUARD)
    assert not is_repeat_write(GUARD, GUARD)
    assert not is_repeat_write(0.7, GUARD)


def test_a_key_override_decides_what_back_and_home_actually_send():
    overridden = effective_key_map({"back": "ESCAPE", "exit": "MENU"})
    first = back_press(overridden, BACK_DOUBLE_SENDS_HOME, None, WINDOW, GUARD, False)
    assert first.keycode == "ESCAPE"
    second = back_press(overridden, BACK_DOUBLE_SENDS_HOME, 0.5, WINDOW, GUARD, True)
    assert second.keycode == "MENU"


def test_cycling_wraps_and_starts_from_the_first_input_when_nothing_matches():
    labels = ["Netflix", "Plex", "Apple TV"]
    assert next_label(labels, None) == "Netflix"
    assert next_label(labels, "Netflix") == "Plex"
    assert next_label(labels, "Apple TV") == "Netflix"
    assert next_label(labels, "Some launcher") == "Netflix"
    assert next_label([], "Netflix") is None
    assert next_label(["Plex"], "Plex") == "Plex"


@pytest.mark.parametrize("stored", [None, "", "nonsense", 7, {"a": 1}])
def test_unknown_or_missing_behaviours_fall_back_to_the_android_defaults(stored):
    assert normalise_behaviour(stored, BACK_BEHAVIOURS, BACK_SENDS_BACK) == BACK_SENDS_BACK
    assert normalise_behaviour(stored, INFO_BEHAVIOURS, INFO_SENDS_INFO) == INFO_SENDS_INFO


def test_stored_behaviours_survive_a_round_trip():
    for value in BACK_BEHAVIOURS:
        assert normalise_behaviour(value, BACK_BEHAVIOURS, BACK_SENDS_BACK) == value
    for value in INFO_BEHAVIOURS:
        assert normalise_behaviour(value, INFO_BEHAVIOURS, INFO_SENDS_INFO) == value
