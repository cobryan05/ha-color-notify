"""Tests for color_notify light entity behavior."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from conftest import make_config_entry

from custom_components.color_notify.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ColorInfo,
    LIGHT_OFF_SEQUENCE,
    LIGHT_ON_SEQUENCE,
    NotificationLightEntity,
    WARM_WHITE_RGB,
    _NotificationSequence,
)
from custom_components.color_notify.const import DEFAULT_PRIORITY


class FakeState:
    def __init__(self, state: str, attributes: dict | None = None):
        self.state = state
        self.attributes = attributes or {}


def make_entity(is_on=False):
    entry = make_config_entry()

    entity = NotificationLightEntity(
        unique_id="test_id",
        wrapped_entity_id="light.test",
        config_entry=entry,
        log_entity=None,
    )
    entity.hass = MagicMock()

    entity.hass.states.get.return_value = None
    entity.async_write_ha_state = MagicMock()
    entity.async_schedule_update_ha_state = MagicMock()
    entity.async_turn_on = AsyncMock()
    entity.async_turn_off = AsyncMock()
    entity._attr_is_on = is_on
    return entity, entry


class TestWorkerSpawnOrder:
    """Worker task spawns after state restore in async_added_to_hass."""

    async def test_worker_spawns_after_state_restore(self):
        """Background task is created after async_get_last_state completes."""
        entity, entry = make_entity()
        call_order = []

        async def tracked_get_last_state():
            call_order.append("get_last_state")
            return FakeState("on")

        def tracked_create_background_task(hass, coro, name, **kwargs):
            call_order.append("create_background_task")
            coro.close()
            task = MagicMock()
            task.cancel = MagicMock()
            return task

        entity.async_get_last_state = tracked_get_last_state
        entry.async_create_background_task = tracked_create_background_task

        await entity.async_added_to_hass()

        assert call_order.index("create_background_task") > call_order.index(
            "get_last_state"
        )

        await entity.async_will_remove_from_hass()

    async def test_worker_spawns_without_restored_state(self):
        """Background task is created even when there's no restored state."""
        entity, entry = make_entity()
        entity.async_get_last_state = AsyncMock(return_value=None)

        def create_task_mock(hass, coro, name, **kwargs):
            coro.close()
            task = MagicMock()
            task.cancel = MagicMock()
            return task

        entry.async_create_background_task = MagicMock(side_effect=create_task_mock)

        await entity.async_added_to_hass()

        entry.async_create_background_task.assert_called_once()

        await entity.async_will_remove_from_hass()


class TestAsyncToggleDynamicPriority:
    async def test_toggle_on_when_off(self):
        """Toggle turns on when entity is off."""
        entity, entry = make_entity(is_on=False)

        await entity.async_toggle()

        entity.async_turn_on.assert_awaited_once()
        entity.async_turn_off.assert_not_awaited()

    async def test_toggle_off_when_state_on_is_top(self):
        """Toggle turns off when entity is on and STATE_ON is top priority."""
        entity, entry = make_entity(is_on=True)
        entity._active_sequences["on"] = _NotificationSequence(
            notify_id="on",
            pattern=[ColorInfo(WARM_WHITE_RGB, 255)],
            priority=DEFAULT_PRIORITY,
        )
        entity._sort_active_sequences()

        await entity.async_toggle()

        entity.async_turn_off.assert_awaited_once()
        entity.async_turn_on.assert_not_awaited()

    async def test_toggle_on_when_notification_outranks_state_on(self):
        """Toggle turns on when a notification outranks STATE_ON."""
        entity, entry = make_entity(is_on=True)
        entity._active_sequences["on"] = LIGHT_ON_SEQUENCE
        entity._active_sequences["alert"] = _NotificationSequence(
            notify_id="alert",
            pattern=[ColorInfo((255, 0, 0), 255)],
            priority=DEFAULT_PRIORITY + 100,
        )
        entity._sort_active_sequences()

        await entity.async_toggle()

        entity.async_turn_on.assert_awaited_once()
        entity.async_turn_off.assert_not_awaited()


class TestNotificationSequenceColor:
    def test_sequence_initial_color_matches_pattern(self) -> None:
        """A _NotificationSequence constructed with a pattern uses that pattern's color."""
        red = ColorInfo(rgb=(255, 0, 0), brightness=255)
        seq = _NotificationSequence(
            pattern=[red], priority=DEFAULT_PRIORITY, notify_id="on"
        )
        assert seq.color.rgb == (255, 0, 0)


class TestTurnOnColorBrightness:
    def _make_entity(self) -> tuple[NotificationLightEntity, MagicMock]:
        """Entity with real async_turn_on and the OFF sequence pre-loaded."""
        entity, entry = make_entity()
        del entity.async_turn_on
        del entity.async_turn_off
        entity._active_sequences["off"] = LIGHT_OFF_SEQUENCE
        return entity, entry

    async def test_turn_on_with_rgb_color_creates_sequence_with_that_color(self) -> None:
        """async_turn_on(rgb_color=X) queues a sequence whose color matches X."""
        entity, _entry = self._make_entity()
        captured: list[_NotificationSequence] = []

        async def capture_add(notify_id: str, sequence: _NotificationSequence, log_trigger: str | None = None) -> None:
            captured.append(sequence)

        entity._add_sequence = capture_add

        with (
            patch("custom_components.color_notify.light.color_RGB_to_hsv", return_value=(0, 100, 100)),
            patch("custom_components.color_notify.light.color_hsv_to_RGB", return_value=(255, 0, 0)),
        ):
            await entity.async_turn_on(rgb_color=(255, 0, 0))

        assert len(captured) == 1
        assert captured[0].color.rgb == (255, 0, 0)

    async def test_turn_on_with_brightness_creates_sequence_with_dimmed_color(self) -> None:
        """async_turn_on(brightness=128) queues a sequence with a ~50% dimmed color."""
        entity, _entry = self._make_entity()
        entity._last_on_rgb = (255, 0, 0)
        captured: list[_NotificationSequence] = []

        async def capture_add(notify_id: str, sequence: _NotificationSequence, log_trigger: str | None = None) -> None:
            captured.append(sequence)

        entity._add_sequence = capture_add

        with (
            patch("custom_components.color_notify.light.color_RGB_to_hsv", return_value=(0, 100, 100)),
            patch("custom_components.color_notify.light.color_hsv_to_RGB", return_value=(127, 0, 0)),
        ):
            await entity.async_turn_on(brightness=128)

        assert len(captured) == 1
        assert captured[0].color.rgb == (127, 0, 0)


class TestStateAttributesWhenOff:
    """state_attributes must explicitly clear color attributes when the light is off.

    HA's entity framework only merges state_attributes when the dict is truthy.
    An empty dict {} is falsy and is skipped, so the HA state machine retains only
    capability attributes and the frontend has no brightness key to inspect.
    Without an explicit brightness=None, the frontend keeps the last displayed
    brightness value and shows a colored icon + X instead of a grey dimmed icon.
    """

    def test_state_attributes_includes_brightness_as_none_when_off(self) -> None:
        """state_attributes must contain brightness=None when the light is off."""
        entity, _ = make_entity(is_on=False)
        entity._last_on_rgb = (255, 249, 216)  # simulate a prior on-state
        attrs = entity.state_attributes
        assert ATTR_BRIGHTNESS in attrs, (
            "ATTR_BRIGHTNESS must be present (as None) when off so HA merges it "
            "and the frontend shows a grey icon instead of a bright colored icon"
        )
        assert attrs[ATTR_BRIGHTNESS] is None

    def test_state_attributes_includes_color_mode_as_none_when_off(self) -> None:
        """state_attributes must contain color_mode=None when the light is off."""
        entity, _ = make_entity(is_on=False)
        attrs = entity.state_attributes
        assert ATTR_COLOR_MODE in attrs, (
            "ATTR_COLOR_MODE must be present (as None) when off so the frontend "
            "knows this is a color-capable light in the off state"
        )
        assert attrs[ATTR_COLOR_MODE] is None


class TestWarmupTimeDetection:
    """_process_sequence_list calls set_initial_hold() on new sequences when the bulb is off.

    The entity checks the real bulb state directly and only calls set_initial_hold()
    when warmup_time > 0 and the bulb is currently off (or state unknown).
    """

    def _make_entity_with_warmup(
        self, warmup_ms: int
    ) -> tuple[NotificationLightEntity, MagicMock]:
        """Return an entity pre-configured with the given warmup_time."""
        entity, entry = make_entity()
        entry.data["warmup_time"] = warmup_ms
        entity._active_sequences["off"] = LIGHT_OFF_SEQUENCE
        entity._wrapped_light_turn_on = AsyncMock(return_value=True)
        entity._log_display_state = MagicMock()
        return entity, entry

    def _add_alert_seq(self, entity: NotificationLightEntity) -> _NotificationSequence:
        """Insert a high-priority alert sequence with a mocked run() and return it."""
        seq = _NotificationSequence(
            notify_id="alert",
            pattern=[ColorInfo((255, 0, 0), 255)],
            priority=DEFAULT_PRIORITY,
        )
        seq.run = AsyncMock()
        entity._active_sequences["alert"] = seq
        entity._sort_active_sequences()
        return seq

    async def test_set_initial_hold_called_when_bulb_is_off(self) -> None:
        """When warmup_time=500 ms and bulb is off, set_initial_hold(0.5) is called."""
        entity, _ = self._make_entity_with_warmup(warmup_ms=500)
        entity.hass.states.get.return_value = FakeState("off")
        seq = self._add_alert_seq(entity)

        await entity._process_sequence_list()

        seq.run.assert_awaited_once()
        assert seq._initial_hold_sec == pytest.approx(0.5)

    async def test_no_initial_hold_when_bulb_is_already_on(self) -> None:
        """When the bulb is already on, set_initial_hold() is not called."""
        entity, _ = self._make_entity_with_warmup(warmup_ms=500)
        entity.hass.states.get.return_value = FakeState("on")
        seq = self._add_alert_seq(entity)

        await entity._process_sequence_list()

        seq.run.assert_awaited_once()
        assert seq._initial_hold_sec == 0.0  # default; set_initial_hold never called

    async def test_no_initial_hold_when_warmup_time_not_configured(self) -> None:
        """When warmup_time is absent from config, set_initial_hold() is never called."""
        entity, entry = make_entity()
        # warmup_time deliberately omitted from entry.data
        entity._active_sequences["off"] = LIGHT_OFF_SEQUENCE
        entity._wrapped_light_turn_on = AsyncMock(return_value=True)
        entity._log_display_state = MagicMock()
        entity.hass.states.get.return_value = FakeState("off")
        seq = self._add_alert_seq(entity)

        await entity._process_sequence_list()

        seq.run.assert_awaited_once()
        assert seq._initial_hold_sec == 0.0

    async def test_initial_hold_applied_when_bulb_state_unavailable(self) -> None:
        """State=None (unavailable/unknown) is treated as off — hold time is applied."""
        entity, _ = self._make_entity_with_warmup(warmup_ms=200)
        entity.hass.states.get.return_value = None
        seq = self._add_alert_seq(entity)

        await entity._process_sequence_list()

        seq.run.assert_awaited_once()
        assert seq._initial_hold_sec == pytest.approx(0.2)

    async def test_initial_hold_not_applied_to_already_running_sequence(self) -> None:
        """A sequence already in _running_sequences is not restarted."""
        entity, _ = self._make_entity_with_warmup(warmup_ms=500)
        entity.hass.states.get.return_value = FakeState("off")
        seq = self._add_alert_seq(entity)
        entity._running_sequences["alert"] = seq  # already running

        await entity._process_sequence_list()

        seq.run.assert_not_awaited()


class TestWarmupWorkerBehavior:
    """_NotificationSequence._worker_func holds for _initial_hold_sec after step 1.

    The hold uses asyncio.wait_for(stop_event.wait(), timeout=hold_delay) so it can
    be interrupted immediately when the sequence is stopped mid-warmup.
    """

    def _make_seq_with_hold(self, hold_sec: float) -> _NotificationSequence:
        """Return a sequence with _initial_hold_sec pre-set via set_initial_hold()."""
        seq = _NotificationSequence(
            notify_id="alert",
            pattern=[ColorInfo((255, 0, 0), 255)],
            priority=DEFAULT_PRIORITY,
        )
        seq.set_initial_hold(hold_sec)
        return seq

    async def test_worker_waits_for_initial_hold_after_first_step(self) -> None:
        """Worker calls asyncio.wait_for with timeout=1.5 after the first step."""
        wait_for_timeouts: list[float] = []

        async def fake_wait_for(coro, *, timeout=None):
            wait_for_timeouts.append(timeout)
            coro.close()
            raise asyncio.TimeoutError  # simulate normal warmup completion

        seq = self._make_seq_with_hold(1.5)
        stop_event = asyncio.Event()

        with patch("custom_components.color_notify.light.asyncio.wait_for", side_effect=fake_wait_for):
            await seq._worker_func(stop_event)

        assert 1.5 in wait_for_timeouts, f"Expected hold timeout of 1.5 s; got: {wait_for_timeouts}"

    async def test_worker_skips_hold_when_hold_is_zero(self) -> None:
        """Worker does not call asyncio.wait_for when _initial_hold_sec=0."""
        wait_for_calls: list[float] = []

        async def fake_wait_for(coro, *, timeout=None):
            wait_for_calls.append(timeout)
            coro.close()

        seq = self._make_seq_with_hold(0.0)
        stop_event = asyncio.Event()

        with patch("custom_components.color_notify.light.asyncio.wait_for", side_effect=fake_wait_for):
            await seq._worker_func(stop_event)

        assert wait_for_calls == [], f"Expected no wait_for calls; got: {wait_for_calls}"

    async def test_worker_hold_skipped_when_stop_event_already_set(self) -> None:
        """Hold is skipped entirely when the stop event is already set before the loop runs."""
        wait_for_calls: list[float] = []

        async def fake_wait_for(coro, *, timeout=None):
            wait_for_calls.append(timeout)
            coro.close()

        seq = self._make_seq_with_hold(1.5)
        stop_event = asyncio.Event()
        stop_event.set()  # already cancelled before worker starts

        with patch("custom_components.color_notify.light.asyncio.wait_for", side_effect=fake_wait_for):
            await seq._worker_func(stop_event)

        assert wait_for_calls == [], "Hold wait_for should be skipped when stop_event is pre-set"

    async def test_worker_hold_interrupted_when_stop_fires_during_warmup(self) -> None:
        """Hold exits immediately when stop_event is set mid-warmup (no TimeoutError raised)."""
        wait_for_completed_normally: list[bool] = []

        async def fake_wait_for(coro, *, timeout=None):
            # Simulate stop_event firing: wait_for returns without raising TimeoutError
            coro.close()
            wait_for_completed_normally.append(True)

        seq = self._make_seq_with_hold(10.0)
        stop_event = asyncio.Event()

        with patch("custom_components.color_notify.light.asyncio.wait_for", side_effect=fake_wait_for):
            await seq._worker_func(stop_event)

        assert wait_for_completed_normally == [True], "Hold should return cleanly when stop_event fires mid-warmup"
