"""Tests for color_notify light entity behavior."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.color_notify.light import (
    ColorInfo,
    LIGHT_OFF_SEQUENCE,
    LIGHT_ON_SEQUENCE,
    NotificationLightEntity,
    WARM_WHITE_RGB,
    _NotificationSequence,
)
from custom_components.color_notify.const import DEFAULT_PRIORITY


class FakeState:
    def __init__(self, state: str):
        self.state = state


def make_entity(is_on=False):
    entry = MagicMock()
    entry.data = {
        "type": "light",
        "name": "Test Light",
        "entity_id": "light.test",
        "color_picker": [255, 249, 216],
        "dynamic_priority": True,
        "priority": DEFAULT_PRIORITY,
        "delay": True,
        "delay_time": {"seconds": 5},
        "peek_time": {"seconds": 5},
    }
    entry.options = {}
    entry.title = "[Light] Test Light"
    def _close_coros(*args, **kwargs):
        for arg in args:
            if asyncio.iscoroutine(arg):
                arg.close()

    entry.async_create_background_task = MagicMock(side_effect=_close_coros)
    entry.async_on_unload = MagicMock()

    entity = NotificationLightEntity(
        unique_id="test_id",
        wrapped_entity_id="light.test",
        config_entry=entry,
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

        def tracked_create_background_task(*args, **kwargs):
            call_order.append("create_background_task")
            for arg in args:
                if asyncio.iscoroutine(arg):
                    arg.close()

        entity.async_get_last_state = tracked_get_last_state
        entry.async_create_background_task = tracked_create_background_task

        await entity.async_added_to_hass()

        assert call_order.index("create_background_task") > call_order.index(
            "get_last_state"
        )

    async def test_worker_spawns_without_restored_state(self):
        """Background task is created even when there's no restored state."""
        entity, entry = make_entity()
        entity.async_get_last_state = AsyncMock(return_value=None)

        await entity.async_added_to_hass()

        entry.async_create_background_task.assert_called_once()


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

        async def capture_add(notify_id: str, sequence: _NotificationSequence) -> None:
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

        async def capture_add(notify_id: str, sequence: _NotificationSequence) -> None:
            captured.append(sequence)

        entity._add_sequence = capture_add

        with (
            patch("custom_components.color_notify.light.color_RGB_to_hsv", return_value=(0, 100, 100)),
            patch("custom_components.color_notify.light.color_hsv_to_RGB", return_value=(127, 0, 0)),
        ):
            await entity.async_turn_on(brightness=128)

        assert len(captured) == 1
        assert captured[0].color.rgb == (127, 0, 0)
