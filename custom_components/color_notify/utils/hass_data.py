import logging
from typing import Any

from homeassistant.const import CONF_ENTITY_ID, CONF_TYPE, CONF_UNIQUE_ID
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from ..const import DOMAIN, TYPE_LIGHT, TYPE_POOL, CONF_ENTRY

_LOGGER = logging.getLogger(__name__)


class HassData:
    """Helper functions for access hass_data."""

    _runtime_data: dict[str, dict] = {}

    @callback
    @staticmethod
    def get_domain_data(hass: HomeAssistant) -> dict[str, dict]:
        """Return the domain hass_data."""
        return hass.data.setdefault(DOMAIN, {})

    @callback
    @staticmethod
    def get_config_entry_runtime_data(config_entry_id: str) -> dict[str, Any]:
        """Return non-persisted runtime data for a ConfigEntry."""
        # TODO: There is a method of putting runtime data on ConfigEntry itself...
        return HassData._runtime_data.setdefault(config_entry_id, {})

    @callback
    @staticmethod
    def clear_config_entry_runtime_data(config_entry_id: str) -> None:
        """Clear runtime data for a ConfigEntry."""
        if config_entry_id in HassData._runtime_data:
            HassData._runtime_data.pop(config_entry_id)

    @callback
    @staticmethod
    def get_all_entities(
        hass: HomeAssistant, config_entry_id: str
    ) -> dict[str, er.RegistryEntry]:
        """Return all entities from a given config_entry."""
        entity_registry = er.async_get(hass)
        entities = er.async_entries_for_config_entry(entity_registry, config_entry_id)
        return {entity.unique_id: entity for entity in entities}

    @callback
    @staticmethod
    def get_all_pools(hass: HomeAssistant) -> dict[str, dict]:
        """Return all notification pools."""
        return {
            uid: item_info
            for uid, item_info in HassData.get_domain_data(hass).items()
            if item_info[CONF_TYPE] == TYPE_POOL
        }

    @callback
    @staticmethod
    def get_domain_lights(hass: HomeAssistant) -> dict[str, dict]:
        """Return all notification lights."""
        return {
            uid: item_info
            for uid, item_info in HassData.get_domain_data(hass).items()
            if item_info[CONF_TYPE] == TYPE_LIGHT
        }

    @callback
    @staticmethod
    def get_domain_light_entity_ids(hass: HomeAssistant) -> list[str]:
        """Return a list of all wrapper light entity_ids.

        Only includes the light-domain entity for each Light config entry;
        companion sensor (event-log) entities are excluded.
        """
        entity_registry: er.EntityRegistry = er.async_get(hass)
        ret: list[str] = []
        for uid in HassData.get_domain_lights(hass).keys():
            entities = er.async_entries_for_config_entry(entity_registry, uid)
            ret.extend(
                entity.entity_id
                for entity in entities
                if entity.domain == "light"
            )
        return ret

    @callback
    @staticmethod
    def get_wrapped_light_entity_ids(hass: HomeAssistant) -> list[str]:
        """Return a list of all wrapped light entity_ids."""
        return [
            item_info[CONF_ENTRY].data[CONF_ENTITY_ID]
            for item_info in HassData.get_domain_lights(hass).values()
        ]

    @callback
    @staticmethod
    def remove_entity(
        hass: HomeAssistant, config_entry_id: str, unique_id: str
    ) -> None:
        """Remove an entity by unique id."""
        entities = HassData.get_all_entities(hass, config_entry_id)
        entity_to_delete = entities.get(unique_id)
        if entity_to_delete is not None:
            entity_registry = er.async_get(hass)
            entity_registry.async_remove(entity_to_delete.entity_id)
        else:
            _LOGGER.warning("Couldn't find entity with uid %s for removal", unique_id)
