"""The Spoolman Active Spool (Moonraker) integration.

Adds a "Set as active" button to every device created by the
Disane87/spoolman-homeassistant integration. Pressing it tells one
printer's Moonraker instance (configured per config entry) to use that
spool as the active spool, via ``POST /server/spoolman/spool_id``.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

PLATFORMS = ["button"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry (one printer)."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
