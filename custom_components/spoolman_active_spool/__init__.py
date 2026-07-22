"""The Spoolman Active Spool (Moonraker) integration.

For every device that Disane87/spoolman-homeassistant created for a spool,
adds a "Nastav na <printer>" button. For each configured printer it also
adds a small device with the active spool's data (mirrored live from the
Spoolman integration's own entities), a "Vymaž aktivní cívku" button and a
dropdown to pick the active spool - all driven by polling Moonraker's
``/server/spoolman/status`` for the currently active spool_id only.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import ActiveSpoolCoordinator

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SENSOR, Platform.SELECT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry (one printer)."""
    coordinator = ActiveSpoolCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coordinator}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
