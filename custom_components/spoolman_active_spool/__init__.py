"""The Spoolman Active Spool (Moonraker) integration.

Two kinds of config entry:

- printer: adds a "Nastav na <printer>" button to every Spoolman spool
  device, and a device of its own with mirrored active-spool sensors, a
  select dropdown and a "clear active spool" button (see coordinator.py,
  button.py, sensor.py, select.py).
- webhook_hub (single instance): registers the shared QR-code webhook and
  adds a QR-code image entity to every Spoolman spool device, plus a
  diagnostic sensor showing the webhook URL (see webhook_hub.py, image.py,
  sensor.py).
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_HUB, ENTRY_TYPE_PRINTER
from .coordinator import ActiveSpoolCoordinator
from .webhook_hub import async_register_webhook

PLATFORMS_PRINTER: list[Platform] = [Platform.BUTTON, Platform.SENSOR, Platform.SELECT]
PLATFORMS_HUB: list[Platform] = [Platform.IMAGE, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry (one printer, or the webhook hub)."""
    entry_type = entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_PRINTER)

    if entry_type == ENTRY_TYPE_HUB:
        await async_register_webhook(hass, entry)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_HUB)
        return True

    coordinator = ActiveSpoolCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coordinator}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_PRINTER)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    entry_type = entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_PRINTER)
    platforms = PLATFORMS_HUB if entry_type == ENTRY_TYPE_HUB else PLATFORMS_PRINTER

    unloaded = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unloaded and entry_type != ENTRY_TYPE_HUB:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
