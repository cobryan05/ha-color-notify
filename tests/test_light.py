"""Tests for async_toggle with dynamic_priority enabled."""

from unittest.mock import AsyncMock, MagicMock
from custom_components.color_notify.light import NotificationLightEntity


class FakeState:
    def __init__(self, state: str):
        self.state = state


from custom_components.color_notify.light import (
    ColorInfo,
    LIGHT_ON_SEQUENCE,
    NotificationLightEntity,
    WARM_WHITE_RGB,
    _NotificationSequence,
)
from custom_components.color_notify.const import DEFAULT_PRIORITY


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
    entry.async_create_background_task = MagicMock()
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
