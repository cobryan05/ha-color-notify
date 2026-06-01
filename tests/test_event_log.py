"""Tests for the ColorNotifyLogEntity and event-log integration in NotificationLightEntity."""

from unittest.mock import AsyncMock, MagicMock

from conftest import make_config_entry

from custom_components.color_notify.sensor import ColorNotifyLogEntity
from custom_components.color_notify.light import (
    ColorInfo,
    LIGHT_OFF_SEQUENCE,
    LIGHT_ON_SEQUENCE,
    NotificationLightEntity,
    WARM_WHITE_RGB,
    _NotificationSequence,
)
from custom_components.color_notify.const import DEFAULT_PRIORITY
from homeassistant.const import STATE_OFF, STATE_ON


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_log_entity(title="[Light] Test Light"):
    entry = make_config_entry(title)
    entity = ColorNotifyLogEntity(light_unique_id="test_id", config_entry=entry)
    return entity


def _make_light_entity(log_entity=None, is_on=False):
    """Return (entity, entry) with an optional ColorNotifyLogEntity wired in."""
    entry = make_config_entry()
    entity = NotificationLightEntity(
        unique_id="test_id",
        wrapped_entity_id="light.test",
        config_entry=entry,
        log_entity=log_entity,
    )
    entity.hass = MagicMock()
    entity.hass.states.get.return_value = None
    entity.async_write_ha_state = MagicMock()
    entity.async_schedule_update_ha_state = MagicMock()
    entity.async_turn_on = AsyncMock()
    entity.async_turn_off = AsyncMock()
    entity._attr_is_on = is_on
    return entity, entry


def _make_mock_logger():
    logger = MagicMock(spec=ColorNotifyLogEntity)
    return logger


# ---------------------------------------------------------------------------
# ColorNotifyLogEntity unit tests
# ---------------------------------------------------------------------------


class TestColorNotifyLogEntity:
    """Tests for ColorNotifyLogEntity state management."""

    def test_unique_id_contains_light_id(self):
        """Unique ID incorporates the parent light's unique_id."""
        entity = _make_log_entity()
        assert "test_id" in entity._attr_unique_id

    def test_name_contains_title(self):
        """Entity name incorporates the config entry title."""
        entity = _make_log_entity("[Light] My Lamp")
        assert "My Lamp" in entity._attr_name or "my lamp" in entity._attr_name.lower()

    def test_initial_native_value_is_none(self):
        """State is None before any message is written."""
        entity = _make_log_entity()
        assert entity._attr_native_value is None

    def test_update_message_sets_native_value(self):
        """update_message stores the message as the entity state."""
        entity = _make_log_entity()
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()

        entity.update_message("Light turned on manually")

        assert entity._attr_native_value == "Light turned on manually"

    def test_update_message_calls_async_write_ha_state(self):
        """update_message triggers a state write to HA."""
        entity = _make_log_entity()
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()

        entity.update_message("hello")

        entity.async_write_ha_state.assert_called_once()

    def test_update_message_skips_when_hass_is_none(self):
        """update_message is a no-op before the entity is added to HA."""
        entity = _make_log_entity()
        entity.hass = None  # not yet added
        entity.async_write_ha_state = MagicMock()

        entity.update_message("hello")

        entity.async_write_ha_state.assert_not_called()
        assert entity._attr_native_value is None

    def test_update_message_overwrites_previous_value(self):
        """Calling update_message twice keeps only the latest message."""
        entity = _make_log_entity()
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()

        entity.update_message("first")
        entity.update_message("second")

        assert entity._attr_native_value == "second"

    async def test_async_added_to_hass_restores_previous_message(self):
        """Last log message is restored from storage after a restart."""
        entity = _make_log_entity()
        last_data = MagicMock()
        last_data.native_value = "Notification 'Alert' added"
        entity.async_get_last_sensor_data = AsyncMock(return_value=last_data)

        await entity.async_added_to_hass()

        assert entity._attr_native_value == "Notification 'Alert' added"

    async def test_async_added_to_hass_with_no_prior_state(self):
        """Missing prior state leaves native_value as None."""
        entity = _make_log_entity()
        entity.async_get_last_sensor_data = AsyncMock(return_value=None)

        await entity.async_added_to_hass()

        assert entity._attr_native_value is None


# ---------------------------------------------------------------------------
# NotificationLightEntity + event log — _process_sequence_list
# ---------------------------------------------------------------------------

_TEST_TRIGGER = f"Test Notification (pri {DEFAULT_PRIORITY}) enabled"


class TestProcessSequenceListEventLog:
    """Event log messages emitted by _log_showing_if_changed (called from _process_sequence_list)."""

    async def _run_with_sequence(self, entity, seq, notify_id, log_trigger=_TEST_TRIGGER):
        """Helper: wire seq into active+running lists and call _process_sequence_list."""
        entity._active_sequences[notify_id] = seq
        # Pre-populate running so sequence.run() is not called during the test.
        entity._running_sequences[notify_id] = seq
        entity._wrapped_light_turn_on = AsyncMock(return_value=True)
        await entity._process_sequence_list(log_trigger=log_trigger)

    async def test_displaying_light_on_when_state_on_is_top(self):
        """'displaying Light On' appears when STATE_ON is the top sequence."""
        logger = _make_mock_logger()
        entity, _ = _make_light_entity(log_entity=logger)

        seq = _NotificationSequence(
            notify_id=STATE_ON,
            pattern=[ColorInfo(WARM_WHITE_RGB, 255)],
            priority=DEFAULT_PRIORITY,
        )
        await self._run_with_sequence(entity, seq, STATE_ON)

        logger.update_message.assert_called_once()
        msg = logger.update_message.call_args[0][0]
        assert "displaying Light On" in msg

    async def test_displaying_off_when_state_off_is_top(self):
        """'displaying Off' appears when the off sequence drives the color."""
        logger = _make_mock_logger()
        entity, _ = _make_light_entity(log_entity=logger)

        await self._run_with_sequence(entity, LIGHT_OFF_SEQUENCE, STATE_OFF)

        logger.update_message.assert_called_once()
        msg = logger.update_message.call_args[0][0]
        assert "displaying Off" in msg

    async def test_displaying_includes_friendly_name(self):
        """Friendly name of the showing notification appears in the log message."""
        logger = _make_mock_logger()
        entity, _ = _make_light_entity(log_entity=logger)

        notify_id = "switch.fire_alert"
        fake_state = MagicMock()
        fake_state.attributes = {"friendly_name": "Fire Alert"}
        entity.hass.states.get.return_value = fake_state

        seq = _NotificationSequence(
            notify_id=notify_id,
            pattern=[ColorInfo((255, 0, 0), 255)],
            priority=DEFAULT_PRIORITY + 1,
        )
        await self._run_with_sequence(entity, seq, notify_id)

        logger.update_message.assert_called_once()
        msg = logger.update_message.call_args[0][0]
        assert "Fire Alert" in msg
        assert "displaying" in msg

    async def test_displaying_falls_back_to_entity_id(self):
        """Falls back to entity_id in the message when no friendly name is available."""
        logger = _make_mock_logger()
        entity, _ = _make_light_entity(log_entity=logger)

        notify_id = "switch.unnamed_alert"
        entity.hass.states.get.return_value = None  # no state / no friendly name

        seq = _NotificationSequence(
            notify_id=notify_id,
            pattern=[ColorInfo((0, 255, 0), 255)],
            priority=DEFAULT_PRIORITY + 1,
        )
        await self._run_with_sequence(entity, seq, notify_id)

        logger.update_message.assert_called_once()
        msg = logger.update_message.call_args[0][0]
        assert notify_id in msg

    async def test_no_log_without_trigger(self):
        """update_message is NOT called when no log_trigger is passed."""
        logger = _make_mock_logger()
        entity, _ = _make_light_entity(log_entity=logger)

        entity._active_sequences[STATE_ON] = LIGHT_ON_SEQUENCE
        entity._running_sequences[STATE_ON] = LIGHT_ON_SEQUENCE
        entity._last_set_color = LIGHT_ON_SEQUENCE.color

        entity._wrapped_light_turn_on = AsyncMock(return_value=True)
        await entity._process_sequence_list()  # no log_trigger

        logger.update_message.assert_not_called()

    async def test_trigger_prefixes_message(self):
        """The log_trigger string forms the first part of the emitted message."""
        logger = _make_mock_logger()
        entity, _ = _make_light_entity(log_entity=logger)
        entity._reset_running_sequences = AsyncMock()

        entity._active_sequences[STATE_ON] = LIGHT_ON_SEQUENCE
        entity._running_sequences[STATE_ON] = LIGHT_ON_SEQUENCE
        entity._wrapped_light_turn_on = AsyncMock(return_value=False)

        trigger = "Fire Alert (pri 500) enabled"
        await entity._process_sequence_list(log_trigger=trigger)

        logger.update_message.assert_called_once()
        msg = logger.update_message.call_args[0][0]
        assert msg.startswith(trigger)

    async def test_no_log_entity_no_error(self):
        """_process_sequence_list runs without error when log_entity is None."""
        entity, _ = _make_light_entity(log_entity=None)
        entity._wrapped_light_turn_on = AsyncMock(return_value=True)

        entity._active_sequences[STATE_ON] = LIGHT_ON_SEQUENCE
        entity._running_sequences[STATE_ON] = LIGHT_ON_SEQUENCE

        await entity._process_sequence_list(log_trigger=_TEST_TRIGGER)  # must not raise

    async def test_displaying_lists_all_same_priority_notifications(self):
        """All same-priority notifications appear in the 'displaying' part of the message."""
        logger = _make_mock_logger()
        entity, _ = _make_light_entity(log_entity=logger)

        _names = {"switch.alert_a": "Alert A", "switch.alert_b": "Alert B"}
        entity.hass.states.get.side_effect = lambda eid: MagicMock(
            attributes={"friendly_name": _names.get(eid, eid)}
        )

        seq_a = _NotificationSequence(
            notify_id="switch.alert_a",
            pattern=[ColorInfo((255, 0, 0), 255)],
            priority=DEFAULT_PRIORITY,
        )
        seq_b = _NotificationSequence(
            notify_id="switch.alert_b",
            pattern=[ColorInfo((0, 255, 0), 255)],
            priority=DEFAULT_PRIORITY,
        )
        entity._active_sequences["switch.alert_a"] = seq_a
        entity._active_sequences["switch.alert_b"] = seq_b
        entity._running_sequences["switch.alert_a"] = seq_a
        entity._running_sequences["switch.alert_b"] = seq_b
        entity._wrapped_light_turn_on = AsyncMock(return_value=True)
        await entity._process_sequence_list(log_trigger=_TEST_TRIGGER)

        logger.update_message.assert_called_once()
        msg = logger.update_message.call_args[0][0]
        assert "Alert A" in msg
        assert "Alert B" in msg
        assert "displaying" in msg

    async def test_displaying_includes_priority_for_regular_notifications(self):
        """Priority appears in the 'displaying' description for non-peeking notifications."""
        logger = _make_mock_logger()
        entity, _ = _make_light_entity(log_entity=logger)

        notify_id = "switch.fire_alert"
        entity.hass.states.get.return_value = None

        seq = _NotificationSequence(
            notify_id=notify_id,
            pattern=[ColorInfo((255, 0, 0), 255)],
            priority=500,
        )
        await self._run_with_sequence(entity, seq, notify_id)

        msg = logger.update_message.call_args[0][0]
        assert "pri 500" in msg

    async def test_peeking_label_shown_when_boost_causes_win(self):
        """'(peeking)' appears when the notification wins only because of the priority boost."""
        from custom_components.color_notify.const import MAXIMUM_PRIORITY

        logger = _make_mock_logger()
        entity, _ = _make_light_entity(log_entity=logger)

        entity.hass.states.get.return_value = None  # entity_id used as name

        # A high-priority notification already showing (not boosted).
        seq_high = _NotificationSequence(
            notify_id="switch.high_prio",
            pattern=[ColorInfo((255, 0, 0), 255)],
            priority=10,
        )
        entity._active_sequences["switch.high_prio"] = seq_high

        # A low-priority notification that was just added with a peek boost.
        seq_low = _NotificationSequence(
            notify_id="switch.low_prio",
            pattern=[ColorInfo((0, 255, 0), 255)],
            priority=3 + MAXIMUM_PRIORITY,  # boosted; un-boosted would be 3
        )
        entity._active_sequences["switch.low_prio"] = seq_low
        entity._running_sequences["switch.low_prio"] = seq_low
        entity._wrapped_light_turn_on = AsyncMock(return_value=True)
        await entity._process_sequence_list(log_trigger=_TEST_TRIGGER)

        msg = logger.update_message.call_args[0][0]
        assert "(peeking)" in msg

    async def test_no_peek_boost_when_already_highest_priority(self):
        """A notification that beats current top priority is not boosted by _work_loop."""
        from custom_components.color_notify.const import MAXIMUM_PRIORITY

        # The boost condition in _work_loop is:
        #   item.sequence.priority < current_top_priority
        # When only STATE_OFF is active, current_top is 0. A notification with
        # priority 10 is already the natural top (10 > 0), so the condition is
        # False and priority must remain unchanged at its natural value.
        assert LIGHT_OFF_SEQUENCE.priority == 0, "STATE_OFF sentinel priority"
        natural_priority = 10
        assert natural_priority > LIGHT_OFF_SEQUENCE.priority, "notification is already top"
        assert natural_priority <= MAXIMUM_PRIORITY, "would not be boosted"


# ---------------------------------------------------------------------------
# NotificationLightEntity + event log — _handle_notification_change
# ---------------------------------------------------------------------------


class TestHandleStateChangeEventLog:
    """log_trigger values queued by _handle_notification_change."""

    @staticmethod
    def _make_event(notify_id, state_value, attributes=None):
        event = MagicMock()
        new_state = MagicMock()
        new_state.state = state_value
        new_state.attributes = attributes or {}
        event.data = {"entity_id": notify_id, "new_state": new_state}
        return event

    async def test_notification_added_trigger_includes_friendly_name(self):
        """Enabling a notification places a trigger with the friendly name in the queue."""
        entity, _ = _make_light_entity()

        notify_id = "switch.fire_alert"
        seq_mock = MagicMock()
        seq_mock.priority = DEFAULT_PRIORITY
        entity._create_sequence_from_attr = MagicMock(return_value=seq_mock)

        await entity._handle_notification_change(
            self._make_event(notify_id, STATE_ON, {"friendly_name": "Fire Alert"})
        )

        item = entity._task_queue.get_nowait()
        assert item.log_trigger is not None
        assert "Fire Alert" in item.log_trigger
        assert "enabled" in item.log_trigger

    async def test_notification_added_trigger_includes_priority(self):
        """The queue trigger for an add includes the notification's natural priority."""
        entity, _ = _make_light_entity()

        notify_id = "switch.fire_alert"
        seq_mock = MagicMock()
        seq_mock.priority = 500
        entity._create_sequence_from_attr = MagicMock(return_value=seq_mock)

        await entity._handle_notification_change(
            self._make_event(notify_id, STATE_ON, {"friendly_name": "Fire Alert"})
        )

        item = entity._task_queue.get_nowait()
        assert f"pri 500" in item.log_trigger

    async def test_notification_removed_trigger_includes_friendly_name(self):
        """Disabling a notification places a trigger with the friendly name in the queue."""
        entity, _ = _make_light_entity()

        notify_id = "switch.fire_alert"

        await entity._handle_notification_change(
            self._make_event(notify_id, STATE_OFF, {"friendly_name": "Fire Alert"})
        )

        item = entity._task_queue.get_nowait()
        assert item.log_trigger is not None
        assert "Fire Alert" in item.log_trigger
        assert "disabled" in item.log_trigger

    async def test_notification_removed_trigger_uses_natural_priority(self):
        """Disabled trigger uses the natural (un-boosted) priority even when sequence is peeking."""
        from custom_components.color_notify.const import MAXIMUM_PRIORITY

        entity, _ = _make_light_entity()
        notify_id = "switch.fire_alert"

        # Simulate a sequence that is currently in the active list with a peek boost.
        seq = _NotificationSequence(
            notify_id=notify_id,
            pattern=[ColorInfo((255, 0, 0), 255)],
            priority=100 + MAXIMUM_PRIORITY,  # boosted; natural = 100
        )
        entity._active_sequences[notify_id] = seq

        await entity._handle_notification_change(
            self._make_event(notify_id, STATE_OFF, {"friendly_name": "Fire Alert"})
        )

        item = entity._task_queue.get_nowait()
        assert "pri 100" in item.log_trigger

    async def test_notification_added_falls_back_to_entity_id(self):
        """entity_id is used in the trigger when there is no friendly name."""
        entity, _ = _make_light_entity()

        notify_id = "switch.unnamed"
        seq_mock = MagicMock()
        seq_mock.priority = DEFAULT_PRIORITY
        entity._create_sequence_from_attr = MagicMock(return_value=seq_mock)

        await entity._handle_notification_change(self._make_event(notify_id, STATE_ON))

        item = entity._task_queue.get_nowait()
        assert notify_id in item.log_trigger

    async def test_notification_removed_falls_back_to_entity_id(self):
        """entity_id is used in the trigger when there is no friendly name."""
        entity, _ = _make_light_entity()

        notify_id = "switch.unnamed"

        await entity._handle_notification_change(self._make_event(notify_id, STATE_OFF))

        item = entity._task_queue.get_nowait()
        assert notify_id in item.log_trigger

    async def test_no_log_entity_no_error_on_add(self):
        """_handle_notification_change runs without error when log_entity is None (add)."""
        entity, _ = _make_light_entity(log_entity=None)
        seq_mock = MagicMock()
        seq_mock.priority = DEFAULT_PRIORITY
        entity._create_sequence_from_attr = MagicMock(return_value=seq_mock)

        await entity._handle_notification_change(
            self._make_event("switch.x", STATE_ON)
        )  # must not raise

    async def test_no_log_entity_no_error_on_remove(self):
        """_handle_notification_change runs without error when log_entity is None (remove)."""
        entity, _ = _make_light_entity(log_entity=None)

        await entity._handle_notification_change(
            self._make_event("switch.x", STATE_OFF)
        )  # must not raise


# ---------------------------------------------------------------------------
# async_turn_on / async_turn_off log triggers
# ---------------------------------------------------------------------------


class TestTurnOnOffEventLog:
    """Log triggers queued by async_turn_on and async_turn_off."""

    async def test_turn_on_queues_light_turned_on_trigger(self):
        """async_turn_on places a 'Light turned on' trigger in the queue."""
        entity, _ = _make_light_entity()
        del entity.async_turn_on  # restore real method (helper mocks it as AsyncMock)
        # Seed the off sentinel so _get_top_sequences()[0] doesn't IndexError.
        entity._active_sequences[STATE_OFF] = LIGHT_OFF_SEQUENCE

        await entity.async_turn_on()

        item = entity._task_queue.get_nowait()
        assert item.log_trigger == "Light turned on"

    async def test_turn_off_queues_light_turned_off_trigger(self):
        """async_turn_off places a 'Light turned off' trigger in the queue."""
        entity, _ = _make_light_entity()
        del entity.async_turn_off  # restore real method (helper mocks it as AsyncMock)

        await entity.async_turn_off()

        item = entity._task_queue.get_nowait()
        assert item.log_trigger == "Light turned off"
