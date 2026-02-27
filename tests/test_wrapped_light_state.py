"""Tests for WrappedLightState — tracks real light state for notification restore.

WrappedLightState solves the post-notification restore problem:
- Before: notifications clear → worker sends WARM_WHITE_RGB at brightness 255
- After: notifications clear → worker sends the actual pre-notification light state

It also eliminates _startup_quiet by decoupling state tracking from commands:
- On startup, WrappedLightState reads the current state without sending commands
- The "restore" concept only applies after a notification has played
"""

import pytest

from custom_components.color_notify.utils.wrapped_light_state import WrappedLightState
from tests.support.entity_helpers import FakeState


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestInit:

    def test_starts_empty(self):
        ws = WrappedLightState()
        assert ws.is_on is False
        assert ws.has_state is False
        assert ws.restore_params == {}

    def test_not_frozen_initially(self):
        ws = WrappedLightState()
        assert ws.is_frozen is False


# ---------------------------------------------------------------------------
# State Updates
# ---------------------------------------------------------------------------

class TestUpdate:

    def test_update_from_on_state(self):
        ws = WrappedLightState()
        ws.update(FakeState("on", {
            "brightness": 150,
            "color_temp": 370,
            "color_mode": "color_temp",
        }))
        assert ws.is_on is True
        assert ws.has_state is True

    def test_update_from_off_state(self):
        ws = WrappedLightState()
        ws.update(FakeState("off"))
        assert ws.is_on is False
        assert ws.has_state is True

    def test_update_replaces_previous(self):
        ws = WrappedLightState()
        ws.update(FakeState("on", {"brightness": 100}))
        ws.update(FakeState("on", {"brightness": 200}))
        assert ws.restore_params["brightness"] == 200

    def test_update_ignored_when_frozen(self):
        ws = WrappedLightState()
        ws.update(FakeState("on", {"brightness": 150}))
        ws.freeze()
        ws.update(FakeState("on", {"brightness": 255}))
        assert ws.restore_params["brightness"] == 150

    def test_update_resumes_after_unfreeze(self):
        ws = WrappedLightState()
        ws.update(FakeState("on", {"brightness": 150}))
        ws.freeze()
        ws.update(FakeState("on", {"brightness": 255}))
        ws.unfreeze()
        ws.update(FakeState("on", {"brightness": 80}))
        assert ws.restore_params["brightness"] == 80


# ---------------------------------------------------------------------------
# Freeze / Unfreeze
# ---------------------------------------------------------------------------

class TestFreeze:

    def test_freeze_captures_state(self):
        ws = WrappedLightState()
        ws.update(FakeState("on", {
            "brightness": 150,
            "color_temp": 370,
            "color_mode": "color_temp",
        }))
        ws.freeze()
        assert ws.is_frozen is True
        params = ws.restore_params
        assert params["brightness"] == 150
        assert params["color_temp"] == 370

    def test_unfreeze_clears_frozen(self):
        ws = WrappedLightState()
        ws.update(FakeState("on", {"brightness": 150}))
        ws.freeze()
        ws.unfreeze()
        assert ws.is_frozen is False

    def test_freeze_without_state_is_safe(self):
        ws = WrappedLightState()
        ws.freeze()
        assert ws.is_frozen is True
        assert ws.restore_params == {}

    def test_double_freeze_is_idempotent(self):
        ws = WrappedLightState()
        ws.update(FakeState("on", {"brightness": 150}))
        ws.freeze()
        ws.freeze()  # Should not reset the captured state
        assert ws.restore_params["brightness"] == 150


# ---------------------------------------------------------------------------
# Restore Params — color_temp mode
# ---------------------------------------------------------------------------

class TestRestoreColorTemp:

    @pytest.mark.parametrize("brightness,color_temp,expected", [
        (150, 370, {"brightness": 150, "color_temp": 370}),
        (None, 370, {"color_temp": 370}),
    ], ids=["with_brightness", "without_brightness"])
    def test_color_temp_mode(self, brightness, color_temp, expected):
        ws = WrappedLightState()
        attrs = {"color_temp": color_temp, "color_mode": "color_temp"}
        if brightness is not None:
            attrs["brightness"] = brightness
        ws.update(FakeState("on", attrs))
        params = ws.restore_params
        assert params == expected
        assert "rgb_color" not in params
        assert "hs_color" not in params


# ---------------------------------------------------------------------------
# Restore Params — xy mode (Hue lights)
# ---------------------------------------------------------------------------

class TestRestoreXY:

    @pytest.mark.parametrize("attrs,expected", [
        (
            {"brightness": 200, "xy_color": [0.4573, 0.41], "color_mode": "xy"},
            {"brightness": 200, "xy_color": [0.4573, 0.41]},
        ),
        (
            {"brightness": 200, "hs_color": [50.769, 15.294], "color_mode": "xy"},
            {"brightness": 200, "hs_color": [50.769, 15.294]},
        ),
    ], ids=["direct_xy", "hs_fallback"])
    def test_xy_mode(self, attrs, expected):
        ws = WrappedLightState()
        ws.update(FakeState("on", attrs))
        assert ws.restore_params == expected


# ---------------------------------------------------------------------------
# Restore Params — hs mode
# ---------------------------------------------------------------------------

class TestRestoreHS:

    def test_hs_mode(self):
        ws = WrappedLightState()
        ws.update(FakeState("on", {
            "brightness": 180,
            "hs_color": [270, 100],
            "color_mode": "hs",
        }))
        params = ws.restore_params
        assert params == {"brightness": 180, "hs_color": [270, 100]}


# ---------------------------------------------------------------------------
# Restore Params — rgb mode
# ---------------------------------------------------------------------------

class TestRestoreRGB:

    def test_rgb_mode(self):
        ws = WrappedLightState()
        ws.update(FakeState("on", {
            "brightness": 128,
            "rgb_color": [255, 0, 128],
            "color_mode": "rgb",
        }))
        params = ws.restore_params
        assert params == {"brightness": 128, "rgb_color": [255, 0, 128]}


# ---------------------------------------------------------------------------
# Restore Params — brightness-only mode
# ---------------------------------------------------------------------------

class TestRestoreBrightness:

    def test_brightness_only(self):
        """Caseta dimmers: brightness only, no color."""
        ws = WrappedLightState()
        ws.update(FakeState("on", {
            "brightness": 64,
            "color_mode": "brightness",
        }))
        params = ws.restore_params
        assert params == {"brightness": 64}


# ---------------------------------------------------------------------------
# Restore Params — off state
# ---------------------------------------------------------------------------

class TestRestoreOff:

    @pytest.mark.parametrize("states,label", [
        ([("off", None)], "off_state"),
        ([("on", {"brightness": 150}), ("off", None)], "on_then_off"),
    ], ids=["off_state", "on_then_off"])
    def test_off_returns_empty(self, states, label):
        ws = WrappedLightState()
        for state_str, attrs in states:
            ws.update(FakeState(state_str, attrs))
        assert ws.restore_params == {}


# ---------------------------------------------------------------------------
# Restore Params — edge cases
# ---------------------------------------------------------------------------

class TestRestoreEdgeCases:

    @pytest.mark.parametrize("attrs,expected_keys", [
        (
            {"brightness": 100, "color_mode": "rgbww", "rgb_color": [255, 200, 150]},
            {"brightness": 100, "rgb_color": [255, 200, 150]},
        ),
        (
            {"brightness": 200},
            {"brightness": 200},
        ),
        (
            {"brightness": 150, "color_temp": None, "color_mode": "color_temp"},
            {"brightness": 150},
        ),
    ], ids=["unknown_mode", "no_color_attrs", "none_values"])
    def test_edge_cases(self, attrs, expected_keys):
        ws = WrappedLightState()
        ws.update(FakeState("on", attrs))
        params = ws.restore_params
        assert params == expected_keys


# ---------------------------------------------------------------------------
# Startup scenario (decoupled from commands)
# ---------------------------------------------------------------------------

class TestStartupDecoupling:

    def test_initial_state_read_no_freeze(self):
        """On startup, read state but don't freeze — no notification active."""
        ws = WrappedLightState()
        ws.update(FakeState("on", {
            "brightness": 150,
            "color_temp": 370,
            "color_mode": "color_temp",
        }))
        assert ws.has_state is True
        assert ws.is_frozen is False
        assert ws.restore_params == {"brightness": 150, "color_temp": 370}

    def test_startup_off_then_notification(self):
        """Light was off at startup, notification plays, restores to off."""
        ws = WrappedLightState()
        ws.update(FakeState("off"))
        ws.freeze()  # Notification starts
        assert ws.is_on is False

    def test_startup_on_then_notification_then_restore(self):
        """Light on at startup, notification plays, restore to original."""
        ws = WrappedLightState()
        ws.update(FakeState("on", {
            "brightness": 150,
            "color_temp": 370,
            "color_mode": "color_temp",
        }))
        ws.freeze()
        # Notification changes light — these updates are ignored
        ws.update(FakeState("on", {
            "brightness": 255,
            "rgb_color": [128, 0, 255],
            "color_mode": "rgb",
        }))
        # Restore should return original state, not notification state
        params = ws.restore_params
        assert params == {"brightness": 150, "color_temp": 370}
        assert ws.is_on is True
