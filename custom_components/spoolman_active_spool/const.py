"""Constants for the Spoolman Active Spool (Moonraker) integration."""

DOMAIN = "spoolman_active_spool"

# Domain used by Disane87/spoolman-homeassistant. Its spool devices carry
# identifiers of the form (SPOOLMAN_DOMAIN, spoolman_url, "spool_<id>").
SPOOLMAN_DOMAIN = "spoolman"

CONF_NAME = "name"
CONF_MOONRAKER_URL = "moonraker_url"
CONF_VERIFY_SSL = "verify_ssl"

DEFAULT_VERIFY_SSL = True
REQUEST_TIMEOUT = 10
