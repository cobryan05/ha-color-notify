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
CONF_RESTORE_POWER: Final = "restore_power"

ACTION_CYCLE_SAME: Final = "cycle_same"

OFF_RGB: Final = (0, 0, 0)
WARM_WHITE_RGB: Final = (255, 249, 216)

INIT_STATE_UPDATE_DELAY_SEC: Final = 1
DEFAULT_PRIORITY: Final = 1000
MAXIMUM_PRIORITY: Final = 99999999
EXPECTED_SERVICE_CALL_TIMEOUT: Final = 5
