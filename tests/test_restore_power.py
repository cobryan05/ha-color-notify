"""Tests for startup restore and runtime transparency.

restore_power=False (default): Reads the wrapped light's actual state,
seeds _last_on_rgb/_last_brightness from it, sends no commands. Transparent.

restore_power=True (opt-in): Uses cached state from async_get_last_state,
seeds tracking from it, and sends turn_on/turn_off to the real light.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.color_notify.const import CONF_RESTORE_POWER


class FakeState:
    """Minimal state object for async_get_last_state or hass.states.get."""

    def __init__(self, state: str, attributes: dict | None = None):
        self.state = state
        self.attributes = attributes or {}


def make_config_entry(restore_power: bool | None = None):
    """Create a mock config entry with optional restore_power setting."""
    entry = MagicMock()
    data = {
        "type": "light",
        "name": "Test Light",
        "entity_id": "light.test_real_light",
        "color_picker": [255, 249, 216],
        "dynamic_priority": True,
        "priority": 1000,
        "delay": True,
        "delay_time": {"seconds": 5},
        "peek_time": {"seconds": 5},
    }
    if restore_power is not None:
        data[CONF_RESTORE_POWER] = restore_power
    entry.data = data
    entry.options = {}
    entry.title = "[Light] Test Light"
    entry.async_create_background_task = MagicMock()
    entry.async_on_unload = MagicMock()
    return entry


def make_light_entity(
    config_entry: MagicMock,
    wrapped_state: FakeState | str | None = None,
    restored_state: FakeState | str | None = None,
):
    from custom_components.color_notify.light import NotificationLightEntity

    entity = NotificationLightEntity(
        unique_id="test_unique_id",
        wrapped_entity_id="light.test_real_light",
        config_entry=config_entry,
    )

    # Mock HA internals
    entity.hass = MagicMock()

    # Set up hass.states.get to return wrapped light state
    if wrapped_state is not None:
        if isinstance(wrapped_state, str):
            wrapped_state = FakeState(wrapped_state)
        entity.hass.states.get.return_value = wrapped_state
    else:
        entity.hass.states.get.return_value = None

    entity.hass.bus.async_fire = MagicMock()
    entity.hass.async_create_task = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity.async_schedule_update_ha_state = MagicMock()

    # Mock async_get_last_state for cached restore state
    if restored_state is not None:
        if isinstance(restored_state, str):
            restored_state = FakeState(restored_state)
        entity.async_get_last_state = AsyncMock(return_value=restored_state)
    else:
        entity.async_get_last_state = AsyncMock(return_value=None)

    # Mock turn_on/turn_off to track calls
    entity.async_turn_on = AsyncMock()
    entity.async_turn_off = AsyncMock()

    return entity


# -- _seed_from_state --


class TestSeedFromState:
    """_seed_from_state correctly updates _last_on_rgb and _last_brightness."""

    def test_seeds_rgb_and_brightness(self):
        config_entry = make_config_entry()
        entity = make_light_entity(config_entry)
        state = FakeState("on", {"rgb_color": (255, 0, 0), "brightness": 128})

        entity._seed_from_state(state)

        assert entity._last_on_rgb == (255, 0, 0)
        assert entity._last_brightness == 128

    def test_none_state_is_noop(self):
        config_entry = make_config_entry()
        entity = make_light_entity(config_entry)
        original_rgb = entity._last_on_rgb
        original_brightness = entity._last_brightness

        entity._seed_from_state(None)

        assert entity._last_on_rgb == original_rgb
        assert entity._last_brightness == original_brightness

    def test_partial_attributes_brightness_only(self):
        config_entry = make_config_entry()
        entity = make_light_entity(config_entry)
        original_rgb = entity._last_on_rgb
        state = FakeState("on", {"brightness": 64})

        entity._seed_from_state(state)

        assert entity._last_on_rgb == original_rgb  # unchanged
        assert entity._last_brightness == 64

    def test_partial_attributes_rgb_only(self):
        config_entry = make_config_entry()
        entity = make_light_entity(config_entry)
        original_brightness = entity._last_brightness
        state = FakeState("on", {"rgb_color": (0, 255, 0)})

        entity._seed_from_state(state)

        assert entity._last_on_rgb == (0, 255, 0)
        assert entity._last_brightness == original_brightness  # unchanged

    def test_empty_attributes(self):
        config_entry = make_config_entry()
        entity = make_light_entity(config_entry)
        original_rgb = entity._last_on_rgb
        original_brightness = entity._last_brightness
        state = FakeState("on", {})

        entity._seed_from_state(state)

        assert entity._last_on_rgb == original_rgb
        assert entity._last_brightness == original_brightness

    def test_state_without_attributes_attr(self):
        """State object without .attributes attribute (edge case)."""
        config_entry = make_config_entry()
        entity = make_light_entity(config_entry)
        original_rgb = entity._last_on_rgb

        class BareState:
            state = "on"

        entity._seed_from_state(BareState())
        assert entity._last_on_rgb == original_rgb


# -- Startup restore --


class TestRestorePowerDefault:
    """Default behavior (restore_power=False) - transparent, reads real light."""

    def test_default_is_false(self):
        config_entry = make_config_entry(restore_power=None)
        entity = make_light_entity(config_entry)
        assert entity._restore_power is False

    def test_explicit_false(self):
        config_entry = make_config_entry(restore_power=False)
        entity = make_light_entity(config_entry)
        assert entity._restore_power is False

    @pytest.mark.asyncio
    async def test_reads_real_light_on(self):
        """When real light is ON, wrapper state is ON, no commands sent."""
        config_entry = make_config_entry(restore_power=False)
        entity = make_light_entity(
            config_entry, wrapped_state="on", restored_state="off"
        )

        await entity.async_added_to_hass()

        assert entity._attr_is_on is True
        entity.hass.async_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_reads_real_light_off(self):
        """When real light is OFF, wrapper state is OFF, no commands sent."""
        config_entry = make_config_entry(restore_power=False)
        entity = make_light_entity(
            config_entry, wrapped_state="off", restored_state="on"
        )

        await entity.async_added_to_hass()

        assert entity._attr_is_on is False
        entity.hass.async_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_cached_when_real_unavailable(self):
        """When real light unavailable, fall back to cached state."""
        config_entry = make_config_entry(restore_power=False)
        entity = make_light_entity(
            config_entry, wrapped_state=None, restored_state="on"
        )

        await entity.async_added_to_hass()

        assert entity._attr_is_on is True
        entity.hass.async_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_state_available(self):
        """When neither real nor cached state available, is_on stays None."""
        config_entry = make_config_entry(restore_power=False)
        entity = make_light_entity(
            config_entry, wrapped_state=None, restored_state=None
        )

        await entity.async_added_to_hass()

        assert entity._attr_is_on is None
        entity.hass.async_create_task.assert_not_called()


class TestRestorePowerEnabled:
    """When restore_power=True, commands ARE sent to the real light."""

    def test_explicit_true(self):
        config_entry = make_config_entry(restore_power=True)
        entity = make_light_entity(config_entry)
        assert entity._restore_power is True

    @pytest.mark.asyncio
    async def test_restore_on_calls_turn_on(self):
        """When cached state was ON and restore_power=True, call turn_on."""
        config_entry = make_config_entry(restore_power=True)
        entity = make_light_entity(
            config_entry, wrapped_state=None, restored_state="on"
        )

        await entity.async_added_to_hass()

        assert entity._attr_is_on is True
        entity.hass.async_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_restore_off_calls_turn_off(self):
        """When cached state was OFF and restore_power=True, call turn_off."""
        config_entry = make_config_entry(restore_power=True)
        entity = make_light_entity(
            config_entry, wrapped_state=None, restored_state="off"
        )

        await entity.async_added_to_hass()

        assert entity._attr_is_on is False
        entity.hass.async_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_cached_state_does_nothing(self):
        """No cached state - no restore, no commands."""
        config_entry = make_config_entry(restore_power=True)
        entity = make_light_entity(
            config_entry, wrapped_state="on", restored_state=None
        )

        await entity.async_added_to_hass()

        entity.hass.async_create_task.assert_not_called()


# -- Startup seeding --


class TestStartupSeed:
    """Startup restore seeds _last_on_rgb/_last_brightness from best source."""

    @pytest.mark.asyncio
    async def test_transparent_seeds_from_real_light(self):
        """restore_power=False seeds tracking from the wrapped light's state."""
        config_entry = make_config_entry(restore_power=False)
        wrapped = FakeState(
            "on", {"rgb_color": (255, 100, 50), "brightness": 180}
        )
        entity = make_light_entity(
            config_entry, wrapped_state=wrapped, restored_state="off"
        )

        await entity.async_added_to_hass()

        assert entity._last_on_rgb == (255, 100, 50)
        assert entity._last_brightness == 180

    @pytest.mark.asyncio
    async def test_transparent_seeds_from_cached_fallback(self):
        """When real light unavailable, seeds from cached state."""
        config_entry = make_config_entry(restore_power=False)
        cached = FakeState(
            "on", {"rgb_color": (200, 150, 100), "brightness": 120}
        )
        entity = make_light_entity(
            config_entry, wrapped_state=None, restored_state=cached
        )

        await entity.async_added_to_hass()

        assert entity._last_on_rgb == (200, 150, 100)
        assert entity._last_brightness == 120

    @pytest.mark.asyncio
    async def test_restore_power_seeds_from_cached(self):
        """restore_power=True seeds tracking from cached state."""
        config_entry = make_config_entry(restore_power=True)
        cached = FakeState(
            "on", {"rgb_color": (200, 150, 100), "brightness": 200}
        )
        entity = make_light_entity(
            config_entry, wrapped_state=None, restored_state=cached
        )

        await entity.async_added_to_hass()

        assert entity._last_on_rgb == (200, 150, 100)
        assert entity._last_brightness == 200

    @pytest.mark.asyncio
    async def test_no_state_keeps_defaults(self):
        """When no state available, defaults are preserved."""
        config_entry = make_config_entry(restore_power=False)
        entity = make_light_entity(
            config_entry, wrapped_state=None, restored_state=None
        )
        default_rgb = entity._last_on_rgb
        default_brightness = entity._last_brightness

        await entity.async_added_to_hass()

        assert entity._last_on_rgb == default_rgb
        assert entity._last_brightness == default_brightness


# -- Worker spawn order --


class TestWorkerSpawnOrder:
    """Worker task must be spawned after state restore completes."""

    @pytest.mark.asyncio
    async def test_worker_spawns_after_state_restore(self):
        config_entry = make_config_entry(restore_power=False)
        entity = make_light_entity(
            config_entry, wrapped_state="on", restored_state="on"
        )

        call_order = []
        original_get_last_state = entity.async_get_last_state

        async def tracked_get_last_state():
            call_order.append("get_last_state")
            return await original_get_last_state()

        def tracked_create_background_task(*args, **kwargs):
            call_order.append("create_background_task")

        entity.async_get_last_state = tracked_get_last_state
        config_entry.async_create_background_task = tracked_create_background_task

        await entity.async_added_to_hass()

        assert "get_last_state" in call_order
        assert "create_background_task" in call_order
        get_idx = call_order.index("get_last_state")
        spawn_idx = call_order.index("create_background_task")
        assert spawn_idx > get_idx, (
            f"Worker spawned at {spawn_idx} but get_last_state at {get_idx}. "
            f"Worker must spawn AFTER state restore. Order: {call_order}"
        )

    @pytest.mark.asyncio
    async def test_worker_spawns_even_without_restored_state(self):
        config_entry = make_config_entry(restore_power=False)
        entity = make_light_entity(
            config_entry, wrapped_state=None, restored_state=None
        )

        await entity.async_added_to_hass()

        config_entry.async_create_background_task.assert_called_once()
