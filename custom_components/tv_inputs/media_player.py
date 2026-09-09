"""The wrapper media player: a child player plus a HomeKit-ready input list."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.components.media_player import (
    ATTR_APP_ID,
    ATTR_APP_NAME,
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_CONTENT_TYPE,
    ATTR_MEDIA_TITLE,
    ATTR_MEDIA_VOLUME_LEVEL,
    ATTR_MEDIA_VOLUME_MUTED,
    DATA_COMPONENT,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    SERVICE_PLAY_MEDIA,
    BrowseError,
    BrowseMedia,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.components.remote import (
    DOMAIN as REMOTE_DOMAIN,
    SERVICE_SEND_COMMAND,
)
from homeassistant.const import (
    ATTR_COMMAND,
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    SERVICE_MEDIA_NEXT_TRACK,
    SERVICE_MEDIA_PAUSE,
    SERVICE_MEDIA_PLAY,
    SERVICE_MEDIA_PLAY_PAUSE,
    SERVICE_MEDIA_PREVIOUS_TRACK,
    SERVICE_MEDIA_STOP,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    SERVICE_VOLUME_DOWN,
    SERVICE_VOLUME_MUTE,
    SERVICE_VOLUME_SET,
    SERVICE_VOLUME_UP,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from . import TvInputsConfig, TvInputsConfigEntry
from .const import (
    ATTR_KEY_NAME,
    BACK_DOUBLE_SECONDS,
    DOMAIN,
    EVENT_HOMEKIT_TV_REMOTE_KEY_PRESSED,
    INPUT_CYCLE_DEBOUNCE_SECONDS,
    KEY_REPEAT_GUARD_SECONDS,
    LAUNCH_ATTEMPTS,
    LAUNCH_CONFIRM_SECONDS,
    LAUNCH_POLL_SECONDS,
    POWER_ON_TIMEOUT_SECONDS,
)
from .logic import (
    INFO_CYCLES_INPUTS,
    KEY_BACK,
    KEY_INFORMATION,
    TvInput,
    back_press,
    current_source,
    is_repeat_write,
    keycode_for,
    next_label,
    resolve_label,
    source_list,
    supported_features,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

_NOT_ON = frozenset({MediaPlayerState.OFF, STATE_UNAVAILABLE, STATE_UNKNOWN})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TvInputsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    config = entry.runtime_data
    child = hass.states.get(config.source_entity)
    if child is None:
        # Normal during boot when the child integration loads later; the
        # entity stays unavailable until the child appears. VOLUME_SET is
        # decided now, so a late child that supports it needs a reload.
        _LOGGER.info(
            "%s: %s is not in the state machine yet; following it once it appears",
            entry.title,
            config.source_entity,
        )
    child_features = child.attributes.get(ATTR_SUPPORTED_FEATURES) if child else None
    async_add_entities([TvInputsMediaPlayer(entry, config, child_features)])


class TvInputsMediaPlayer(MediaPlayerEntity):
    """Mirrors the child's state and answers HomeKit's input list."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False

    def __init__(
        self,
        entry: TvInputsConfigEntry,
        config: TvInputsConfig,
        child_features: int | None,
    ) -> None:
        self._config = config
        self._attr_unique_id = entry.entry_id
        self._attr_device_class = MediaPlayerDeviceClass(config.device_class)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=config.name,
            manufacturer="TV Inputs",
            model="HomeKit input wrapper",
        )
        # Fixed for the entity's lifetime and computed from capabilities, not
        # state: HomeKit rebuilds the accessory whenever supported_features
        # changes (homekit/accessories.py RELOAD_ON_CHANGE_ATTRS), which would
        # tear it down every time the child powers off.
        self._attr_supported_features = MediaPlayerEntityFeature(
            supported_features(child_features)
        )
        self._attr_source_list = source_list(config.inputs)
        self._child: State | None = None
        self._power_on = asyncio.Event()
        # Loop-clock stamp of the last back press that opened a double window.
        # Clock of the last back write acted on - kept even when the window
        # closes, so that press's own duplicate still has something to
        # measure against - and, separately, whether the window is open.
        self._last_back: float | None = None
        self._back_window_open = False
        self._last_info: float | None = None
        # The input the info button is walking towards, held through its launch
        # so further presses advance from it instead of from the live app.
        self._cycle_target: str | None = None
        self._cycle_wake = asyncio.Event()
        self._cycle_worker: asyncio.Task[None] | None = None
        self._cycle_launch: asyncio.Task[None] | None = None

    # ----------------------------------------------------------------- state

    @property
    def available(self) -> bool:
        return self._child is not None and self._child.state != STATE_UNAVAILABLE

    @property
    def state(self) -> MediaPlayerState | None:
        if self._child is None or self._child.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        try:
            return MediaPlayerState(self._child.state)
        except ValueError:
            return None

    def _child_attr(self, name: str) -> Any:
        return self._child.attributes.get(name) if self._child is not None else None

    @property
    def volume_level(self) -> float | None:
        return self._child_attr(ATTR_MEDIA_VOLUME_LEVEL)

    @property
    def is_volume_muted(self) -> bool | None:
        return self._child_attr(ATTR_MEDIA_VOLUME_MUTED)

    @property
    def media_title(self) -> str | None:
        return self._child_attr(ATTR_MEDIA_TITLE)

    @property
    def app_id(self) -> str | None:
        return self._child_attr(ATTR_APP_ID)

    @property
    def app_name(self) -> str | None:
        return self._child_attr(ATTR_APP_NAME)

    @property
    def source(self) -> str | None:
        return current_source(self._config.inputs, self.app_id, self.app_name)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "source_entity": self._config.source_entity,
            "remote_entity": self._config.remote_entity,
        }

    # ------------------------------------------------------------- lifecycle

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._async_apply_child(self.hass.states.get(self._config.source_entity))
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._config.source_entity], self._async_child_changed
            )
        )
        if self._config.forward_remote_keys and self._config.remote_entity:
            self.async_on_remove(
                self.hass.bus.async_listen(
                    EVENT_HOMEKIT_TV_REMOTE_KEY_PRESSED,
                    self._async_remote_key_pressed,
                    event_filter=self._async_is_my_key,
                )
            )
            self.async_on_remove(self._async_abandon_cycle)

    @callback
    def _async_abandon_cycle(self) -> None:
        """Drop a pending or running cycle.

        Saving options reloads the entry, so a debounce or a launch that is
        still confirming belongs to an entity that is going away: left alone,
        its poll would keep running and could land a launch after the new
        entity is already up.
        """
        self._cycle_target = None
        self._cycle_wake.clear()
        for task in (self._cycle_launch, self._cycle_worker):
            if task is not None and not task.done():
                task.cancel()
        self._cycle_launch = None
        self._cycle_worker = None

    @callback
    def _async_apply_child(self, state: State | None) -> None:
        self._child = state
        if state is not None and state.state not in _NOT_ON:
            self._power_on.set()

    @callback
    def _async_child_changed(self, event: Event[EventStateChangedData]) -> None:
        self._async_apply_child(event.data["new_state"])
        self.async_write_ha_state()

    # ---------------------------------------------------------- remote keys

    @callback
    def _async_is_my_key(self, data: Mapping[str, Any]) -> bool:
        return data.get(ATTR_ENTITY_ID) == self.entity_id

    async def _async_remote_key_pressed(self, event: Event) -> None:
        key_name = event.data.get(ATTR_KEY_NAME)
        if key_name == KEY_INFORMATION and self._config.info_behaviour == INFO_CYCLES_INPUTS:
            self._async_queue_cycle()
            return
        if key_name == KEY_BACK:
            await self._async_back_pressed()
            return
        keycode = keycode_for(self._config.key_map, key_name)
        if keycode is None:
            _LOGGER.debug("%s: no keycode for HomeKit key %r", self.entity_id, key_name)
            return
        await self._async_send_remote(keycode)

    async def _async_back_pressed(self) -> None:
        """Send back, or home when this press closes a double-press window."""
        now = self.hass.loop.time()
        elapsed = None if self._last_back is None else now - self._last_back
        decision = back_press(
            self._config.key_map,
            self._config.back_behaviour,
            elapsed,
            BACK_DOUBLE_SECONDS,
            KEY_REPEAT_GUARD_SECONDS,
            self._back_window_open,
        )
        if decision.stamp:
            self._last_back = now
        self._back_window_open = decision.window_open
        if decision.keycode is None:
            _LOGGER.debug(
                "%s: ignoring a back write %.2fs after the last as one press",
                self.entity_id,
                elapsed or 0.0,
            )
            return
        await self._async_send_remote(decision.keycode)

    # -------------------------------------------------------- input cycling

    @callback
    def _async_queue_cycle(self) -> None:
        """Advance the target one input; the worker launches where presses stop.

        The next input is taken from the target already queued, never from the
        app the child reports: a launch takes seconds to confirm, so reading
        the live app would make every press inside that window pick the same
        "next" input again. A press arriving while a launch is still being
        confirmed also cancels it - the user has moved on, and sitting through
        the remaining ``LAUNCH_ATTEMPTS * LAUNCH_CONFIRM_SECONDS`` first would
        leave the button feeling dead for up to twelve seconds.
        """
        target = next_label(self._attr_source_list or [], self._cycle_target or self.source)
        if target is None:
            _LOGGER.debug("%s: info pressed with no inputs to cycle", self.entity_id)
            return
        now = self.hass.loop.time()
        if is_repeat_write(
            None if self._last_info is None else now - self._last_info,
            KEY_REPEAT_GUARD_SECONDS,
        ):
            _LOGGER.debug(
                "%s: ignoring a duplicate info write as one press", self.entity_id
            )
            return
        self._last_info = now
        self._cycle_target = target
        if self._cycle_launch is not None and not self._cycle_launch.done():
            self._cycle_launch.cancel()
        self._cycle_wake.set()
        if self._cycle_worker is None or self._cycle_worker.done():
            self._cycle_worker = self.hass.async_create_task(
                self._async_cycle_worker(),
                f"{DOMAIN} cycle inputs {self.entity_id}",
                eager_start=False,
            )

    async def _async_cycle_worker(self) -> None:
        """Settle the presses, launch what they landed on, then repeat."""
        while self._cycle_wake.is_set():
            await self._async_settle_presses()
            target = self._cycle_target
            if target is None:
                return
            self._cycle_launch = self.hass.async_create_task(
                self.async_select_source(target),
                f"{DOMAIN} launch {target}",
                eager_start=False,
            )
            await asyncio.wait({self._cycle_launch})
            launch, self._cycle_launch = self._cycle_launch, None
            if launch.cancelled():
                _LOGGER.debug("%s: launch of %s superseded", self.entity_id, target)
            elif (err := launch.exception()) is not None:
                if not isinstance(err, HomeAssistantError):
                    raise err
                _LOGGER.warning(
                    "%s: could not cycle to %s: %s", self.entity_id, target, err
                )
                self._cycle_target = None
                return
            if self._cycle_target == target:
                self._cycle_target = None

    async def _async_settle_presses(self) -> None:
        """Return once no further press has arrived for the debounce window."""
        while True:
            self._cycle_wake.clear()
            try:
                async with asyncio.timeout(INPUT_CYCLE_DEBOUNCE_SECONDS):
                    await self._cycle_wake.wait()
            except TimeoutError:
                return

    async def _async_send_remote(self, keycode: str) -> bool:
        """Send one keycode to the remote; False if it could not be delivered."""
        remote = self._config.remote_entity
        if not remote:
            return False
        try:
            await self.hass.services.async_call(
                REMOTE_DOMAIN,
                SERVICE_SEND_COMMAND,
                {ATTR_ENTITY_ID: remote, ATTR_COMMAND: keycode},
                blocking=True,
                context=self._context,
            )
        except HomeAssistantError as err:
            _LOGGER.warning("%s: %s did not accept %s: %s", self.entity_id, remote, keycode, err)
            return False
        return True

    # ------------------------------------------------------------- commands

    async def _async_child_call(
        self, service: str, data: Mapping[str, Any] | None = None
    ) -> None:
        await self.hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            service,
            {ATTR_ENTITY_ID: self._config.source_entity, **(data or {})},
            blocking=True,
            context=self._context,
        )

    async def async_select_source(self, source: str) -> None:
        tv_input = resolve_label(self._config.inputs, source)
        if tv_input is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_source",
                translation_placeholders={
                    "source": source,
                    "sources": ", ".join(self._attr_source_list or ()) or "-",
                },
            )
        if self._child is not None and self._child.state == MediaPlayerState.OFF:
            await self._async_wake_child()
        await self._async_launch(tv_input)

    async def _async_launch(self, tv_input: TvInput) -> None:
        """Send the launch, then make sure it actually took.

        A box that has just powered on reports a non-off state while its
        launcher is still coming up, and an intent sent in that window is
        accepted and dropped (seen live on the onn 4K: the deep link left the
        Projectivy launcher in front). There is nothing to wait for that
        distinguishes ready from not-ready, so the launch is verified against
        the app the child reports and sent once more if it did not land.
        """
        for attempt in range(LAUNCH_ATTEMPTS):
            await self._async_child_call(
                SERVICE_PLAY_MEDIA,
                {
                    ATTR_MEDIA_CONTENT_TYPE: tv_input.launch_type,
                    ATTR_MEDIA_CONTENT_ID: tv_input.launch_target,
                },
            )
            if await self._async_launch_landed(tv_input):
                return
            if attempt + 1 < LAUNCH_ATTEMPTS:
                _LOGGER.debug(
                    "%s: %s did not come up, retrying the launch",
                    self.entity_id,
                    tv_input.label,
                )
        _LOGGER.warning(
            "%s: %s did not report as running after %d launch attempts",
            self.entity_id,
            tv_input.label,
            LAUNCH_ATTEMPTS,
        )

    async def _async_launch_landed(self, tv_input: TvInput) -> bool:
        """Poll the child, briefly, for the launched app becoming current.

        Only meaningful when the input carries an app id to compare against;
        without one there is nothing to verify, so the launch is taken at its
        word.
        """
        if not tv_input.app_id:
            return True
        deadline = self.hass.loop.time() + LAUNCH_CONFIRM_SECONDS
        while self.hass.loop.time() < deadline:
            await asyncio.sleep(LAUNCH_POLL_SECONDS)
            child = self.hass.states.get(self._config.source_entity)
            if child is not None and current_source(
                self._config.inputs,
                child.attributes.get(ATTR_APP_ID),
                child.attributes.get(ATTR_APP_NAME),
            ) == tv_input.label:
                return True
        return False

    async def _async_wake_child(self) -> None:
        """Turn the child on and wait, bounded, until it reports so.

        A launch sent while the box is still off is silently dropped (seen
        live on the onn 4K), so the launch is held until the child reports a
        non-off state; after the timeout it is sent regardless.
        """
        self._power_on.clear()
        await self._async_child_call(SERVICE_TURN_ON)
        if self._child is not None and self._child.state not in _NOT_ON:
            return
        try:
            async with asyncio.timeout(POWER_ON_TIMEOUT_SECONDS):
                await self._power_on.wait()
        except TimeoutError:
            _LOGGER.warning(
                "%s: %s did not report on within %.0fs; launching anyway",
                self.entity_id,
                self._config.source_entity,
                POWER_ON_TIMEOUT_SECONDS,
            )

    async def async_turn_on(self) -> None:
        await self._async_child_call(SERVICE_TURN_ON)

    async def async_turn_off(self) -> None:
        await self._async_child_call(SERVICE_TURN_OFF)

    async def async_volume_up(self) -> None:
        await self._async_child_call(SERVICE_VOLUME_UP)

    async def async_volume_down(self) -> None:
        await self._async_child_call(SERVICE_VOLUME_DOWN)

    async def async_mute_volume(self, mute: bool) -> None:
        await self._async_child_call(SERVICE_VOLUME_MUTE, {ATTR_MEDIA_VOLUME_MUTED: mute})

    async def async_set_volume_level(self, volume: float) -> None:
        await self._async_child_call(SERVICE_VOLUME_SET, {ATTR_MEDIA_VOLUME_LEVEL: volume})

    async def async_media_play(self) -> None:
        await self._async_child_call(SERVICE_MEDIA_PLAY)

    async def async_media_pause(self) -> None:
        await self._async_child_call(SERVICE_MEDIA_PAUSE)

    async def async_media_stop(self) -> None:
        await self._async_child_call(SERVICE_MEDIA_STOP)

    async def async_media_next_track(self) -> None:
        await self._async_child_call(SERVICE_MEDIA_NEXT_TRACK)

    async def async_media_previous_track(self) -> None:
        await self._async_child_call(SERVICE_MEDIA_PREVIOUS_TRACK)

    async def async_media_play_pause(self) -> None:
        # androidtv_remote never reports `playing`, so a state-based toggle
        # would always send play. The remote's MEDIA_PLAY_PAUSE key is a real
        # toggle on the box; fall back to the child's service without a remote.
        keycode = keycode_for(self._config.key_map, "play_pause")
        if keycode and await self._async_send_remote(keycode):
            return
        await self._async_child_call(SERVICE_MEDIA_PLAY_PAUSE)

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        await self._async_child_call(
            SERVICE_PLAY_MEDIA,
            {
                ATTR_MEDIA_CONTENT_TYPE: media_type,
                ATTR_MEDIA_CONTENT_ID: media_id,
                **kwargs,
            },
        )

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        child = self.hass.data[DATA_COMPONENT].get_entity(self._config.source_entity)
        if child is None:
            raise BrowseError(f"{self._config.source_entity} is not available to browse")
        return await child.async_browse_media(media_content_type, media_content_id)
