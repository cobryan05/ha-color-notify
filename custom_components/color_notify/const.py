"""Constants for the ColorNotify integration."""

from typing import Final

DOMAIN: Final = "color_notify"

TYPE_POOL: Final = "pool"
TYPE_LIGHT: Final = "light"

CONF_RGB_SELECTOR: Final = "color_picker"
CONF_SUBSCRIPTION: Final = "subscription"
CONF_CLEANUP: Final = "cleanup"
CONF_NOTIFY_PATTERN: Final = "pattern"
CONF_EXPIRE_ENABLED: Final = "expire_enabled"
CONF_NTFCTN_ENTRIES: Final = "ntfctn_entries"
CONF_PRIORITY: Final = "priority"
CONF_DELETE: Final = "delete"
CONF_ADD: Final = "add"
CONF_ENTRY_ID: Final = "entry_id"
CONF_ENTRY: Final = "entry"
CONF_PEEK_TIME: Final = "peek_time"
CONF_PEEK_ENABLED: Final = "peek_enabled"
CONF_DYNAMIC_PRIORITY: Final = "dynamic_priority"
CONF_ENABLE_EVENT_LOG: Final = "enable_event_log"
CONF_WARMUP_TIME: Final = "warmup_time"
CONF_EVENT_ENTITY: Final = "event_entity"
CONF_LOADED_PLATFORMS: Final = "loaded_platforms"

ACTION_CYCLE_SAME: Final = "cycle_same"

CONF_TEST_LIGHT: Final = "test_light"
CONF_TEST_ACTION: Final = "test_action"
SERVICE_PREVIEW_SEQUENCE: Final = "preview_sequence"
SERVICE_STOP_PREVIEW: Final = "stop_preview"
PREVIEW_NOTIFY_ID: Final = "__preview__"
MAX_PREVIEW_DURATION_SEC: Final = 300  # 5-minute safety cap
DEFAULT_COLOR_STEP_DELAY_SEC: Final = 1.0  # default delay injected by "Append color" action

OFF_RGB: Final = (0, 0, 0)
WARM_WHITE_RGB: Final = (255, 249, 216)

INIT_STATE_UPDATE_DELAY_SEC: Final = 1
DEFAULT_PRIORITY: Final = 1000
MAXIMUM_PRIORITY: Final = 99999999
EXPECTED_SERVICE_CALL_TIMEOUT: Final = 5
