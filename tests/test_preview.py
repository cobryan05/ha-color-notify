"""Tests for async_preview_sequence and async_stop_preview on NotificationLightEntity."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from conftest import make_config_entry

from homeassistant.const import CONF_DELAY_TIME

from custom_components.color_notify.const import (
    CONF_EXPIRE_ENABLED,
    CONF_NOTIFY_PATTERN,
    CONF_RGB_SELECTOR,
    MAX_PREVIEW_DURATION_SEC,
    PREVIEW_NOTIFY_ID,
)
from custom_components.color_notify.light import NotificationLightEntity


def make_entity():
    """Return a minimal NotificationLightEntity with mocked internals."""
    entry = make_config_entry()
    entity = NotificationLightEntity(
        unique_id="test_id",
        wrapped_entity_id="light.test",
        config_entry=entry,
        log_entity=None,
    )
    entity.hass = MagicMock()
    entity._remove_sequence = AsyncMock()
    entity._add_sequence = AsyncMock()
    return entity


class TestAsyncPreviewSequence:
    """async_preview_sequence queues a remove then an add, sets a safety timer."""

    async def test_remove_called_before_add(self):
        """Remove must be queued before the add so the old preview is replaced."""
        entity = make_entity()
        call_order: list[str] = []
        entity._remove_sequence = AsyncMock(side_effect=lambda *a, **kw: call_order.append("remove"))
        entity._add_sequence = AsyncMock(side_effect=lambda *a, **kw: call_order.append("add"))

        with patch("custom_components.color_notify.light.async_call_later"):
            await entity.async_preview_sequence()

        assert call_order == ["remove", "add"], (
            "remove must be queued before add so the old animation is stopped first"
        )

    async def test_always_uses_preview_notify_id(self):
        """Both remove and add must use PREVIEW_NOTIFY_ID so previews replace each other."""
        entity = make_entity()

        with patch("custom_components.color_notify.light.async_call_later"):
            await entity.async_preview_sequence()

        entity._remove_sequence.assert_awaited_once_with(PREVIEW_NOTIFY_ID)
        add_call = entity._add_sequence.await_args
        assert add_call.args[0] == PREVIEW_NOTIFY_ID

    async def test_sets_safety_timer(self):
        """async_call_later must be called with MAX_PREVIEW_DURATION_SEC."""
        entity = make_entity()
        cancel_mock = MagicMock()

        with patch(
            "custom_components.color_notify.light.async_call_later",
            return_value=cancel_mock,
        ) as mock_later:
            await entity.async_preview_sequence()

        mock_later.assert_called_once()
        _hass, duration, _cb = mock_later.call_args.args
        assert duration == MAX_PREVIEW_DURATION_SEC
        assert entity._preview_cancel is cancel_mock

    async def test_strips_expire_settings_from_sequence(self):
        """CONF_EXPIRE_ENABLED and CONF_DELAY_TIME must not reach the sequence builder.

        The sequence has no switch entity to call turn_off on, so the
        switch-based auto-clear path must never be triggered.
        """
        entity = make_entity()
        captured_attrs: list[dict] = []

        real_create = entity._create_sequence_from_attr

        def capturing_create(attrs, notify_id=None):
            captured_attrs.append(dict(attrs))
            return real_create(attrs, notify_id)

        entity._create_sequence_from_attr = capturing_create

        with patch("custom_components.color_notify.light.async_call_later"):
            await entity.async_preview_sequence(
                **{
                    CONF_EXPIRE_ENABLED: True,
                    CONF_DELAY_TIME: {"seconds": 10},
                    CONF_RGB_SELECTOR: [255, 0, 0],
                }
            )

        assert len(captured_attrs) == 1
        attrs = captured_attrs[0]
        assert attrs.get(CONF_EXPIRE_ENABLED) is False, (
            "CONF_EXPIRE_ENABLED must be forced to False so the sequence never "
            "tries to call switch.turn_off on a nonexistent entity"
        )
        assert CONF_DELAY_TIME not in attrs, (
            "CONF_DELAY_TIME must be stripped so clear_delay is None in the sequence"
        )

    async def test_second_call_cancels_first_timer(self):
        """Calling preview twice must cancel the previous safety timer."""
        entity = make_entity()
        cancel_first = MagicMock()
        cancel_second = MagicMock()

        with patch(
            "custom_components.color_notify.light.async_call_later",
            side_effect=[cancel_first, cancel_second],
        ):
            await entity.async_preview_sequence()
            assert entity._preview_cancel is cancel_first

            await entity.async_preview_sequence()

        cancel_first.assert_called_once()
        assert entity._preview_cancel is cancel_second

    async def test_second_call_removes_old_preview_first(self):
        """Calling preview twice must queue two removes and two adds."""
        entity = make_entity()

        with patch("custom_components.color_notify.light.async_call_later"):
            await entity.async_preview_sequence()
            await entity.async_preview_sequence()

        assert entity._remove_sequence.await_count == 2
        assert entity._add_sequence.await_count == 2


class TestAsyncStopPreview:
    """async_stop_preview cancels the safety timer and removes the preview sequence."""

    async def test_stop_cancels_timer_and_removes_sequence(self):
        """Stop must cancel the pending timer and queue a remove."""
        entity = make_entity()
        cancel_mock = MagicMock()

        with patch(
            "custom_components.color_notify.light.async_call_later",
            return_value=cancel_mock,
        ):
            await entity.async_preview_sequence()

        await entity.async_stop_preview()

        cancel_mock.assert_called_once()
        assert entity._preview_cancel is None
        # remove was called once for the preview start, once for the stop
        assert entity._remove_sequence.await_count == 2

    async def test_stop_clears_preview_cancel_reference(self):
        """_preview_cancel must be None after stop so a second stop is safe."""
        entity = make_entity()

        with patch(
            "custom_components.color_notify.light.async_call_later",
            return_value=MagicMock(),
        ):
            await entity.async_preview_sequence()

        await entity.async_stop_preview()

        assert entity._preview_cancel is None

    async def test_stop_when_no_preview_is_noop(self):
        """Stopping when no preview is active must not raise."""
        entity = make_entity()
        assert entity._preview_cancel is None

        await entity.async_stop_preview()  # must not raise

        entity._remove_sequence.assert_awaited_once_with(PREVIEW_NOTIFY_ID)
