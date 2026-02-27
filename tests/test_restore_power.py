"""Tests for restore_power config option (startup white blast fix)."""

from unittest.mock import AsyncMock

import pytest

from custom_components.color_notify.const import CONF_RESTORE_POWER
from tests.support.entity_helpers import FakeState, make_config_entry, make_light_entity


def _make_restore_entity(restore_power: bool | None = None):
    overrides = {}
    if restore_power is not None:
        overrides[CONF_RESTORE_POWER] = restore_power
    entry = make_config_entry(data_overrides=overrides)
    entity = make_light_entity(entry)
    # Restore tests need to intercept async_turn_on/off calls
    entity.async_turn_on = AsyncMock()
    entity.async_turn_off = AsyncMock()
    return entity


async def _simulate_restore(entity, last_state: str | None):
    """Mirrors the restore logic in async_added_to_hass."""
    entity.async_get_last_state = AsyncMock(
        return_value=FakeState(last_state) if last_state else None,
    )
    restored_state = await entity.async_get_last_state()
    if restored_state:
        entity._attr_is_on = restored_state.state == "on"
        entity.async_schedule_update_ha_state(True)
        if entity._restore_power:
            if entity.is_on:
                entity.hass.async_create_task(entity.async_turn_on())
            else:
                entity.hass.async_create_task(entity.async_turn_off())


class TestRestorePowerConfig:

    @pytest.mark.parametrize("restore_power,expected", [
        (None, False),
        (False, False),
        (True, True),
    ], ids=["default_missing", "explicit_false", "explicit_true"])
    def test_restore_power_value(self, restore_power, expected):
        entity = _make_restore_entity(restore_power=restore_power)
        assert entity._restore_power is expected


class TestRestorePowerDisabled:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("last_state", ["on", "off"])
    async def test_no_commands_sent(self, last_state):
        entity = _make_restore_entity(restore_power=False)
        await _simulate_restore(entity, last_state)

        assert entity._attr_is_on == (last_state == "on")
        entity.hass.async_create_task.assert_not_called()


class TestRestorePowerEnabled:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("last_state", ["on", "off"])
    async def test_command_sent(self, last_state):
        entity = _make_restore_entity(restore_power=True)
        await _simulate_restore(entity, last_state)

        assert entity._attr_is_on == (last_state == "on")
        entity.hass.async_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_previous_state_does_nothing(self):
        entity = _make_restore_entity(restore_power=True)
        await _simulate_restore(entity, None)

        entity.hass.async_create_task.assert_not_called()
        entity.async_schedule_update_ha_state.assert_not_called()


class TestStartupQuiet:

    @pytest.mark.parametrize("restore_power,expected_quiet", [
        (False, True),
        (True, False),
    ], ids=["restore_off_quiet_on", "restore_on_quiet_off"])
    def test_startup_quiet_flag(self, restore_power, expected_quiet):
        entity = _make_restore_entity(restore_power=restore_power)
        assert entity._startup_quiet is expected_quiet

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,kwargs", [
        ("_wrapped_light_turn_on", {"rgb_color": (255, 249, 216)}),
        ("_wrapped_light_turn_off", {}),
    ], ids=["turn_on_blocked", "turn_off_blocked"])
    async def test_commands_blocked_during_startup_quiet(self, method, kwargs):
        entity = _make_restore_entity(restore_power=False)
        entity.hass.services.async_call = AsyncMock()

        result = await getattr(entity, method)(**kwargs)
        assert result is True
        entity.hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_commands_allowed_when_restore_power_true(self):
        entity = _make_restore_entity(restore_power=True)
        entity.hass.services.async_call = AsyncMock()

        await entity._wrapped_light_turn_off()
        entity.hass.services.async_call.assert_called_once()
