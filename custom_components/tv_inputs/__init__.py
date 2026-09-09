"""TV Inputs.

Wraps an existing media player (typically Android TV Remote) in one entity
that carries a HomeKit-ready input list: ``source_list`` is the configured
labels, ``select_source`` launches the matching deep link or package on the
child, and HomeKit remote keys are forwarded to a remote entity. Everything is
configured through the UI; there is no YAML path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_BACK_BEHAVIOUR,
    CONF_DEVICE_CLASS,
    CONF_FORWARD_REMOTE_KEYS,
    CONF_INFO_BEHAVIOUR,
    CONF_INPUTS,
    CONF_KEY_MAP_OVERRIDES,
    CONF_REMOTE_ENTITY,
    CONF_SOURCE_ENTITY,
    DEFAULT_DEVICE_CLASS,
    DEFAULT_FORWARD_REMOTE_KEYS,
    DEVICE_CLASSES,
)
from .logic import (
    BACK_BEHAVIOURS,
    BACK_SENDS_BACK,
    INFO_BEHAVIOURS,
    INFO_SENDS_INFO,
    TvInput,
    effective_key_map,
    normalise_behaviour,
    normalise_inputs,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER]


@dataclass(frozen=True, slots=True)
class TvInputsConfig:
    """The entry's data and options, validated once per (re)load."""

    name: str
    source_entity: str
    remote_entity: str | None
    device_class: str
    inputs: list[TvInput]
    forward_remote_keys: bool
    back_behaviour: str = BACK_SENDS_BACK
    info_behaviour: str = INFO_SENDS_INFO
    key_map: dict[str, str] = field(default_factory=dict)


TvInputsConfigEntry = ConfigEntry[TvInputsConfig]


def resolve_config(entry: ConfigEntry) -> TvInputsConfig:
    """Read the entry, dropping (and logging) any input that cannot be used.

    A hand-edited or half-migrated option must never keep the whole entry from
    loading; the entity degrades to the inputs that are still valid.
    """
    data: dict[str, Any] = {**entry.data, **entry.options}
    inputs, rejected = normalise_inputs(data.get(CONF_INPUTS))
    for index, code in rejected:
        _LOGGER.warning(
            "%s: ignoring input #%d in options (%s)", entry.title, index + 1, code
        )
    device_class = data.get(CONF_DEVICE_CLASS, DEFAULT_DEVICE_CLASS)
    if device_class not in DEVICE_CLASSES:
        _LOGGER.warning(
            "%s: unknown device class %r, using %s",
            entry.title,
            device_class,
            DEFAULT_DEVICE_CLASS,
        )
        device_class = DEFAULT_DEVICE_CLASS
    return TvInputsConfig(
        name=data.get(CONF_NAME) or entry.title,
        source_entity=data[CONF_SOURCE_ENTITY],
        remote_entity=data.get(CONF_REMOTE_ENTITY) or None,
        device_class=device_class,
        inputs=inputs,
        forward_remote_keys=bool(
            data.get(CONF_FORWARD_REMOTE_KEYS, DEFAULT_FORWARD_REMOTE_KEYS)
        ),
        back_behaviour=normalise_behaviour(
            data.get(CONF_BACK_BEHAVIOUR), BACK_BEHAVIOURS, BACK_SENDS_BACK
        ),
        info_behaviour=normalise_behaviour(
            data.get(CONF_INFO_BEHAVIOUR), INFO_BEHAVIOURS, INFO_SENDS_INFO
        ),
        key_map=effective_key_map(data.get(CONF_KEY_MAP_OVERRIDES)),
    )


async def async_setup_entry(hass: HomeAssistant, entry: TvInputsConfigEntry) -> bool:
    entry.runtime_data = resolve_config(entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TvInputsConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options and title changes take effect by rebuilding the entity."""
    await hass.config_entries.async_reload(entry.entry_id)
