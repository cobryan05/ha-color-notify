"""Track the real wrapped light's state for notification restore.

Decouples state tracking from command sending:
- Observes HA state changes on the wrapped light
- Freezes on notification start (captures pre-notification state)
- Provides restore_params after notifications clear
- Never sends commands — the caller decides when/what to send

Replaces the _startup_quiet flag and WARM_WHITE_RGB hardcoded restore.
"""

from __future__ import annotations

from typing import Any


# Color modes where color_temp is the primary color attribute
_COLOR_TEMP_MODES = {"color_temp"}

# Color modes where xy is the primary color attribute
_XY_MODES = {"xy"}

# Color modes where hs is the primary color attribute
_HS_MODES = {"hs"}

# Color modes where rgb is the primary color attribute
_RGB_MODES = {"rgb", "rgbw", "rgbww"}


class WrappedLightState:
    """Tracks the real wrapped light's actual state.

    Usage:
        tracker = WrappedLightState()
        tracker.update(state)       # Call on every state_changed event
        tracker.freeze()            # Call when notification starts
        tracker.restore_params      # Use to restore after notification clears
        tracker.unfreeze()          # Call after restore command sent
    """

    def __init__(self) -> None:
        self._state: str | None = None
        self._attrs: dict[str, Any] = {}
        self._frozen: bool = False

    @property
    def is_on(self) -> bool:
        return self._state == "on"

    @property
    def has_state(self) -> bool:
        return self._state is not None

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    def update(self, state: Any) -> None:
        """Update from an HA state object. Ignored while frozen."""
        if self._frozen:
            return
        self._state = state.state
        self._attrs = dict(state.attributes) if state.attributes else {}

    def freeze(self) -> None:
        """Capture current state for restore. Idempotent."""
        self._frozen = True

    def unfreeze(self) -> None:
        """Resume tracking state changes."""
        self._frozen = False

    @property
    def restore_params(self) -> dict[str, Any]:
        """Return light.turn_on kwargs to restore the wrapped light.

        Returns empty dict if light was off or no state tracked.
        The caller should check is_on to decide turn_on vs turn_off.
        """
        if not self.is_on:
            return {}

        params: dict[str, Any] = {}
        brightness = self._attrs.get("brightness")
        if brightness is not None:
            params["brightness"] = brightness

        color_mode = self._attrs.get("color_mode")
        color_attr = self._color_attr_for_mode(color_mode)
        if color_attr:
            value = self._attrs.get(color_attr)
            if value is not None:
                params[color_attr] = value

        return params

    def _color_attr_for_mode(self, color_mode: str | None) -> str | None:
        """Return the HA attribute name for the given color mode."""
        if color_mode in _COLOR_TEMP_MODES:
            return "color_temp"
        if color_mode in _XY_MODES:
            # Prefer xy_color, fall back to hs_color
            if self._attrs.get("xy_color") is not None:
                return "xy_color"
            if self._attrs.get("hs_color") is not None:
                return "hs_color"
            return None
        if color_mode in _HS_MODES:
            return "hs_color"
        if color_mode in _RGB_MODES:
            return "rgb_color"
        # Unknown mode — try to include whatever color attribute is available
        for attr in ("rgb_color", "hs_color", "xy_color", "color_temp"):
            if self._attrs.get(attr) is not None:
                return attr
        return None
