"""Diagnostics: everything needed to explain why an input did or did not map."""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import (
    ATTR_APP_ID,
    ATTR_APP_NAME,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
)
from homeassistant.const import ATTR_SUPPORTED_FEATURES
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er

from . import TvInputsConfigEntry
from .const import DOMAIN
from .logic import DEFAULT_KEY_MAP, current_source, supported_features


def _snapshot(state: State | None) -> dict[str, Any] | None:
    if state is None:
        return None
    return {
        "entity_id": state.entity_id,
        "state": state.state,
        "attributes": dict(state.attributes),
        "last_changed": state.last_changed.isoformat(),
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TvInputsConfigEntry
) -> dict[str, Any]:
    """Nothing here is secret: entity ids, labels and deep links only."""
    config = entry.runtime_data
    child = hass.states.get(config.source_entity)
    remote = hass.states.get(config.remote_entity) if config.remote_entity else None
    child_attrs = child.attributes if child else {}
    wrapper_id = er.async_get(hass).async_get_entity_id(
        MEDIA_PLAYER_DOMAIN, DOMAIN, entry.entry_id
    )
    return {
        "entry": {
            "title": entry.title,
            "unique_id": entry.unique_id,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "resolved": {
            "name": config.name,
            "device_class": config.device_class,
            "inputs": [tv_input.as_dict() for tv_input in config.inputs],
            "forward_remote_keys": config.forward_remote_keys,
            "back_behaviour": config.back_behaviour,
            "info_behaviour": config.info_behaviour,
            "key_map": config.key_map,
            "key_map_overridden": sorted(
                key for key, code in config.key_map.items() if DEFAULT_KEY_MAP[key] != code
            ),
            "supported_features": supported_features(
                child_attrs.get(ATTR_SUPPORTED_FEATURES)
            ),
            "current_source": current_source(
                config.inputs,
                child_attrs.get(ATTR_APP_ID),
                child_attrs.get(ATTR_APP_NAME),
            ),
        },
        "wrapper": _snapshot(hass.states.get(wrapper_id) if wrapper_id else None),
        "child": _snapshot(child),
        "remote": _snapshot(remote),
    }
