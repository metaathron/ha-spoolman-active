"""Constants for the Spoolman Active Spool (Moonraker) integration."""

DOMAIN = "spoolman_active_spool"

# Domain used by Disane87/spoolman-homeassistant. Its spool devices carry
# identifiers of the form (SPOOLMAN_DOMAIN, spoolman_url, "spool_<id>"), and
# its entities have unique_ids of the form
# "spoolman_<spoolman_entry_id>_spool_<spool_id>_<suffix>".
SPOOLMAN_DOMAIN = "spoolman"

# Every config entry is one of two kinds, told apart by CONF_ENTRY_TYPE.
# Entries created before this field existed (v1.1.x) have no entry_type at
# all - they are always printers, so every read uses
# entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_PRINTER).
CONF_ENTRY_TYPE = "entry_type"
ENTRY_TYPE_PRINTER = "printer"
ENTRY_TYPE_HUB = "webhook_hub"

CONF_NAME = "name"
CONF_MOONRAKER_URL = "moonraker_url"
CONF_VERIFY_SSL = "verify_ssl"
CONF_POLL_INTERVAL = "poll_interval"

CONF_WEBHOOK_ID = "webhook_id"
CONF_LOCAL_ONLY = "local_only"
CONF_BASE_URL = "base_url"

DEFAULT_VERIFY_SSL = True
DEFAULT_POLL_INTERVAL = 30  # seconds
MIN_POLL_INTERVAL = 1  # seconds
DEFAULT_LOCAL_ONLY = True

REQUEST_TIMEOUT = 10

# Short timeout for the best-effort "is this printer online" check shown on
# the webhook picker page - deliberately much shorter than REQUEST_TIMEOUT
# so a dead printer doesn't stall page rendering; a timeout just means the
# page shows an "offline" hint, it never blocks the actual set/clear action.
ONLINE_CHECK_TIMEOUT = 2
