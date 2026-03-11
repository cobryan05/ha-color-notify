"""Stub homeassistant modules for unit testing without full HA install."""

import sys
import types
from unittest.mock import MagicMock

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
ha_light.ATTR_XY_COLOR = "xy_color"
ha_light.ColorMode = MagicMock()
ha_light.ColorMode.COLOR_TEMP = "color_temp"
class _StubLightEntity:
    _attr_is_on = None
    _attr_name = None
    entity_id = None

    @property
    def is_on(self):
        return self._attr_is_on

    @property
    def name(self):
        return self._attr_name

    async def async_added_to_hass(self):
        pass

ha_light.LightEntity = _StubLightEntity
ha_light.DOMAIN = "light"

ha_switch = sys.modules["homeassistant.components.switch"]
ha_switch.DOMAIN = "switch"

ha_restore = sys.modules["homeassistant.helpers.restore_state"]
ha_restore.RestoreEntity = type("RestoreEntity", (), {})

ha_core = sys.modules["homeassistant.core"]
ha_core.callback = lambda f: f
ha_core.Event = MagicMock()
ha_core.EventStateChangedData = MagicMock()
ha_core.HomeAssistant = MagicMock()
