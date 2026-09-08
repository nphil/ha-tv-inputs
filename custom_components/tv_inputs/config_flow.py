"""Config and options flows for TV Inputs.

The config flow collects the basics and walks the user through adding
inputs; the options flow gives full control afterwards: the same basics, add /
edit / delete inputs, remote-key forwarding and per-key keycode overrides.
Every change reloads the entry through the update listener in ``__init__``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.components.remote import DOMAIN as REMOTE_DOMAIN
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_DEVICE_CLASS,
    CONF_FORWARD_REMOTE_KEYS,
    CONF_INPUTS,
    CONF_KEY_MAP_OVERRIDES,
    CONF_REMOTE_ENTITY,
    CONF_SOURCE_ENTITY,
    DEFAULT_DEVICE_CLASS,
    DEFAULT_FORWARD_REMOTE_KEYS,
    DEVICE_CLASSES,
    DOMAIN,
)
from .logic import (
    CONF_APP_ID,
    CONF_LABEL,
    CONF_LAUNCH_TARGET,
    CONF_LAUNCH_TYPE,
    DEFAULT_KEY_MAP,
    HOMEKIT_KEYS,
    LAUNCH_TYPE_URL,
    LAUNCH_TYPES,
    InputError,
    TvInput,
    normalise_input,
    normalise_inputs,
    normalise_key_map_overrides,
)

# Form-only field names; never persisted.
CONF_INPUT = "input"
CONF_DELETE = "delete"
CONF_KEY = "key"
CONF_KEYCODE = "keycode"
CONF_EDIT_BASICS = "edit_basics"

ADD_INPUT = "add"

# Which form field an InputError belongs to; anything else lands on the form.
_ERROR_FIELDS = {"blank_label": CONF_LABEL, "blank_target": CONF_LAUNCH_TARGET}

_PLACEHOLDERS = {
    "example_url": "https://www.netflix.com/browse",
    "example_app": "com.netflix.ninja",
}


def _basics_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NAME): TextSelector(),
            vol.Required(CONF_SOURCE_ENTITY): EntitySelector(
                EntitySelectorConfig(domain=MEDIA_PLAYER_DOMAIN)
            ),
            vol.Optional(CONF_REMOTE_ENTITY): EntitySelector(
                EntitySelectorConfig(domain=REMOTE_DOMAIN)
            ),
            vol.Required(CONF_DEVICE_CLASS, default=DEFAULT_DEVICE_CLASS): SelectSelector(
                SelectSelectorConfig(
                    options=list(DEVICE_CLASSES),
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key=CONF_DEVICE_CLASS,
                )
            ),
        }
    )


def _input_schema(deletable: bool) -> vol.Schema:
    fields: dict[vol.Marker, Any] = {
        vol.Required(CONF_LABEL): TextSelector(),
        vol.Required(CONF_LAUNCH_TYPE, default=LAUNCH_TYPE_URL): SelectSelector(
            SelectSelectorConfig(
                options=list(LAUNCH_TYPES),
                mode=SelectSelectorMode.DROPDOWN,
                translation_key=CONF_LAUNCH_TYPE,
            )
        ),
        vol.Required(CONF_LAUNCH_TARGET): TextSelector(),
        vol.Optional(CONF_APP_ID): TextSelector(),
    }
    if deletable:
        fields[vol.Optional(CONF_DELETE, default=False)] = BooleanSelector()
    return vol.Schema(fields)


def _basics_from(user_input: Mapping[str, Any]) -> dict[str, Any]:
    basics = {
        CONF_NAME: (user_input.get(CONF_NAME) or "").strip(),
        CONF_SOURCE_ENTITY: user_input[CONF_SOURCE_ENTITY],
        CONF_DEVICE_CLASS: user_input.get(CONF_DEVICE_CLASS, DEFAULT_DEVICE_CLASS),
    }
    if remote := user_input.get(CONF_REMOTE_ENTITY):
        basics[CONF_REMOTE_ENTITY] = remote
    return basics


def _validate_input(
    user_input: Mapping[str, Any], others: list[TvInput]
) -> tuple[TvInput | None, dict[str, str]]:
    """Normalise one form submission and refuse a label already in use."""
    try:
        tv_input = normalise_input(user_input)
    except InputError as err:
        return None, {_ERROR_FIELDS.get(err.code, "base"): err.code}
    if any(other.label == tv_input.label for other in others):
        return None, {CONF_LABEL: "duplicate_label"}
    return tv_input, {}


class TvInputsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Basics, then a menu loop of add-an-input / finish."""

    VERSION = 1

    def __init__(self) -> None:
        self._basics: dict[str, Any] = {}
        self._inputs: list[TvInput] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_NAME].strip():
                errors[CONF_NAME] = "blank_name"
            else:
                # One wrapper per media player: the unique id is the child.
                await self.async_set_unique_id(user_input[CONF_SOURCE_ENTITY])
                self._abort_if_unique_id_configured()
                self._basics = _basics_from(user_input)
                return await self.async_step_inputs()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _basics_schema(), user_input
            ),
            errors=errors,
        )

    async def async_step_inputs(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="inputs",
            menu_options=["input", "finish"],
            description_placeholders={
                "count": str(len(self._inputs)),
                "labels": ", ".join(i.label for i in self._inputs) or "-",
            },
        )

    async def async_step_input(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            tv_input, errors = _validate_input(user_input, self._inputs)
            if tv_input is not None:
                self._inputs.append(tv_input)
                return await self.async_step_inputs()
        return self.async_show_form(
            step_id="input",
            data_schema=self.add_suggested_values_to_schema(
                _input_schema(deletable=False), user_input
            ),
            errors=errors,
            description_placeholders=_PLACEHOLDERS,
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._basics[CONF_NAME],
            data=self._basics,
            options={
                CONF_INPUTS: [i.as_dict() for i in self._inputs],
                CONF_FORWARD_REMOTE_KEYS: DEFAULT_FORWARD_REMOTE_KEYS,
                CONF_KEY_MAP_OVERRIDES: {},
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> TvInputsOptionsFlow:
        return TvInputsOptionsFlow(config_entry)


class TvInputsOptionsFlow(OptionsFlow):
    """Everything editable after setup, staged in memory until saved.

    ``init`` is the hub: pick an input or a remote key to edit, tick
    "edit basics", or just submit to save what has been staged.
    """

    def __init__(self, entry: ConfigEntry) -> None:
        self._basics = _basics_from({CONF_NAME: entry.title, **entry.data})
        self._inputs, _ = normalise_inputs(entry.options.get(CONF_INPUTS))
        self._forward = bool(
            entry.options.get(CONF_FORWARD_REMOTE_KEYS, DEFAULT_FORWARD_REMOTE_KEYS)
        )
        self._overrides = normalise_key_map_overrides(
            entry.options.get(CONF_KEY_MAP_OVERRIDES)
        )
        # Index into self._inputs being edited; None means "add a new one".
        self._editing: int | None = None
        self._key: str | None = None

    def _init_schema(self) -> vol.Schema:
        inputs = [SelectOptionDict(value=ADD_INPUT, label="Add a new input")] + [
            SelectOptionDict(
                value=str(index), label=f"{tv_input.label} ({tv_input.launch_target})"
            )
            for index, tv_input in enumerate(self._inputs)
        ]
        keys = [
            SelectOptionDict(
                value=key,
                label=(
                    f"{key} \u2192 {self._overrides[key]} (custom)"
                    if key in self._overrides
                    else f"{key} \u2192 {DEFAULT_KEY_MAP[key]}"
                ),
            )
            for key in HOMEKIT_KEYS
        ]
        return vol.Schema(
            {
                vol.Optional(CONF_INPUT): SelectSelector(
                    SelectSelectorConfig(
                        options=inputs,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key=CONF_INPUT,
                    )
                ),
                vol.Optional(CONF_KEY): SelectSelector(
                    SelectSelectorConfig(options=keys, mode=SelectSelectorMode.DROPDOWN)
                ),
                vol.Required(
                    CONF_FORWARD_REMOTE_KEYS, default=self._forward
                ): BooleanSelector(),
                vol.Optional(CONF_EDIT_BASICS, default=False): BooleanSelector(),
            }
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._forward = user_input[CONF_FORWARD_REMOTE_KEYS]
            if (choice := user_input.get(CONF_INPUT)) is not None:
                self._editing = None if choice == ADD_INPUT else int(choice)
                return await self.async_step_input()
            if (key := user_input.get(CONF_KEY)) is not None:
                self._key = key
                return await self.async_step_key()
            if user_input.get(CONF_EDIT_BASICS):
                return await self.async_step_basics()
            return self._async_save()
        return self.async_show_form(
            step_id="init",
            data_schema=self._init_schema(),
            description_placeholders={
                "count": str(len(self._inputs)),
                "overrides": str(len(self._overrides)),
            },
        )

    async def async_step_input(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        index = self._editing
        if index is not None and index >= len(self._inputs):
            index = None
        if user_input is not None:
            if index is not None and user_input.get(CONF_DELETE):
                del self._inputs[index]
                return await self.async_step_init()
            others = [
                tv_input
                for position, tv_input in enumerate(self._inputs)
                if position != index
            ]
            tv_input, errors = _validate_input(user_input, others)
            if tv_input is not None:
                if index is None:
                    self._inputs.append(tv_input)
                else:
                    self._inputs[index] = tv_input
                return await self.async_step_init()
        suggested: Mapping[str, Any] | None = user_input
        if suggested is None and index is not None:
            suggested = self._inputs[index].as_dict()
        return self.async_show_form(
            step_id="input",
            data_schema=self.add_suggested_values_to_schema(
                _input_schema(deletable=index is not None), suggested
            ),
            errors=errors,
            description_placeholders=_PLACEHOLDERS,
        )

    async def async_step_key(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        key = self._key
        if key not in DEFAULT_KEY_MAP:
            return await self.async_step_init()
        if user_input is not None:
            keycode = (user_input.get(CONF_KEYCODE) or "").strip()
            if keycode and keycode != DEFAULT_KEY_MAP[key]:
                self._overrides[key] = keycode
            else:
                self._overrides.pop(key, None)
            return await self.async_step_init()
        return self.async_show_form(
            step_id="key",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Optional(CONF_KEYCODE): TextSelector()}),
                {CONF_KEYCODE: self._overrides.get(key, "")},
            ),
            description_placeholders={
                "key": key,
                "default": DEFAULT_KEY_MAP[key],
                "current": self._overrides.get(key, DEFAULT_KEY_MAP[key]),
            },
        )

    async def async_step_basics(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            source = user_input[CONF_SOURCE_ENTITY]
            taken = any(
                entry.entry_id != self.config_entry.entry_id
                and entry.unique_id == source
                for entry in self.hass.config_entries.async_entries(DOMAIN)
            )
            if not user_input[CONF_NAME].strip():
                errors[CONF_NAME] = "blank_name"
            elif taken:
                errors[CONF_SOURCE_ENTITY] = "already_configured"
            else:
                self._basics = _basics_from(user_input)
                return await self.async_step_init()
        return self.async_show_form(
            step_id="basics",
            data_schema=self.add_suggested_values_to_schema(
                _basics_schema(), user_input or self._basics
            ),
            errors=errors,
        )

    @callback
    def _async_save(self) -> ConfigFlowResult:
        """Persist everything in one entry update.

        Basics live in ``entry.data`` (plus the title and unique id), which the
        options flow manager cannot write, so the whole entry is updated here.
        The manager then stores the identical options, which async_update_entry
        treats as unchanged: exactly one reload per save.
        """
        options = {
            CONF_INPUTS: [tv_input.as_dict() for tv_input in self._inputs],
            CONF_FORWARD_REMOTE_KEYS: self._forward,
            CONF_KEY_MAP_OVERRIDES: dict(self._overrides),
        }
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data=self._basics,
            options=options,
            title=self._basics[CONF_NAME],
            unique_id=self._basics[CONF_SOURCE_ENTITY],
        )
        return self.async_create_entry(title="", data=options)
