"""Tests for worker task spawn ordering in async_added_to_hass."""

from unittest.mock import AsyncMock, MagicMock

from custom_components.color_notify.light import NotificationLightEntity


class FakeState:
    def __init__(self, state: str):
        self.state = state


def make_entity():
    entry = MagicMock()
    entry.data = {
        "type": "light",
        "name": "Test Light",
        "entity_id": "light.test",
        "color_picker": [255, 249, 216],
        "dynamic_priority": True,
        "priority": 1000,
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

        assert call_order.index("create_background_task") > call_order.index("get_last_state")

    async def test_worker_spawns_without_restored_state(self):
        """Background task is created even when there's no restored state."""
        entity, entry = make_entity()
        entity.async_get_last_state = AsyncMock(return_value=None)

        await entity.async_added_to_hass()

        entry.async_create_background_task.assert_called_once()
