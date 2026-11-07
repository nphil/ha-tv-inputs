"""Smoke tests against a real Home Assistant core.

``test_logic.py`` covers the decisions without Home Assistant. These check what
it cannot: that every Home Assistant API the integration imports still exists in
the installed core, that the config flow and options flow run, and that the
wrapper entity mirrors its child, forwards commands, answers HomeKit keys and
survives its entity id being changed. They run in CI against stable and beta
Home Assistant, which is what warns before a release breaks the integration.
"""

from __future__ import annotations

from pytest_homeassistant.common import MockConfigEntry, async_mock_service

from homeassistant.components.media_player import (
    ATTR_APP_ID,
    DATA_COMPONENT,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

import pytest

from custom_components.tv_inputs.const import (
    ATTR_KEY_NAME,
    CONF_DEVICE_CLASS,
    CONF_FORWARD_REMOTE_KEYS,
    CONF_INPUTS,
    CONF_REMOTE_ENTITY,
    CONF_SOURCE_ENTITY,
    DOMAIN,
    EVENT_HOMEKIT_TV_REMOTE_KEY_PRESSED,
)

CHILD = "media_player.living_room_tv_child"
REMOTE = "remote.living_room_tv"
INPUTS = [
    {
        "label": "Netflix",
        "launch_type": "url",
        "launch_target": "https://www.netflix.com/browse",
    },
    {"label": "YouTube", "launch_type": "app", "launch_target": "com.google.android.youtube.tv"},
]
CHILD_FEATURES = 2048 | 128 | 256 | 512 | 4 | 8


def _entry(**options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Living room TV",
        unique_id=CHILD,
        data={
            "name": "Living room TV",
            CONF_SOURCE_ENTITY: CHILD,
            CONF_REMOTE_ENTITY: REMOTE,
            CONF_DEVICE_CLASS: "tv",
        },
        options={CONF_INPUTS: INPUTS, CONF_FORWARD_REMOTE_KEYS: True, **options},
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    hass.states.async_set(
        CHILD, "on", {"supported_features": CHILD_FEATURES, "volume_level": 0.3}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    entity_id = er.async_get(hass).async_get_entity_id(
        MEDIA_PLAYER_DOMAIN, DOMAIN, entry.entry_id
    )
    assert entity_id is not None
    return entity_id


async def test_config_flow_creates_a_wrapper(hass: HomeAssistant) -> None:
    hass.states.async_set(CHILD, "on", {"supported_features": CHILD_FEATURES})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Living room TV", CONF_SOURCE_ENTITY: CHILD, CONF_DEVICE_CLASS: "tv"},
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "inputs"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "input"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "input"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "label": "Netflix",
            "launch_type": "url",
            "launch_target": "https://www.netflix.com/browse",
        },
    )
    assert result["step_id"] == "inputs"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    (entry,) = hass.config_entries.async_entries(DOMAIN)
    assert entry.unique_id == CHILD
    assert entry.state is ConfigEntryState.LOADED
    entity_id = er.async_get(hass).async_get_entity_id(
        MEDIA_PLAYER_DOMAIN, DOMAIN, entry.entry_id
    )
    assert hass.states.get(entity_id).attributes["source_list"] == ["Netflix"]


async def test_a_second_wrapper_for_the_same_player_is_refused(
    hass: HomeAssistant,
) -> None:
    _entry().add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Again", CONF_SOURCE_ENTITY: CHILD, CONF_DEVICE_CLASS: "tv"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_entity_mirrors_the_child_and_unloads(hass: HomeAssistant) -> None:
    entry = _entry()
    entity_id = await _setup(hass, entry)

    state = hass.states.get(entity_id)
    assert state.state == "on"
    assert state.attributes["source_list"] == ["Netflix", "YouTube"]
    assert state.attributes["volume_level"] == 0.3

    hass.states.async_set(
        CHILD,
        "on",
        {
            "supported_features": CHILD_FEATURES,
            ATTR_APP_ID: "com.google.android.youtube.tv",
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).attributes["source"] == "YouTube"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_select_source_launches_on_the_child(hass: HomeAssistant) -> None:
    entity_id = await _setup(hass, _entry())
    calls = async_mock_service(hass, MEDIA_PLAYER_DOMAIN, "play_media")

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN,
        "select_source",
        {"entity_id": entity_id, "source": "Netflix"},
        blocking=True,
    )

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == CHILD
    assert calls[0].data["media_content_id"] == "https://www.netflix.com/browse"

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            "select_source",
            {"entity_id": entity_id, "source": "Nope"},
            blocking=True,
        )


async def test_volume_is_forwarded_to_the_child(hass: HomeAssistant) -> None:
    entity_id = await _setup(hass, _entry())
    wrapper = hass.data[DATA_COMPONENT].get_entity(entity_id)
    # Mocking volume_set replaces the media_player service itself, so the wrapper
    # is driven directly; what it sends to the child is the thing under test.
    calls = async_mock_service(hass, MEDIA_PLAYER_DOMAIN, "volume_set")

    await wrapper.async_set_volume_level(0.5)

    assert [c.data["entity_id"] for c in calls] == [CHILD]
    assert calls[0].data["volume_level"] == 0.5


async def test_homekit_keys_go_to_the_remote_and_follow_an_entity_id_change(
    hass: HomeAssistant,
) -> None:
    entity_id = await _setup(hass, _entry())
    sent = async_mock_service(hass, "remote", "send_command")

    hass.bus.async_fire(
        EVENT_HOMEKIT_TV_REMOTE_KEY_PRESSED,
        {"entity_id": entity_id, ATTR_KEY_NAME: "arrow_up"},
    )
    await hass.async_block_till_done()
    assert [c.data["command"] for c in sent] == ["DPAD_UP"]

    new_id = "media_player.lounge_tv"
    registry = er.async_get(hass)
    registry.async_update_entity(entity_id, new_entity_id=new_id)
    await hass.async_block_till_done()

    # Whether Home Assistant moved the entity in place (2026.11) or removed and
    # re-added it, the wrapper still mirrors the child and answers on the new id.
    assert hass.states.get(entity_id) is None
    assert hass.states.get(new_id).state == "on"
    sent.clear()
    hass.bus.async_fire(
        EVENT_HOMEKIT_TV_REMOTE_KEY_PRESSED,
        {"entity_id": new_id, ATTR_KEY_NAME: "arrow_down"},
    )
    await hass.async_block_till_done()
    assert [c.data["command"] for c in sent] == ["DPAD_DOWN"]


async def test_options_flow_saves_and_reloads_once(hass: HomeAssistant) -> None:
    entry = _entry()
    await _setup(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "back_behaviour": "back",
            "info_behaviour": "info",
            CONF_FORWARD_REMOTE_KEYS: False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.options[CONF_FORWARD_REMOTE_KEYS] is False
    assert len(entry.options[CONF_INPUTS]) == 2
