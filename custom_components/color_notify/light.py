"""Light platform for ColorNotify integration."""

import asyncio
from collections.abc import Callable
from datetime import timedelta
from functools import cached_property
import logging
import time
from typing import Any

import voluptuous as vol

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ATTR_RGB_COLOR,
    ATTR_XY_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_DELAY_TIME,
    CONF_ENTITIES,
    CONF_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    Platform,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_platform, entity_registry as er
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util.color import (
    color_hs_to_RGB,
    color_hs_to_xy,
    color_hsv_to_RGB,
    color_RGB_to_hsv,
    color_temperature_to_rgb,
    color_xy_to_temperature,
)

from .const import (
    CONF_DYNAMIC_PRIORITY,
    CONF_ENABLE_EVENT_LOG,
    CONF_EVENT_ENTITY,
    CONF_EXPIRE_ENABLED,
    CONF_NOTIFY_PATTERN,
    CONF_PEEK_ENABLED,
    CONF_PRIORITY,
    CONF_RGB_SELECTOR,
    CONF_SUBSCRIPTION,
    DEFAULT_PRIORITY,
    EXPECTED_SERVICE_CALL_TIMEOUT,
    INIT_STATE_UPDATE_DELAY_SEC,
    MAX_PREVIEW_DURATION_SEC,
    MAXIMUM_PRIORITY,
    OFF_RGB,
    PREVIEW_NOTIFY_ID,
    SERVICE_PREVIEW_SEQUENCE,
    SERVICE_STOP_PREVIEW,
    TYPE_POOL,
    WARM_WHITE_RGB,
)
from .models import ActiveNotification, NotificationConfig
from .sensor import ColorNotifyLogEntity
from .utils.hass_data import HassData
from .utils.light_sequence import ColorInfo
from .utils.notification_manager import NotificationManager

_LOGGER = logging.getLogger(__name__)


def _NotificationSequence(
    pattern: list,
    priority: int = DEFAULT_PRIORITY,
    notify_id: str | None = None,
    clear_delay: float | None = None,
    peek_enabled: bool = True,
) -> ActiveNotification:
    """Backward-compat factory — prefer ActiveNotification(NotificationConfig(...)) directly."""
    return ActiveNotification(
        NotificationConfig(
            priority=priority,
            notify_id=notify_id,
            pattern=pattern,
            peek_enabled=peek_enabled,
            clear_delay=clear_delay,
        )
    )

# Schema for the preview_sequence entity service.  All fields are optional so
# callers can pass only what they have (e.g. just a pattern, or just a color).
SERVICE_PREVIEW_SEQUENCE_SCHEMA: dict = {
    vol.Optional(CONF_NOTIFY_PATTERN): vol.Any(None, [str]),
    vol.Optional(CONF_RGB_SELECTOR): list,
    vol.Optional(CONF_PRIORITY, default=DEFAULT_PRIORITY): vol.All(
        vol.Coerce(int), vol.Range(min=1, max=MAXIMUM_PRIORITY)
    ),
    vol.Optional(CONF_PEEK_ENABLED, default=True): cv.boolean,
    vol.Optional(CONF_EXPIRE_ENABLED, default=False): cv.boolean,
    vol.Optional(CONF_DELAY_TIME): dict,
}

# Module-level sentinel sequences — always present in every light's queue.
LIGHT_OFF_SEQUENCE = ActiveNotification(
    NotificationConfig(
        notify_id=STATE_OFF,
        pattern=[ColorInfo(OFF_RGB, 0)],
        priority=0,
        peek_enabled=False,
        clear_delay=None,
    )
)
LIGHT_ON_SEQUENCE = ActiveNotification(
    NotificationConfig(
        notify_id=STATE_ON,
        pattern=[ColorInfo(WARM_WHITE_RGB, 255)],
        priority=DEFAULT_PRIORITY,
        peek_enabled=False,
        clear_delay=None,
    )
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize ColorNotify config entry."""
    registry = er.async_get(hass)
    wrapped_entity_id = er.async_validate_entity_id(
        registry, config_entry.data[CONF_ENTITY_ID]
    )
    unique_id = config_entry.entry_id
    runtime_data = HassData.get_config_entry_runtime_data(config_entry.entry_id)
    enable_log = config_entry.options.get(
        CONF_ENABLE_EVENT_LOG,
        config_entry.data.get(CONF_ENABLE_EVENT_LOG, True),
    )
    log_entity: ColorNotifyLogEntity | None = None
    if enable_log:
        log_entity = ColorNotifyLogEntity(unique_id, config_entry)
        runtime_data[CONF_EVENT_ENTITY] = log_entity
    new_entity = NotificationLightEntity(
        unique_id, wrapped_entity_id, config_entry, log_entity
    )
    runtime_data[CONF_ENTITIES] = new_entity
    async_add_entities([new_entity])

    # Register entity services once per domain (idempotent).
    current_platform = entity_platform.async_get_current_platform()
    current_platform.async_register_entity_service(
        SERVICE_PREVIEW_SEQUENCE,
        SERVICE_PREVIEW_SEQUENCE_SCHEMA,
        "async_preview_sequence",
    )
    current_platform.async_register_entity_service(
        SERVICE_STOP_PREVIEW,
        {},
        "async_stop_preview",
    )


class NotificationLightEntity(LightEntity, RestoreEntity):
    """ColorNotify Light entity — thin HA shell backed by NotificationManager."""

    _attr_should_poll = False

    def __init__(
        self,
        unique_id: str,
        wrapped_entity_id: str,
        config_entry: ConfigEntry,
        log_entity: ColorNotifyLogEntity | None,
    ) -> None:
        """Initialize light."""
        super().__init__()
        self._wrapped_entity_id: str = wrapped_entity_id
        self._wrapped_init_done: bool = False
        self._attr_name: str = config_entry.title
        self._attr_unique_id: str = unique_id
        self._config_entry: ConfigEntry = config_entry
        self._event_logger: ColorNotifyLogEntity | None = log_entity

        self._dynamic_priority: bool = config_entry.options.get(
            CONF_DYNAMIC_PRIORITY, True
        )
        self._response_expected_expire_time: float = 0.0
        self._preview_cancel: Callable | None = None

        self._light_on_priority: int = config_entry.options.get(
            CONF_PRIORITY, DEFAULT_PRIORITY
        )
        self._last_on_rgb: tuple = tuple(
            config_entry.data.get(CONF_RGB_SELECTOR, WARM_WHITE_RGB)
        )
        self._last_brightness: int = 255

        # Manager is created here (before hass is available) so that
        # _active_sequences and related attrs exist immediately.
        self._manager = NotificationManager(
            config_entry=config_entry,
            get_hass=lambda: self.hass,
            wrapped_entity_id=wrapped_entity_id,
            on_color_change=lambda **kw: self._wrapped_light_turn_on(**kw),
            event_logger=log_entity,
            entity_name=config_entry.title,
        )

    # ------------------------------------------------------------------
    # Delegation — expose manager internals consumed by tests and entity methods
    # ------------------------------------------------------------------

    @property
    def _active_sequences(self) -> dict[str, ActiveNotification]:
        return self._manager._active_sequences  # noqa: SLF001

    @_active_sequences.setter
    def _active_sequences(self, value: dict[str, ActiveNotification]) -> None:
        self._manager._active_sequences = value  # noqa: SLF001

    @property
    def _running_sequences(self) -> dict[str, ActiveNotification]:
        return self._manager._running_sequences  # noqa: SLF001

    @callback
    def _sort_active_sequences(self) -> None:
        self._manager._sort_active_sequences()  # noqa: SLF001

    @callback
    def _get_top_sequences(self) -> list[ActiveNotification]:
        return self._manager._get_top_sequences()  # noqa: SLF001

    @property
    def _task_queue(self) -> asyncio.Queue:
        return self._manager._task_queue  # noqa: SLF001

    @property
    def _last_set_color(self) -> ColorInfo | None:
        return self._manager._last_set_color  # noqa: SLF001

    @_last_set_color.setter
    def _last_set_color(self, value: ColorInfo | None) -> None:
        self._manager._last_set_color = value  # noqa: SLF001

    async def _reset_running_sequences(self) -> None:
        await self._manager._reset_running_sequences()  # noqa: SLF001

    async def _process_sequence_list(self, log_trigger: str | None = None) -> None:
        await self._manager._process_sequence_list(log_trigger)  # noqa: SLF001

    async def _add_sequence(
        self,
        notify_id: str,
        notification: ActiveNotification,
        log_trigger: str | None = None,
    ) -> None:
        """Enqueue adding a notification sequence."""
        await self._manager.add_notification(notify_id, notification, log_trigger)

    async def _remove_sequence(
        self, notify_id: str, log_trigger: str | None = None
    ) -> None:
        """Enqueue removing a notification sequence."""
        await self._manager.remove_notification(notify_id, log_trigger)

    # ------------------------------------------------------------------
    # HA lifecycle
    # ------------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        """Set up before initially adding to HASS."""
        await super().async_added_to_hass()

        # Add a per-entity 'OFF' sequence so the list is never empty.
        # A fresh instance is created here rather than using the module-level
        # LIGHT_OFF_SEQUENCE singleton; ActiveNotification carries mutable runtime
        # state (_task, _stop_event) so sharing one instance across entities would
        # cause each entity's run() to cancel the previous entity's animation.
        self._active_sequences[STATE_OFF] = ActiveNotification(
            NotificationConfig(
                notify_id=STATE_OFF,
                pattern=[ColorInfo(OFF_RGB, 0)],
                priority=0,
                peek_enabled=False,
                clear_delay=None,
            )
        )

        # Check if the wrapped entity is valid at startup.
        state = self.hass.states.get(self._wrapped_entity_id)
        if state:
            await self._handle_wrapped_light_init()

        # Subscribe to wrapped-light state changes.
        self._config_entry.async_on_unload(
            async_track_state_change_event(
                self.hass, self._wrapped_entity_id, self._handle_wrapped_light_change
            )
        )

        subs = self._config_entry.options.get(CONF_SUBSCRIPTION, {})
        pool_subs: list[str] = subs.get(TYPE_POOL, [])
        entity_subs: list[str] = subs.get(CONF_ENTITIES, [])

        async def delay_fire_initial_events(_) -> None:
            nonlocal pool_subs
            nonlocal entity_subs
            already_fired: set[str] = set()
            for pool in pool_subs:
                for notif in HassData.get_all_entities(self.hass, pool).values():
                    if notif.entity_id in already_fired:
                        continue
                    already_fired.add(notif.entity_id)
                    self.hass.bus.async_fire(
                        "state_changed",
                        {
                            ATTR_ENTITY_ID: notif.entity_id,
                            "new_state": self.hass.states.get(notif.entity_id),
                            "old_state": None,
                        },
                    )
            for entity in entity_subs:
                if entity in already_fired:
                    continue
                already_fired.add(entity)
                new_state = self.hass.states.get(entity)
                if new_state is None:
                    _LOGGER.warning(
                        "%s is missing notification %s", self.entity_id, entity
                    )
                    continue
                self.hass.bus.async_fire(
                    "state_changed",
                    {
                        ATTR_ENTITY_ID: entity,
                        "new_state": new_state,
                        "old_state": None,
                    },
                )

        for pool in pool_subs:
            pool_callbacks: set[Callable] = HassData.get_config_entry_runtime_data(
                pool
            ).setdefault(CONF_SUBSCRIPTION, set())
            pool_callbacks.add(self._handle_notification_change)

        for entity in entity_subs:
            self._config_entry.async_on_unload(
                async_track_state_change_event(
                    self.hass, entity, self._handle_notification_change
                )
            )

        async_call_later(
            self.hass, INIT_STATE_UPDATE_DELAY_SEC, delay_fire_initial_events
        )

        restored_state = await self.async_get_last_state()
        if restored_state:
            self._attr_is_on = restored_state.state == STATE_ON
            if rgb := restored_state.attributes.get(ATTR_RGB_COLOR):
                self._last_on_rgb = tuple(rgb)
            if brightness := restored_state.attributes.get(ATTR_BRIGHTNESS):
                self._last_brightness = int(brightness)
            self.async_schedule_update_ha_state(True)
            if self.is_on:
                self.hass.async_create_task(self.async_turn_on())
            else:
                self.hass.async_create_task(self.async_turn_off())

        # Start the background worker. Must happen after state restore to avoid
        # racing with initialization.
        self._manager.start()

    async def async_will_remove_from_hass(self) -> None:
        """Clean up before removal from HASS."""
        self._manager.stop()

        subs = self._config_entry.options.get(CONF_SUBSCRIPTION, {})
        pool_subs: list[str] = subs.get(TYPE_POOL, [])
        for pool_entry_id in pool_subs:
            pool_callbacks: set[Callable] = HassData.get_config_entry_runtime_data(
                pool_entry_id
            ).setdefault(CONF_SUBSCRIPTION, set())
            pool_callbacks.discard(self._handle_notification_change)

    # ------------------------------------------------------------------
    # Wrapped-light helpers
    # ------------------------------------------------------------------

    def _reset_expected_response_timeout(self) -> None:
        self._response_expected_expire_time = (
            time.time() + EXPECTED_SERVICE_CALL_TIMEOUT
        )

    async def _wrapped_light_turn_on(self, **kwargs: Any) -> bool:
        """Turn on the underlying wrapped light entity."""
        if kwargs.get(ATTR_RGB_COLOR, []) == OFF_RGB:
            return await self._wrapped_light_turn_off()

        if not self._wrapped_init_done:
            _LOGGER.warning(
                "Can't turn on light before it is initialized: %s", self.name
            )
            return False

        if (
            ATTR_RGB_COLOR in kwargs
            and ATTR_BRIGHTNESS not in kwargs
            and ColorMode.RGB not in (self._attr_supported_color_modes or {})
        ):
            # Convert RGB → HS + brightness when the bulb doesn't support RGB natively.
            rgb = kwargs.pop(ATTR_RGB_COLOR)
            h, s, v = color_RGB_to_hsv(*rgb)
            brightness = (255 / 100) * v
            kwargs[ATTR_HS_COLOR] = (h, s)
            kwargs[ATTR_BRIGHTNESS] = brightness

        self._reset_expected_response_timeout()
        await self.hass.services.async_call(
            Platform.LIGHT,
            SERVICE_TURN_ON,
            service_data={ATTR_ENTITY_ID: self._wrapped_entity_id} | kwargs,
        )
        return True

    async def _wrapped_light_turn_off(self, **kwargs: Any) -> bool:
        """Turn off the underlying wrapped light entity."""
        if not self._wrapped_init_done:
            return False
        self._reset_expected_response_timeout()
        await self.hass.services.async_call(
            Platform.LIGHT,
            SERVICE_TURN_OFF,
            service_data={ATTR_ENTITY_ID: self._wrapped_entity_id} | kwargs,
        )
        return True

    # ------------------------------------------------------------------
    # Notification event handlers
    # ------------------------------------------------------------------

    async def _handle_notification_change(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Handle a subscribed notification changing state."""
        notify_id = event.data[CONF_ENTITY_ID]
        if event.data.get("new_state") is None:
            _LOGGER.warning(
                "[%s] No new state for [%s], renamed or deleted?",
                self._config_entry.title,
                notify_id,
            )
            await self._remove_sequence(
                notify_id, log_trigger=f"{notify_id} removed (renamed or deleted)"
            )
            return

        is_on = event.data["new_state"].state == STATE_ON
        friendly = event.data["new_state"].attributes.get("friendly_name") or notify_id
        if is_on:
            if (
                notify_id in self._active_sequences
                and event.data.get("old_state") is None
            ):
                return
            notification = self._create_sequence_from_attr(
                event.data["new_state"].attributes, notify_id
            )
            log_trigger = f"{friendly} (pri {notification.priority}) enabled"
            await self._add_sequence(notify_id, notification, log_trigger=log_trigger)
        else:
            existing_seq = self._active_sequences.get(notify_id)
            if existing_seq is not None:
                p = existing_seq.priority
                natural = p - MAXIMUM_PRIORITY if p > MAXIMUM_PRIORITY else p
                log_trigger = f"{friendly} (pri {natural}) disabled"
                await self._remove_sequence(notify_id, log_trigger=log_trigger)

    async def _handle_wrapped_light_change(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Handle the underlying wrapped light changing state."""
        if event.data["old_state"] is None:
            await self._handle_wrapped_light_init()
        elif time.time() > self._response_expected_expire_time:
            _LOGGER.warning(
                "%s received unexpected event %s", self.entity_id, str(event.data)
            )
            await self._manager._reset_running_sequences()  # noqa: SLF001

    async def _handle_wrapped_light_init(self) -> None:
        """Handle wrapped light entity initializing."""
        entity_registry: er.EntityRegistry = er.async_get(self.hass)
        entity: er.RegistryEntry | None = entity_registry.async_get(
            self._wrapped_entity_id
        )
        if entity:
            self._attr_capability_attributes = dict(entity.capabilities)
            self._attr_supported_color_modes = self._attr_capability_attributes.get(
                "supported_color_modes", set()
            )
            self._wrapped_init_done = True
            self.async_write_ha_state()
            await self._manager._wake_loop()  # noqa: SLF001

    # ------------------------------------------------------------------
    # Sequence factory
    # ------------------------------------------------------------------

    def _create_sequence_from_attr(
        self, attributes: dict[str, Any], notify_id: str | None = None
    ) -> ActiveNotification:
        """Create an ActiveNotification from notification entity attributes."""
        pattern = attributes.get(CONF_NOTIFY_PATTERN)
        if not pattern:
            pattern = [ColorInfo(rgb=attributes.get(CONF_RGB_SELECTOR, WARM_WHITE_RGB))]
        expire_enabled = attributes.get(CONF_EXPIRE_ENABLED, False)
        expire_time = attributes.get(CONF_DELAY_TIME) if expire_enabled else None
        delay_sec: float | None = (
            float(timedelta(**expire_time).seconds) if expire_time else None
        )
        priority = attributes.get(CONF_PRIORITY, DEFAULT_PRIORITY)
        return ActiveNotification(
            NotificationConfig(
                pattern=pattern,
                priority=priority,
                notify_id=notify_id,
                clear_delay=delay_sec,
                peek_enabled=attributes.get(CONF_PEEK_ENABLED, True),
            )
        )

    # ------------------------------------------------------------------
    # HA service handlers
    # ------------------------------------------------------------------

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Handle a turn_on service call."""
        self._attr_is_on = True

        if ATTR_HS_COLOR in kwargs:
            rgb = color_hs_to_RGB(*kwargs[ATTR_HS_COLOR])
        elif ATTR_COLOR_TEMP_KELVIN in kwargs:
            rgb = color_temperature_to_rgb(kwargs[ATTR_COLOR_TEMP_KELVIN])
        elif ATTR_RGB_COLOR in kwargs or ATTR_BRIGHTNESS in kwargs:
            rgb = kwargs.get(ATTR_RGB_COLOR, self._last_on_rgb)
            self._last_brightness = kwargs.get(ATTR_BRIGHTNESS, self._last_brightness)
            v = (100 / 255) * self._last_brightness
            h, s, _ = color_RGB_to_hsv(*rgb)
            rgb = color_hsv_to_RGB(h, s, v)
        else:
            rgb = self._last_on_rgb

        priority = self._light_on_priority
        if self._dynamic_priority:
            priority = max(priority, self._get_top_sequences()[0].priority) + 0.5

        self._last_on_rgb = rgb
        notification = ActiveNotification(
            NotificationConfig(
                pattern=[ColorInfo(rgb=rgb)],
                priority=priority,
                notify_id=STATE_ON,
                peek_enabled=False,
                clear_delay=None,
            )
        )

        await self._add_sequence(STATE_ON, notification, log_trigger="Light turned on")
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Handle a turn_off service call."""
        self._attr_is_on = False
        self.async_write_ha_state()
        await self._remove_sequence(STATE_ON, log_trigger="Light turned off")

    async def async_toggle(self, **kwargs: Any) -> None:
        """Handle a toggle service call."""
        if not self.is_on or (
            self._dynamic_priority
            and self._get_top_sequences()[0].notify_id != STATE_ON
        ):
            await self.async_turn_on(**kwargs)
        else:
            await self.async_turn_off(**kwargs)

    async def async_preview_sequence(self, **kwargs: Any) -> None:
        """Play a preview notification sequence on this light.

        Replaces any currently running preview. Auto-expires after
        MAX_PREVIEW_DURATION_SEC as a safety cap.
        """
        if self._preview_cancel is not None:
            self._preview_cancel()
            self._preview_cancel = None

        await self._remove_sequence(PREVIEW_NOTIFY_ID)
        attrs = {**kwargs, CONF_EXPIRE_ENABLED: False}
        attrs.pop(CONF_DELAY_TIME, None)
        notification = self._create_sequence_from_attr(attrs, PREVIEW_NOTIFY_ID)
        await self._add_sequence(PREVIEW_NOTIFY_ID, notification)

        async def _expire_preview(_: Any) -> None:
            self._preview_cancel = None
            await self._remove_sequence(PREVIEW_NOTIFY_ID)

        self._preview_cancel = async_call_later(
            self.hass, MAX_PREVIEW_DURATION_SEC, _expire_preview
        )

    async def async_stop_preview(self, **kwargs: Any) -> None:
        """Stop any running preview on this light."""
        if self._preview_cancel is not None:
            self._preview_cancel()
            self._preview_cancel = None
        await self._remove_sequence(PREVIEW_NOTIFY_ID)

    # ------------------------------------------------------------------
    # HA entity properties
    # ------------------------------------------------------------------

    @callback
    @staticmethod
    def mix_colors(
        colors: list[ColorInfo], weights: list[float] | None = None
    ) -> ColorInfo:
        """Mix a list of RGB colors with their respective brightness and weight values."""
        if weights is None:
            weights = [1.0] * len(colors)
        total_weight = sum(weights)
        normalized_weights = [w / total_weight for w in weights]
        r_total, g_total, b_total, brightness_total = 0.0, 0.0, 0.0, 0.0
        for color, weight in zip(colors, normalized_weights, strict=True):
            r, g, b = color.rgb
            r_total += r * weight
            g_total += g * weight
            b_total += b * weight
            brightness_total += color.brightness * weight
        r = min(int(round(r_total)), 255)
        g = min(int(round(g_total)), 255)
        b = min(int(round(b_total)), 255)
        brightness_total = min(int(round(brightness_total)), 255)
        return ColorInfo((r, g, b), brightness_total)

    @property
    def capability_attributes(self) -> dict[str, Any] | None:
        """Return capability attributes."""
        return self._attr_capability_attributes

    @property
    def state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        data: dict[str, Any] = {}
        if self.is_on:
            data[ATTR_COLOR_MODE] = ColorMode.RGB
            data[ATTR_RGB_COLOR] = self._last_on_rgb
            h, s, v = color_RGB_to_hsv(*self._last_on_rgb)
            brightness = (255 / 100) * v
            data[ATTR_BRIGHTNESS] = brightness
            x, y = color_hs_to_xy(h, s)
            data[ATTR_XY_COLOR] = (x, y)
            data[ATTR_COLOR_TEMP_KELVIN] = color_xy_to_temperature(x, y)
        else:
            data[ATTR_COLOR_MODE] = None
            data[ATTR_BRIGHTNESS] = None
            data[ATTR_RGB_COLOR] = None
            data[ATTR_XY_COLOR] = None
            data[ATTR_COLOR_TEMP_KELVIN] = None
        return data

    @property
    def color_mode(self) -> ColorMode | str | None:
        """Return the current color mode."""
        return self._attr_color_mode

    @cached_property
    def supported_color_modes(self) -> set[str] | None:
        """Light wrapper expects RGB."""
        return [ColorMode.RGB]
