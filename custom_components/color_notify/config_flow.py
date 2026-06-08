"""Config flow for ColorNotify integration."""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, Mapping
from uuid import uuid4

import voluptuous as vol

from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_DELAY,
    CONF_DELAY_TIME,
    CONF_ENTITIES,
    CONF_ENTITY_ID,
    CONF_FORCE_UPDATE,
    CONF_NAME,
    CONF_TYPE,
    CONF_UNIQUE_ID,
)
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er, selector
import homeassistant.helpers.config_validation as cv

from .const import (
    DEFAULT_COLOR_STEP_DELAY_SEC,
    CONF_DELETE,
    CONF_DYNAMIC_PRIORITY,
    CONF_ENABLE_EVENT_LOG,
    CONF_ENTRY,
    CONF_EXPIRE_ENABLED,
    CONF_NOTIFY_PATTERN,
    CONF_NTFCTN_ENTRIES,
    CONF_PEEK_ENABLED,
    CONF_PEEK_TIME,
    CONF_PRIORITY,
    CONF_RGB_SELECTOR,
    CONF_SUBSCRIPTION,
    CONF_TEST_ACTION,
    CONF_TEST_LIGHT,
    DEFAULT_PRIORITY,
    DOMAIN,
    MAXIMUM_PRIORITY,
    SERVICE_PREVIEW_SEQUENCE,
    SERVICE_STOP_PREVIEW,
    TYPE_LIGHT,
    TYPE_POOL,
    WARM_WHITE_RGB,
)
from .utils.hass_data import HassData
from .utils.light_sequence import LightSequence

_LOGGER = logging.getLogger(__name__)


ADD_NOTIFY_DEFAULTS = {
    CONF_NAME: "New Notification Name",
    CONF_NOTIFY_PATTERN: [],
    CONF_RGB_SELECTOR: WARM_WHITE_RGB,
    CONF_DELAY_TIME: {"seconds": 0},
    CONF_EXPIRE_ENABLED: False,
    CONF_PRIORITY: DEFAULT_PRIORITY,
    CONF_PEEK_ENABLED: True,
}
ADD_NOTIFY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME, default=ADD_NOTIFY_DEFAULTS[CONF_NAME]): cv.string,
        vol.Required(
            CONF_PRIORITY, default=ADD_NOTIFY_DEFAULTS[CONF_PRIORITY]
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                mode=selector.NumberSelectorMode.BOX, min=1, max=MAXIMUM_PRIORITY
            )
        ),
        vol.Required(
            CONF_PEEK_ENABLED, default=ADD_NOTIFY_DEFAULTS[CONF_PEEK_ENABLED]
        ): cv.boolean,
        vol.Required(
            CONF_EXPIRE_ENABLED, default=ADD_NOTIFY_DEFAULTS[CONF_EXPIRE_ENABLED]
        ): cv.boolean,
        vol.Optional(
            CONF_DELAY_TIME, default=ADD_NOTIFY_DEFAULTS[CONF_DELAY_TIME]
        ): selector.DurationSelector(selector.DurationSelectorConfig()),
        vol.Optional(
            CONF_NOTIFY_PATTERN, default=ADD_NOTIFY_DEFAULTS[CONF_NOTIFY_PATTERN]
        ): selector.TextSelector(
            selector.TextSelectorConfig(
                multiple=True,
            )
        ),
        vol.Optional(
            CONF_RGB_SELECTOR, default=ADD_NOTIFY_DEFAULTS[CONF_RGB_SELECTOR]
        ): selector.ColorRGBSelector(),
    }
)

ADD_POOL_SCHEMA = vol.Schema({vol.Required(CONF_NAME): cv.string})

ADD_LIGHT_DEFAULTS = {
    CONF_NAME: "New Notification Light",
    CONF_RGB_SELECTOR: WARM_WHITE_RGB,
    CONF_PRIORITY: DEFAULT_PRIORITY,
    CONF_DYNAMIC_PRIORITY: True,
    CONF_DELAY: True,
    CONF_DELAY_TIME: {"seconds": 5},
    CONF_PEEK_TIME: {"seconds": 5},
    CONF_ENABLE_EVENT_LOG: True,
}
ADD_LIGHT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME, default=ADD_LIGHT_DEFAULTS[CONF_NAME]): cv.string,
        vol.Required(CONF_ENTITY_ID): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=LIGHT_DOMAIN)
        ),
        vol.Optional(
            CONF_RGB_SELECTOR, default=ADD_LIGHT_DEFAULTS[CONF_RGB_SELECTOR]
        ): selector.ColorRGBSelector(),
        vol.Required(
            CONF_DYNAMIC_PRIORITY, default=ADD_LIGHT_DEFAULTS[CONF_DYNAMIC_PRIORITY]
        ): cv.boolean,
        vol.Optional(
            CONF_PRIORITY, default=ADD_LIGHT_DEFAULTS[CONF_PRIORITY]
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                mode=selector.NumberSelectorMode.BOX, min=1, max=MAXIMUM_PRIORITY
            )
        ),
        vol.Required(CONF_DELAY, default=ADD_LIGHT_DEFAULTS[CONF_DELAY]): cv.boolean,
        vol.Optional(
            CONF_DELAY_TIME, default=ADD_LIGHT_DEFAULTS[CONF_DELAY_TIME]
        ): selector.DurationSelector(selector.DurationSelectorConfig()),
        vol.Optional(
            CONF_PEEK_TIME, default=ADD_LIGHT_DEFAULTS[CONF_PEEK_TIME]
        ): selector.DurationSelector(selector.DurationSelectorConfig()),
        vol.Required(
            CONF_ENABLE_EVENT_LOG, default=ADD_LIGHT_DEFAULTS[CONF_ENABLE_EVENT_LOG]
        ): cv.boolean,
    }
)

SUBSCRIPTION_DEFAULTS = {TYPE_POOL: [], CONF_ENTITIES: []}
SUBSCRIPTION_SCHEMA = vol.Schema(
    {
        vol.Optional(
            TYPE_POOL, default=SUBSCRIPTION_DEFAULTS.get(TYPE_POOL)
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                multiple=True, options=SUBSCRIPTION_DEFAULTS.get(TYPE_POOL)
            )
        ),
        vol.Optional(
            CONF_ENTITIES, default=SUBSCRIPTION_DEFAULTS.get(CONF_ENTITIES)
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(
                multiple=True,
                filter=selector.EntityFilterSelectorConfig(
                    domain=SWITCH_DOMAIN, integration=DOMAIN
                ),
            )
        ),
    }
)


class ConfigFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config or options flow for ColorNotify."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        return self.async_show_menu(menu_options=["new_pool", "new_light"])

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle integration reconfiguration."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry

        if entry.data[CONF_TYPE] == TYPE_LIGHT:
            return await self.async_step_reconfigure_light(user_input)

        return self.async_abort(
            reason=f"Reconfigure not supported for {str(entry.data[CONF_TYPE])}"
        )

    async def async_step_reconfigure_light(
        self, user_input: dict[str, Any] | None = None
    ):
        """Handle reconfiguring the light entity."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry

        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry,
                data=user_input | {CONF_TYPE: TYPE_LIGHT},
                reason="Changes saved",
            )

        # Remove 'name' from schema. Use 'rename' for that.
        schema = vol.Schema(
            {k: v for k, v in ADD_LIGHT_SCHEMA.schema.items() if k != CONF_NAME}
        )
        schema = self.add_suggested_values_to_schema(
            schema, suggested_values=entry.data
        )
        return self.async_show_form(step_id="reconfigure_light", data_schema=schema)

    async def async_step_new_pool(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a New Pool flow."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"[Pool] {user_input[CONF_NAME]}",
                data=user_input | {CONF_TYPE: TYPE_POOL},
            )
        return self.async_show_form(step_id="new_pool", data_schema=ADD_POOL_SCHEMA)

    async def async_step_new_light(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a New Light flow."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"[Light] {user_input[CONF_NAME]}",
                data=user_input | {CONF_TYPE: TYPE_LIGHT},
            )

        exclude_entities = HassData.get_domain_light_entity_ids(self.hass)
        exclude_entities.extend(HassData.get_wrapped_light_entity_ids(self.hass))
        schema = {k: copy.copy(v) for k, v in ADD_LIGHT_SCHEMA.schema.items()}
        schema[CONF_ENTITY_ID] = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=LIGHT_DOMAIN, exclude_entities=exclude_entities
            )
        )

        return self.async_show_form(step_id="new_light", data_schema=vol.Schema(schema))

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        """Create the options flow."""
        item_type = config_entry.data.get(CONF_TYPE, None)
        if item_type == TYPE_LIGHT:
            return LightOptionsFlowHandler(config_entry)
        elif item_type == TYPE_POOL:
            return PoolOptionsFlowHandler(config_entry)
        raise NotImplementedError


class HassDataOptionsFlow(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry):
        self._config_entry = config_entry

    async def _async_trigger_conf_update(
        self, title: str | None = None, data: Mapping | None = None
    ) -> ConfigFlowResult:
        # Trigger a Config Update by setting a unique CONF_FORCE_UPDATE
        return self.async_create_entry(
            title=title, data=data | {CONF_FORCE_UPDATE: uuid4().hex}
        )


class PoolOptionsFlowHandler(HassDataOptionsFlow):
    """Handle options flow for a Pool"""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__(config_entry)
        # Tracks which light entity currently has an active preview so we can
        # stop it before starting a new one on a different light, or on save.
        self._preview_light: str | None = None

    @callback
    def async_remove(self) -> None:
        """Stop any active preview when the flow is closed or cancelled.

        HA calls this synchronously, so we schedule the async stop as a task.
        """
        if self._preview_light is not None:
            self.hass.async_create_task(self._stop_active_preview())

    @callback
    def _strip_ephemeral_fields(
        self, user_input: dict[str, Any]
    ) -> tuple[str | None, str]:
        """Pop UI-only fields and return (test_light, test_action).

        These fields drive the form action selector but must never be
        persisted with the notification data.
        """
        test_light: str | None = user_input.pop(CONF_TEST_LIGHT, None)
        test_action: str = user_input.pop(CONF_TEST_ACTION, "save")
        return test_light, test_action

    @staticmethod
    def _append_color_to_pattern(user_input: dict[str, Any]) -> None:
        """Append the current color picker value as a JSON pattern step.

        Mutates user_input[CONF_NOTIFY_PATTERN] in place.
        """
        rgb = user_input.get(CONF_RGB_SELECTOR, WARM_WHITE_RGB)
        new_entry = json.dumps({"rgb": list(rgb), "delay": DEFAULT_COLOR_STEP_DELAY_SEC})
        current_pattern = list(user_input.get(CONF_NOTIFY_PATTERN) or [])
        current_pattern.append(new_entry)
        user_input[CONF_NOTIFY_PATTERN] = current_pattern

    async def _stop_active_preview(self) -> None:
        """Stop any running preview and clear the tracked light."""
        if self._preview_light is None:
            return
        try:
            await self.hass.services.async_call(
                DOMAIN,
                SERVICE_STOP_PREVIEW,
                {ATTR_ENTITY_ID: self._preview_light},
            )
        except Exception:
            _LOGGER.warning("Failed to stop preview on %s", self._preview_light)
        self._preview_light = None

    @callback
    def _extend_schema_with_test_fields(self, schema: vol.Schema) -> vol.Schema:
        """Append action-selector and optional test-on-light fields.

        'Add color to pattern' is always available. 'Preview notification on
        light' and the light selector appear only when at least one ColorNotify
        light wrapper exists.
        """
        light_ids = HassData.get_domain_light_entity_ids(self.hass)
        options: list[selector.SelectOptionDict] = [
            selector.SelectOptionDict(value="save", label="Save config and close"),
            selector.SelectOptionDict(
                value="add_color", label="Append selected color to pattern"
            ),
            *(
                [
                    selector.SelectOptionDict(
                        value="test", label="Preview sequence on selected light"
                    ),
                    selector.SelectOptionDict(
                        value="test_color",
                        label="Preview solid color on selected light",
                    ),
                    selector.SelectOptionDict(
                        value="stop_preview", label="Stop preview"
                    ),
                ]
                if light_ids
                else []
            ),
        ]
        return schema.extend(
            {
                vol.Required(CONF_TEST_ACTION, default="save"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                **(
                    {
                        vol.Optional(CONF_TEST_LIGHT): selector.EntitySelector(
                            selector.EntitySelectorConfig(include_entities=light_ids)
                        )
                    }
                    if light_ids
                    else {}
                ),
            }
        )

    async def _fire_preview_sequence(
        self,
        test_light: str,
        notification_data: dict[str, Any],
        color_only: bool = False,
    ) -> None:
        """Call the preview_sequence service on the selected light wrapper.

        When color_only is True, only the solid color is sent (no pattern),
        so the user can see what the color picker value looks like on the bulb.
        Expire settings are intentionally omitted so the service uses its own
        preview_duration.
        """
        service_data: dict[str, Any] = {ATTR_ENTITY_ID: test_light}
        fields = (
            (CONF_RGB_SELECTOR, CONF_PRIORITY, CONF_PEEK_ENABLED)
            if color_only
            else (CONF_NOTIFY_PATTERN, CONF_RGB_SELECTOR, CONF_PRIORITY, CONF_PEEK_ENABLED)
        )
        for key in fields:
            val = notification_data.get(key)
            if val is not None:
                service_data[key] = val
        try:
            await self.hass.services.async_call(
                DOMAIN, SERVICE_PREVIEW_SEQUENCE, service_data
            )
        except Exception:
            _LOGGER.warning("Failed to fire preview sequence on %s", test_light)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the options flow."""
        # forward to pool_init to differentiate in strings.json
        return await self.async_step_pool_init(user_input)

    async def async_step_pool_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the options flow."""
        return self.async_show_menu(
            step_id="pool_init",
            menu_options=[
                "add_notification",
                "add_notification_sample",
                "add_notification_copy",
                "modify_notification_select",
                "delete_notification",
            ],
        )

    async def async_step_add_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the Add Notification form."""
        errors: dict[str, str] = {}
        desc_placeholders: dict[str, str] = {}
        test_light: str | None = None
        test_action: str = "save"
        schema = self._extend_schema_with_test_fields(ADD_NOTIFY_SCHEMA)

        if user_input is not None:
            test_light, test_action = self._strip_ephemeral_fields(user_input)

            if test_action == "add_color":
                # Append the current color picker value as a new pattern entry,
                # then re-show the form. Skip validation — the user is still
                # building the pattern.
                self._append_color_to_pattern(user_input)
                schema = self.add_suggested_values_to_schema(
                    schema,
                    suggested_values=user_input
                    | {CONF_TEST_ACTION: "save"}
                    | ({CONF_TEST_LIGHT: test_light} if test_light else {}),
                )
                return self.async_show_form(
                    step_id="add_notification",
                    data_schema=schema,
                )

            if test_action == "stop_preview":
                await self._stop_active_preview()
                schema = self.add_suggested_values_to_schema(
                    schema,
                    suggested_values=user_input | {CONF_TEST_ACTION: "save"},
                )
                return self.async_show_form(
                    step_id="add_notification", data_schema=schema
                )

            # Validate pattern
            try:
                LightSequence.create_from_pattern(user_input.get(CONF_NOTIFY_PATTERN))
            except Exception as e:
                errors["pattern"] = str(e)
                desc_placeholders["error_detail"] = str(e)

            # Validate test-specific requirements
            if not errors and test_action in ("test", "test_color") and not test_light:
                errors[CONF_TEST_LIGHT] = "select_test_light"

            if not errors:
                if test_action in ("test", "test_color"):
                    # Stop any preview on a different light before starting
                    if self._preview_light and self._preview_light != test_light:
                        await self._stop_active_preview()
                    await self._fire_preview_sequence(
                        test_light, user_input, color_only=(test_action == "test_color")
                    )
                    self._preview_light = test_light
                    # Re-show form with all values preserved for further testing
                    schema = self.add_suggested_values_to_schema(
                        schema,
                        suggested_values=user_input
                        | {CONF_TEST_LIGHT: test_light, CONF_TEST_ACTION: test_action},
                    )
                    return self.async_show_form(
                        step_id="add_notification",
                        data_schema=schema,
                        errors=errors,
                        description_placeholders=desc_placeholders,
                    )
                # action == "save" — stop any running preview before saving
                await self._stop_active_preview()
                return await self.async_step_finish_add_notification(user_input)

            # Re-show form with current values and errors
            schema = self.add_suggested_values_to_schema(
                schema,
                suggested_values=user_input
                | {CONF_TEST_ACTION: test_action}
                | ({CONF_TEST_LIGHT: test_light} if test_light else {}),
            )

        return self.async_show_form(
            step_id="add_notification",
            data_schema=schema,
            errors=errors,
            description_placeholders=desc_placeholders,
        )

    async def async_step_add_notification_sample(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the Add Notification form with sample."""

        # Insert a sample pattern into the Add Notify schema
        sample_pattern = [
            "[",
            '{"rgb": [255,0,0], "delay": 0.750}',
            '{"rgb": [0,0,255], "delay": 0.750}',
            "],5",
            '{"rgb": [255,255,255]}',
        ]
        defaults = ADD_NOTIFY_DEFAULTS | {CONF_NOTIFY_PATTERN: sample_pattern}
        schema = self.add_suggested_values_to_schema(
            ADD_NOTIFY_SCHEMA, suggested_values=defaults
        )
        schema = self._extend_schema_with_test_fields(schema)

        return self.async_show_form(step_id="add_notification", data_schema=schema)

    async def async_step_add_notification_copy(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the Copy Notification Selection form."""
        if user_input is not None:
            entities = HassData.get_all_entities(self.hass, self._config_entry.entry_id)
            entity_to_copy = entities.get(user_input[CONF_UNIQUE_ID])
            state = (
                self.hass.states.get(entity_to_copy.entity_id)
                if entity_to_copy is not None
                else None
            )
            if state is None:
                return self.async_abort(reason="Can't locate notification to copy")
            defaults = (
                ADD_NOTIFY_DEFAULTS
                | state.attributes
                | {CONF_NAME: state.attributes[CONF_NAME] + " (copy)"}
            )
            schema = self.add_suggested_values_to_schema(
                ADD_NOTIFY_SCHEMA, suggested_values=defaults
            )
            schema = self._extend_schema_with_test_fields(schema)
            return self.async_show_form(step_id="add_notification", data_schema=schema)

        # Generate list of notifications from pool to select from
        select_list = self._get_notifications()
        options_schema = vol.Schema({vol.Required(CONF_UNIQUE_ID): vol.In(select_list)})

        return self.async_show_form(
            step_id="add_notification_copy", data_schema=options_schema
        )

    async def async_step_modify_notification_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the Modify Notification Selection form."""
        if user_input is not None:
            return await self.async_step_modify_notification(user_input)

        # Generate list of notifications from pool to select from
        select_list = self._get_notifications()

        options_schema = vol.Schema({vol.Required(CONF_UNIQUE_ID): vol.In(select_list)})

        return self.async_show_form(
            step_id="modify_notification_select", data_schema=options_schema
        )

    async def async_step_modify_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the Modify Notification form."""
        item_data: dict | None = None
        ntfctn_entries = self._config_entry.options.get(CONF_NTFCTN_ENTRIES, {})
        if uuid := user_input.get(CONF_UNIQUE_ID):
            item_data = ntfctn_entries.get(uuid)

        if item_data is None:
            return self.async_abort(reason="Can't locate notification to modify")

        errors: dict[str, str] = {}
        desc_placeholders: dict[str, str] = {}
        test_light: str | None = None
        test_action: str = "save"

        if CONF_FORCE_UPDATE in user_input:
            test_light, test_action = self._strip_ephemeral_fields(user_input)
            # Merge submitted values into item_data for all re-show paths
            merged = {
                **item_data,
                **{k: v for k, v in user_input.items() if k != CONF_FORCE_UPDATE},
            }

            if test_action == "add_color":
                # Append the current color picker value as a new pattern entry,
                # then fall through to re-show the form. Skip validation — the
                # user is still building the pattern.
                self._append_color_to_pattern(merged)
                item_data = merged
                test_action = "save"
            elif test_action == "stop_preview":
                await self._stop_active_preview()
                item_data = merged
                test_action = "save"
            else:
                # Validate
                try:
                    LightSequence.create_from_pattern(
                        user_input.get(CONF_NOTIFY_PATTERN)
                    )
                except Exception as e:
                    errors["pattern"] = str(e)
                    desc_placeholders["error_detail"] = str(e)

                # Validate test-specific requirements
                if not errors and test_action in ("test", "test_color") and not test_light:
                    errors[CONF_TEST_LIGHT] = "select_test_light"

                if not errors:
                    if test_action in ("test", "test_color"):
                        # Stop any preview on a different light before starting
                        if self._preview_light and self._preview_light != test_light:
                            await self._stop_active_preview()
                        await self._fire_preview_sequence(
                            test_light, user_input, color_only=(test_action == "test_color")
                        )
                        self._preview_light = test_light
                        item_data = merged
                    else:
                        # FORCE_UPDATE was the flag indicating modification is done
                        await self._stop_active_preview()
                        user_input.pop(CONF_FORCE_UPDATE)
                        return await self.async_step_finish_add_notification(user_input)
                else:
                    # Failed validation — re-show submitted values, not last-saved
                    item_data = merged

        # Merge in default values
        item_data = ADD_NOTIFY_DEFAULTS | item_data | {CONF_FORCE_UPDATE: 1}

        # Carry test field selections through to the re-displayed form
        if test_light:
            item_data[CONF_TEST_LIGHT] = test_light
        item_data[CONF_TEST_ACTION] = test_action

        # Build schema: notification fields + modify sentinels + test fields
        schema = ADD_NOTIFY_SCHEMA.extend(
            {
                # Flag to indicate modify_notification has been submitted
                vol.Optional(CONF_FORCE_UPDATE): selector.ConstantSelector(
                    selector.ConstantSelectorConfig(label="", value=True)
                ),
                vol.Optional(CONF_UNIQUE_ID): selector.ConstantSelector(
                    selector.ConstantSelectorConfig(label="", value=uuid)
                ),
            }
        )
        schema = self._extend_schema_with_test_fields(schema)
        schema = self.add_suggested_values_to_schema(schema, suggested_values=item_data)

        return self.async_show_form(
            step_id="modify_notification",
            data_schema=schema,
            errors=errors,
            description_placeholders=desc_placeholders,
        )

    async def async_step_delete_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the Delete Notification form."""
        if user_input is not None:
            # Set 'to delete' entries and trigger reload
            delete_entry = {CONF_DELETE: user_input.get(CONF_DELETE, [])}
            return await self._async_trigger_conf_update(
                data=self._config_entry.options | delete_entry
            )

        # Generate list of notifications from pool to select from
        select_list = self._get_notifications()
        options_schema = vol.Schema(
            {
                vol.Optional(CONF_DELETE): cv.multi_select(select_list),
            }
        )
        return self.async_show_form(
            step_id="delete_notification", data_schema=options_schema
        )

    async def async_step_finish_add_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Finalize adding the notification."""
        # ensure defaults are set
        user_input = ADD_NOTIFY_DEFAULTS | user_input
        uuid = user_input.get(CONF_UNIQUE_ID)
        if uuid is None:
            uuid = uuid4().hex
            user_input[CONF_UNIQUE_ID] = uuid

        # Add to the entry to hass_data
        ntfctn_entries = self._config_entry.options.get(CONF_NTFCTN_ENTRIES, {})
        ntfctn_entries[uuid] = user_input

        return await self._async_trigger_conf_update(
            data=self._config_entry.options | {CONF_NTFCTN_ENTRIES: ntfctn_entries}
        )

    @callback
    def _get_notifications(self) -> dict[str, str]:
        # Generate list of notifications from pool to select from, sorted by priority
        ntfctns = self._config_entry.options.get(CONF_NTFCTN_ENTRIES, {})
        ntfctns = sorted(
            ntfctns.items(), key=lambda x: x[1].get(CONF_PRIORITY), reverse=True
        )

        entities = HassData.get_all_entities(self.hass, self._config_entry.entry_id)
        select_list: dict[str, str] = {}
        for uid, ntfctn in ntfctns:
            entity = entities[uid]
            select_list[uid] = (
                f"{ntfctn.get(CONF_NAME)} [{entity.entity_id}] Prio: {ntfctn.get(CONF_PRIORITY):.0f}"
            )
        return select_list


class LightOptionsFlowHandler(HassDataOptionsFlow):
    """Handle an options flow."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__(config_entry)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the options flow."""
        # forward to light_init to differentiate in strings.json
        return await self.async_step_light_init(user_input)

    async def async_step_light_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the options flow."""
        return self.async_show_menu(
            step_id="light_init",
            menu_options=["light_options", "subscriptions"],
        )

    async def async_step_light_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and save the configurable light settings."""
        if user_input is not None:
            return await self._async_trigger_conf_update(
                data=self._config_entry.options
                | {
                    CONF_ENABLE_EVENT_LOG: user_input[CONF_ENABLE_EVENT_LOG],
                    CONF_DYNAMIC_PRIORITY: user_input[CONF_DYNAMIC_PRIORITY],
                    CONF_PRIORITY: user_input[CONF_PRIORITY],
                }
            )

        current = self._config_entry
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ENABLE_EVENT_LOG,
                    default=current.options.get(
                        CONF_ENABLE_EVENT_LOG,
                        current.data.get(CONF_ENABLE_EVENT_LOG, True),
                    ),
                ): cv.boolean,
                vol.Required(
                    CONF_DYNAMIC_PRIORITY,
                    default=current.options.get(
                        CONF_DYNAMIC_PRIORITY,
                        current.data.get(CONF_DYNAMIC_PRIORITY, True),
                    ),
                ): cv.boolean,
                vol.Optional(
                    CONF_PRIORITY,
                    default=current.options.get(
                        CONF_PRIORITY,
                        current.data.get(CONF_PRIORITY, DEFAULT_PRIORITY),
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=1,
                        max=MAXIMUM_PRIORITY,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="light_options", data_schema=schema)

    async def async_step_subscriptions(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the Notification Subscriptions form."""
        if user_input is not None:
            return await self.async_step_finish_subscriptions(user_input)

        pools = HassData.get_all_pools(self.hass)
        pool_items = [
            {"value": uid, "label": f"{pool_info[CONF_ENTRY].title}"}
            for uid, pool_info in pools.items()
        ]
        # TODO: Set up pool subscriptions
        # TODO: Update light when pool subscriptions change

        # Set up multi-select
        schema = {k: copy.copy(v) for k, v in SUBSCRIPTION_SCHEMA.schema.items()}
        schema[TYPE_POOL] = selector.SelectSelector(
            selector.SelectSelectorConfig(multiple=True, options=pool_items)
        )
        schema = vol.Schema(schema)
        # Get subscribed pools, filtering out pools that don't exist
        cur_subs: dict = self._config_entry.options.get(CONF_SUBSCRIPTION, {})
        cur_subs[TYPE_POOL] = [x for x in cur_subs.get(TYPE_POOL, []) if x in pools]
        defaults: dict[str, dict] = SUBSCRIPTION_DEFAULTS | cur_subs
        schema = self.add_suggested_values_to_schema(schema, suggested_values=defaults)

        return self.async_show_form(step_id="subscriptions", data_schema=schema)

    async def async_step_finish_subscriptions(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Finalize updating subscriptions, preserving all other options."""
        return await self._async_trigger_conf_update(
            data=self._config_entry.options | {CONF_SUBSCRIPTION: user_input}
        )
