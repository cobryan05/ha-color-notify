"""Stub homeassistant modules for unit testing without full HA install."""

import colorsys
import sys
from unittest.mock import MagicMock

# Upstream light.py imports color_temperature_to_rgb from HA — stub it here
from tests.support.color_util_stub import color_temperature_to_rgb as _color_temperature_to_rgb

# Stub out homeassistant modules before any imports
HA_MODULES = [
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.light",
    "homeassistant.components.switch",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.config_validation",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.event",
    "homeassistant.helpers.restore_state",
    "homeassistant.helpers.selector",
    "homeassistant.util",
    "homeassistant.util.color",
    "voluptuous",
]

for mod_name in HA_MODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

# Set specific constants that our code imports
ha_const = sys.modules["homeassistant.const"]
ha_const.ATTR_ENTITY_ID = "entity_id"
ha_const.CONF_DELAY = "delay"
ha_const.CONF_DELAY_TIME = "delay_time"
ha_const.CONF_ENTITIES = "entities"
ha_const.CONF_ENTITY_ID = "entity_id"
ha_const.CONF_FORCE_UPDATE = "force_update"
ha_const.CONF_NAME = "name"
ha_const.CONF_RGB = "rgb"
ha_const.CONF_TYPE = "type"
ha_const.CONF_UNIQUE_ID = "unique_id"
ha_const.SERVICE_TURN_OFF = "turn_off"
ha_const.SERVICE_TURN_ON = "turn_on"
ha_const.STATE_OFF = "off"
ha_const.STATE_ON = "on"
ha_const.Platform = MagicMock()

ha_light = sys.modules["homeassistant.components.light"]
ha_light.ATTR_BRIGHTNESS = "brightness"
ha_light.ATTR_COLOR_MODE = "color_mode"
ha_light.ATTR_COLOR_TEMP_KELVIN = "color_temp_kelvin"
ha_light.ATTR_HS_COLOR = "hs_color"
ha_light.ATTR_RGB_COLOR = "rgb_color"
ha_light.ATTR_TRANSITION = "transition"
ha_light.ATTR_XY_COLOR = "xy_color"
ha_light.ColorMode = MagicMock()
ha_light.ColorMode.RGB = "rgb"
ha_light.ColorMode.COLOR_TEMP = "color_temp"
ha_light.DOMAIN = "light"


class _StubLightEntity:
    _attr_is_on = None

    @property
    def is_on(self):
        return self._attr_is_on


ha_light.LightEntity = _StubLightEntity

ha_switch = sys.modules["homeassistant.components.switch"]
ha_switch.DOMAIN = "switch"

ha_restore = sys.modules["homeassistant.helpers.restore_state"]
ha_restore.RestoreEntity = type("RestoreEntity", (), {})

ha_core = sys.modules["homeassistant.core"]
ha_core.callback = lambda f: f
ha_core.Event = MagicMock()
ha_core.EventStateChangedData = MagicMock()
ha_core.HomeAssistant = MagicMock()

# Wire up color util stubs — mirrors HA's homeassistant.util.color
ha_util_color = sys.modules["homeassistant.util.color"]
ha_util_color.color_temperature_to_rgb = _color_temperature_to_rgb


def _color_RGB_to_hsv(r, g, b):
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    return (h * 360, s * 100, v * 100)


def _color_hsv_to_RGB(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h / 360.0, s / 100.0, v / 100.0)
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def _color_hs_to_RGB(h, s):
    return _color_hsv_to_RGB(h, s, 100)


def _color_hs_to_xy(h, s):
    return (0.3, 0.3)  # Simplified — exact xy values not under test


def _color_xy_to_temperature(x, y):
    return 4000  # Simplified — exact value not under test


ha_util_color.color_RGB_to_hsv = _color_RGB_to_hsv
ha_util_color.color_hsv_to_RGB = _color_hsv_to_RGB
ha_util_color.color_hs_to_RGB = _color_hs_to_RGB
ha_util_color.color_hs_to_xy = _color_hs_to_xy
ha_util_color.color_xy_to_temperature = _color_xy_to_temperature
