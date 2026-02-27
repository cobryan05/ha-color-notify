"""Tests for notification restore — the post-notification state problem.

Problem: After a notification clears, Color Notify restores the wrapped light
to WARM_WHITE_RGB at brightness 255 instead of the actual pre-notification state.

Solution: WrappedLightState tracks the real light state and provides correct
restore_params. The entity uses these instead of the hardcoded LIGHT_ON_SEQUENCE.

These tests validate the integration between WrappedLightState and the entity's
restore logic without running the full worker loop.
"""

import pytest

from custom_components.color_notify.const import CONF_RESTORE_POWER, WARM_WHITE_RGB
from custom_components.color_notify.utils.wrapped_light_state import WrappedLightState
from tests.support.entity_helpers import (
    FakeState,
    make_config_entry,
    make_light_entity,
    simulate_restore,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity(restore_power: bool = False):
    overrides = {CONF_RESTORE_POWER: restore_power, "dynamic_priority": True}
    entry = make_config_entry(data_overrides=overrides)
    entity = make_light_entity(entry)
    entity._startup_quiet = False
    return entity


# ---------------------------------------------------------------------------
# Restore to color_temp (most common Hue scenario)
# ---------------------------------------------------------------------------

class TestRestoreColorTemp:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("brightness,color_temp,label", [
        (150, 370, "warm_2700k"),
        (255, 312, "cool_3200k"),
    ], ids=["warm_2700k", "cool_3200k"])
    async def test_restore_color_temp(self, brightness, color_temp, label):
        entity = _make_entity()

        tracker = WrappedLightState()
        tracker.update(FakeState("on", {
            "brightness": brightness,
            "color_temp": color_temp,
            "color_mode": "color_temp",
        }))
        tracker.freeze()

        await simulate_restore(entity, tracker)

        entity.hass.services.async_call.assert_called_once()
        call_kwargs = entity.hass.services.async_call.call_args
        service_data = call_kwargs[1].get("service_data") or call_kwargs[0][2]
        assert service_data["brightness"] == brightness
        assert service_data["color_temp"] == color_temp
        assert "rgb_color" not in service_data


# ---------------------------------------------------------------------------
# Restore to xy mode (Hue default)
# ---------------------------------------------------------------------------

class TestRestoreXY:

    @pytest.mark.asyncio
    async def test_restore_xy_warm_white(self):
        """Hue light in xy mode (warm white) → notification → restore."""
        entity = _make_entity()

        tracker = WrappedLightState()
        tracker.update(FakeState("on", {
            "brightness": 254,
            "xy_color": [0.4573, 0.41],
            "hs_color": [50.769, 15.294],
            "color_mode": "xy",
        }))
        tracker.freeze()

        await simulate_restore(entity, tracker)

        call_kwargs = entity.hass.services.async_call.call_args
        service_data = call_kwargs[1].get("service_data") or call_kwargs[0][2]
        assert service_data["brightness"] == 254
        assert service_data["xy_color"] == [0.4573, 0.41]
        assert "rgb_color" not in service_data


# ---------------------------------------------------------------------------
# Restore OFF light
# ---------------------------------------------------------------------------

class TestRestoreOff:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("states,label", [
        ([("off", None)], "off_stays_off"),
        ([("on", {"brightness": 100}), ("off", None)], "on_then_off"),
    ], ids=["off_stays_off", "on_then_off"])
    async def test_restore_off_sends_turn_off(self, states, label):
        entity = _make_entity()

        tracker = WrappedLightState()
        for state_str, attrs in states:
            tracker.update(FakeState(state_str, attrs))
        tracker.freeze()

        await simulate_restore(entity, tracker)

        assert entity.hass.services.async_call.call_count == 1
        call_args = entity.hass.services.async_call.call_args[0]
        assert call_args[1] == "turn_off"


# ---------------------------------------------------------------------------
# Restore brightness-only (Caseta dimmers)
# ---------------------------------------------------------------------------

class TestRestoreBrightnessOnly:

    @pytest.mark.asyncio
    async def test_restore_caseta_dimmer(self):
        """Caseta dimmer: brightness only, no color mode."""
        entity = _make_entity()

        tracker = WrappedLightState()
        tracker.update(FakeState("on", {
            "brightness": 64,
            "color_mode": "brightness",
        }))
        tracker.freeze()

        await simulate_restore(entity, tracker)

        call_kwargs = entity.hass.services.async_call.call_args
        service_data = call_kwargs[1].get("service_data") or call_kwargs[0][2]
        assert service_data["brightness"] == 64
        assert "color_temp" not in service_data
        assert "rgb_color" not in service_data


# ---------------------------------------------------------------------------
# Startup: no commands sent
# ---------------------------------------------------------------------------

class TestStartupNoCommands:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("state,expected_on", [
        ("on", True),
        ("off", False),
    ], ids=["on", "off"])
    async def test_startup_reads_state_only(self, state, expected_on):
        overrides = {CONF_RESTORE_POWER: False, "dynamic_priority": True}
        entry = make_config_entry(data_overrides=overrides)
        entity = make_light_entity(entry)

        tracker = WrappedLightState()
        attrs = {"brightness": 150, "color_temp": 370, "color_mode": "color_temp"} if state == "on" else None
        tracker.update(FakeState(state, attrs))

        assert tracker.has_state is True
        assert tracker.is_on is expected_on
        entity.hass.services.async_call.assert_not_called()


# ---------------------------------------------------------------------------
# Freeze during notification prevents state tracking
# ---------------------------------------------------------------------------

class TestFreezeBlocksTracking:

    @pytest.mark.asyncio
    async def test_notification_changes_ignored_during_freeze(self):
        """State changes during notification don't corrupt restore state."""
        entity = _make_entity()

        tracker = WrappedLightState()

        # Pre-notification: warm white
        tracker.update(FakeState("on", {
            "brightness": 150,
            "color_temp": 370,
            "color_mode": "color_temp",
        }))
        tracker.freeze()

        # Notification sends purple to the light — state changes arrive
        tracker.update(FakeState("on", {
            "brightness": 255,
            "rgb_color": [128, 0, 255],
            "hs_color": [270, 100],
            "color_mode": "hs",
        }))

        # Restore should use pre-notification state, not purple
        await simulate_restore(entity, tracker)

        call_kwargs = entity.hass.services.async_call.call_args
        service_data = call_kwargs[1].get("service_data") or call_kwargs[0][2]
        assert service_data["brightness"] == 150
        assert service_data["color_temp"] == 370
        assert "rgb_color" not in service_data

    @pytest.mark.asyncio
    async def test_multiple_notifications_preserve_original_state(self):
        """Multiple notifications in sequence: always restore to original."""
        entity = _make_entity()

        tracker = WrappedLightState()

        # Original state
        tracker.update(FakeState("on", {
            "brightness": 100,
            "color_temp": 370,
            "color_mode": "color_temp",
        }))
        tracker.freeze()

        # First notification plays purple
        tracker.update(FakeState("on", {
            "brightness": 200,
            "rgb_color": [128, 0, 255],
            "color_mode": "rgb",
        }))
        # Second notification plays green (higher priority)
        tracker.update(FakeState("on", {
            "brightness": 255,
            "rgb_color": [0, 255, 0],
            "color_mode": "rgb",
        }))

        # All notifications clear — restore to ORIGINAL state
        await simulate_restore(entity, tracker)

        call_kwargs = entity.hass.services.async_call.call_args
        service_data = call_kwargs[1].get("service_data") or call_kwargs[0][2]
        assert service_data["brightness"] == 100
        assert service_data["color_temp"] == 370


# ---------------------------------------------------------------------------
# Contrast with old behavior (WARM_WHITE_RGB)
# ---------------------------------------------------------------------------

class TestContrastOldBehavior:

    def test_old_behavior_always_warm_white(self):
        """Document: old code always restores to WARM_WHITE_RGB regardless."""
        from custom_components.color_notify.utils.light_sequence import ColorInfo

        # This is what LIGHT_ON_SEQUENCE.color.light_params returns
        old_restore = ColorInfo(WARM_WHITE_RGB, 255).light_params
        assert old_restore == {"rgb_color": WARM_WHITE_RGB}

    @pytest.mark.asyncio
    async def test_new_behavior_restores_actual_state(self):
        """New code restores the actual pre-notification state."""
        tracker = WrappedLightState()
        tracker.update(FakeState("on", {
            "brightness": 150,
            "color_temp": 370,
            "color_mode": "color_temp",
        }))
        tracker.freeze()

        new_restore = tracker.restore_params
        assert new_restore == {"brightness": 150, "color_temp": 370}
