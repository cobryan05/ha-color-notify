"""Sensor platform for ColorNotify integration event logging."""

from homeassistant.components.sensor import RestoreSensor
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_EVENT_ENTITY
from .utils.hass_data import HassData


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the ColorNotify event log sensor for a light config entry."""
    runtime_data = HassData.get_config_entry_runtime_data(config_entry.entry_id)
    log_entity: ColorNotifyLogEntity = runtime_data[CONF_EVENT_ENTITY]
    async_add_entities([log_entity])


class ColorNotifyLogEntity(RestoreSensor):
    """Event log sensor for a ColorNotify notification light.

    State is always the most recent human-readable event message.  Because
    every state change is recorded by the HA recorder, the entity's history
    card becomes a timestamped log that answers "what caused that light to
    turn on?"
    """

    _attr_should_poll = False
    _attr_native_value: str | None = None

    def __init__(self, light_unique_id: str, config_entry: ConfigEntry) -> None:
        """Initialize the event log sensor."""
        super().__init__()
        self._attr_unique_id = f"{light_unique_id}_event_log"
        self._attr_name = f"{config_entry.title} event log"

    async def async_added_to_hass(self) -> None:
        """Restore the last known message after a restart."""
        await super().async_added_to_hass()
        if (last_data := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last_data.native_value

    @callback
    def update_message(self, message: str) -> None:
        """Write a new log message; called directly by the associated NotificationLightEntity."""
        if self.hass is None:
            # Not yet added to HA; skip until setup is complete.
            return
        self._attr_native_value = message
        self.async_write_ha_state()
