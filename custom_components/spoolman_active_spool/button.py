"""Button platform for Spoolman Active Spool (Moonraker).

For every device that Disane87/spoolman-homeassistant created for a spool,
this adds one button per configured printer ("Nastav na <tiskárna>").
Pressing it calls this printer's Moonraker with the spool's id, so
Moonraker starts reporting filament usage for that spool.

Devices are matched purely via the device registry (identifiers of the
form (SPOOLMAN_DOMAIN, spoolman_url, "spool_<id>")) - this integration
does not talk to Spoolman directly and does not need the spoolman
integration's coordinator or API wrapper.

Cleanup: when the spoolman integration removes a spool device (it does
so via device_registry.async_remove_device on cleanup), Home Assistant
core's entity registry automatically removes every entity tied to that
device - including our button - because our config entry is registered
against that shared device as soon as we add an entity with matching
device_info.identifiers. No extra cleanup code is needed here.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry, DeviceInfo
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .const import (
    CONF_MOONRAKER_URL,
    CONF_VERIFY_SSL,
    DOMAIN,
    REQUEST_TIMEOUT,
    SPOOLMAN_DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

ICON = "mdi:movie-roll"


def _spool_id_from_device(device: DeviceEntry) -> int | None:
    """Return the Spoolman spool id if this is a spool device, else None."""
    for identifier in device.identifiers:
        if (
            len(identifier) >= 3
            and identifier[0] == SPOOLMAN_DOMAIN
            and isinstance(identifier[2], str)
            and identifier[2].startswith("spool_")
        ):
            try:
                return int(identifier[2].removeprefix("spool_"))
            except ValueError:
                return None
    return None


def _object_id(spool_id: int, printer_name: str) -> str:
    """entity_id-friendly slug: spoolman_spool_<id>_set_active_<printer>."""
    return f"spoolman_spool_{spool_id}_set_active_{slugify(printer_name)}"


def _resolve_entity_id(
    hass: HomeAssistant,
    ent_reg: er.EntityRegistry,
    unique_id: str,
    desired_object_id: str,
) -> str:
    """Return the entity_id this button should use, renaming it in the
    registry if the printer name (and therefore the desired entity_id)
    changed since the entity was first created.
    """
    desired_entity_id = f"{Platform.BUTTON}.{desired_object_id}"
    existing_entity_id = ent_reg.async_get_entity_id(
        Platform.BUTTON, DOMAIN, unique_id
    )

    if existing_entity_id is None:
        # Brand new entity - avoid clobbering an unrelated entity_id.
        return generate_entity_id(
            "button.{}", desired_object_id, hass=hass
        )

    if existing_entity_id == desired_entity_id:
        return existing_entity_id

    try:
        updated = ent_reg.async_update_entity(
            existing_entity_id, new_entity_id=desired_entity_id
        )
    except ValueError:
        _LOGGER.warning(
            "Nepodařilo se přejmenovat %s na %s (cílové entity_id už existuje) "
            "- entity_id zůstává beze změny",
            existing_entity_id,
            desired_entity_id,
        )
        return existing_entity_id

    return updated.entity_id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one button per existing spool device, and watch for new ones."""
    device_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    known_device_ids: set[str] = set()

    def _build_button(device: DeviceEntry) -> SetActiveSpoolButton | None:
        spool_id = _spool_id_from_device(device)
        if spool_id is None:
            return None
        known_device_ids.add(device.id)
        return SetActiveSpoolButton(hass, ent_reg, entry, device, spool_id)

    initial_entities = [
        button
        for device in device_reg.devices.values()
        if (button := _build_button(device)) is not None
    ]

    if initial_entities:
        async_add_entities(initial_entities)

    if not initial_entities:
        _LOGGER.warning(
            "Spoolman Active Spool (%s): no spool devices found yet. "
            "Make sure the Spoolman integration (Disane87/spoolman-homeassistant) "
            "is installed and has created spool devices - buttons for spools "
            "added later will appear automatically",
            entry.title,
        )
    else:
        _LOGGER.info(
            "Spoolman Active Spool (%s): added %d button(s) for existing spool devices",
            entry.title,
            len(initial_entities),
        )

    @callback
    def _handle_device_registry_update(event: Event) -> None:
        if event.data.get("action") != "create":
            return
        device = device_reg.async_get(event.data["device_id"])
        if device is None:
            return
        button = _build_button(device)
        if button is not None:
            _LOGGER.info(
                "Spoolman Active Spool (%s): new spool device detected, adding button",
                entry.title,
            )
            async_add_entities([button])

    entry.async_on_unload(
        hass.bus.async_listen(
            dr.EVENT_DEVICE_REGISTRY_UPDATED, _handle_device_registry_update
        )
    )


class SetActiveSpoolButton(ButtonEntity):
    """Button that sets one spool as the active spool on one printer."""

    _attr_has_entity_name = False
    _attr_icon = ICON

    def __init__(
        self,
        hass: HomeAssistant,
        ent_reg: er.EntityRegistry,
        entry: ConfigEntry,
        device: DeviceEntry,
        spool_id: int,
    ) -> None:
        """Attach to the existing Spoolman device instead of creating a new one."""
        self._spool_id = spool_id
        self._moonraker_url = entry.data[CONF_MOONRAKER_URL].rstrip("/")
        self._verify_ssl = entry.data.get(CONF_VERIFY_SSL, True)

        self._attr_unique_id = f"{entry.entry_id}_spool_{spool_id}_set_active"
        self._attr_name = f"Nastav na {entry.title}"
        self._attr_device_info = DeviceInfo(identifiers=device.identifiers)

        object_id = _object_id(spool_id, entry.title)
        self.entity_id = _resolve_entity_id(
            hass, ent_reg, self._attr_unique_id, object_id
        )

    async def async_press(self) -> None:
        """Tell this printer's Moonraker to use this spool as the active one."""
        url = f"{self._moonraker_url}/server/spoolman/spool_id"
        session = async_get_clientsession(self.hass)
        ssl_kwarg: dict[str, Any] = {} if self._verify_ssl else {"ssl": False}

        try:
            async with session.post(
                url,
                json={"spool_id": self._spool_id},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                **ssl_kwarg,
            ) as response:
                response.raise_for_status()
        except aiohttp.ClientError as err:
            _LOGGER.error(
                "Failed to set spool %s as active on %s: %s",
                self._spool_id,
                self._moonraker_url,
                err,
            )
            raise
