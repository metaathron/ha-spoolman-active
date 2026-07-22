"""Constants for the Spoolman Active Spool (Moonraker) integration."""

DOMAIN = "spoolman_active_spool"

# Domain used by Disane87/spoolman-homeassistant. Its spool devices carry
# identifiers of the form (SPOOLMAN_DOMAIN, spoolman_url, "spool_<id>"), and
# its entities have unique_ids of the form
# "spoolman_<spoolman_entry_id>_spool_<spool_id>_<suffix>".
SPOOLMAN_DOMAIN = "spoolman"

CONF_NAME = "name"
CONF_MOONRAKER_URL = "moonraker_url"
CONF_VERIFY_SSL = "verify_ssl"
CONF_POLL_INTERVAL = "poll_interval"

DEFAULT_VERIFY_SSL = True
DEFAULT_POLL_INTERVAL = 30  # seconds
MIN_POLL_INTERVAL = 1  # seconds

REQUEST_TIMEOUT = 10
