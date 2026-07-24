"""Button platform for Spoolman Active Spool (Moonraker).

Two kinds of buttons:

- One "Nastav na <printer>" button per existing Spoolman spool device
  (attached to that device). Devices are matched purely via the device
  registry - see spoolman_registry.py.
- One "Vymaž aktivní cívku" button per printer, living on this
  integration's own printer device.

Cleanup for the per-spool buttons: when the spoolman integration removes a
spool device, Home Assistant core's entity registry automatically removes
every entity tied to that device - including our button - because our
config entry is registered against that shared device as soon as we add an
entity with matching device_info.identifiers. No extra cleanup code needed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry, DeviceInfo
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ActiveSpoolCoordinator
from .moonraker import async_set_active_spool
from .spoolman_registry import (
    printer_device_identifier,
    printer_object_id,
    spool_id_from_device,
)

_LOGGER = logging.getLogger(__name__)

SET_ACTIVE_ICON = "mdi:movie-roll"
CLEAR_ACTIVE_ICON = "mdi:circle-off-outline"


def _resolve_entity_id(
    hass: HomeAssistant,
    ent_reg: er.EntityRegistry,
    unique_id: str,
    desired_object_id: str,
) -> str:
    """entity_id for a button, renamed in the registry if the printer name
    (and therefore the desired entity_id) changed since it was first created.
    """
    desired_entity_id = f"{Platform.BUTTON}.{desired_object_id}"
    existing_entity_id = ent_reg.async_get_entity_id(
        Platform.BUTTON, DOMAIN, unique_id
    )

    if existing_entity_id is None:
        return generate_entity_id("button.{}", desired_object_id, hass=hass)

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
    """Set up per-spool "set active" buttons and the "clear active" button."""
    device_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    coordinator: ActiveSpoolCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    known_device_ids: set[str] = set()

    def _build_set_active_button(device: DeviceEntry) -> SetActiveSpoolButton | None:
        spool_id = spool_id_from_device(device)
        if spool_id is None:
            return None
        known_device_ids.add(device.id)
        return SetActiveSpoolButton(hass, ent_reg, entry, coordinator, device, spool_id)

    initial_entities: list[ButtonEntity] = [
        ClearActiveSpoolButton(hass, ent_reg, entry, coordinator)
    ]
    initial_entities += [
        button
        for device in device_reg.devices.values()
        if (button := _build_set_active_button(device)) is not None
    ]

    async_add_entities(initial_entities)
    _LOGGER.info(
        "Spoolman Active Spool (%s): added %d spool button(s) + 1 clear button",
        entry.title,
        len(initial_entities) - 1,
    )

    @callback
    def _handle_device_registry_update(event: Event) -> None:
        if event.data.get("action") != "create":
            return
        device = device_reg.async_get(event.data["device_id"])
        if device is None:
            return
        button = _build_set_active_button(device)
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
    _attr_icon = SET_ACTIVE_ICON

    def __init__(
        self,
        hass: HomeAssistant,
        ent_reg: er.EntityRegistry,
        entry: ConfigEntry,
        coordinator: ActiveSpoolCoordinator,
        device: DeviceEntry,
        spool_id: int,
    ) -> None:
        """Attach to the existing Spoolman device instead of creating a new one."""
        self._spool_id = spool_id
        self._coordinator = coordinator
        self._moonraker_url = coordinator.moonraker_url
        self._verify_ssl = coordinator.verify_ssl

        self._attr_unique_id = f"{entry.entry_id}_spool_{spool_id}_set_active"
        self._attr_name = f"Nastav na {entry.title}"
        self._attr_device_info = DeviceInfo(identifiers=device.identifiers)

        object_id = f"spoolman_spool_{spool_id}_set_active_{printer_object_id(entry.title)}"
        self.entity_id = _resolve_entity_id(
            hass, ent_reg, self._attr_unique_id, object_id
        )

    async def async_press(self) -> None:
        """Tell this printer's Moonraker to use this spool as the active one."""
        try:
            await async_set_active_spool(
                self.hass, self._moonraker_url, self._verify_ssl, self._spool_id
            )
        except aiohttp.ClientError as err:
            _LOGGER.error(
                "Failed to set spool %s as active on %s: %s",
                self._spool_id,
                self._moonraker_url,
                err,
            )
            raise
        # Moonraker needs a moment to actually apply the change before a
        # refresh would just read back the old value.
        await asyncio.sleep(2)
        await self._coordinator.async_request_refresh()


class ClearActiveSpoolButton(CoordinatorEntity[ActiveSpoolCoordinator], ButtonEntity):
    """Button that unsets the active spool on one printer (disables tracking)."""

    _attr_has_entity_name = False
    _attr_icon = CLEAR_ACTIVE_ICON

    def __init__(
        self,
        hass: HomeAssistant,
        ent_reg: er.EntityRegistry,
        entry: ConfigEntry,
        coordinator: ActiveSpoolCoordinator,
    ) -> None:
        super().__init__(coordinator)
        self._moonraker_url = coordinator.moonraker_url
        self._verify_ssl = coordinator.verify_ssl

        self._attr_unique_id = f"{entry.entry_id}_active_spool_clear"
        self._attr_name = "Vymaž aktivní cívku"
        self._attr_device_info = DeviceInfo(
            identifiers={printer_device_identifier(entry.entry_id)},
            name=entry.title,
            manufacturer="Spoolman Active Spool (Moonraker)",
            model="Tiskárna",
        )
        object_id = f"spoolman_active_{printer_object_id(entry.title)}_spool_clear"
        self.entity_id = _resolve_entity_id(
            hass, ent_reg, self._attr_unique_id, object_id
        )

    async def async_press(self) -> None:
        """Unset the active spool on this printer."""
        try:
            await async_set_active_spool(
                self.hass, self._moonraker_url, self._verify_ssl, None
            )
        except aiohttp.ClientError as err:
            _LOGGER.error(
                "Failed to clear active spool on %s: %s", self._moonraker_url, err
            )
            raise
        await asyncio.sleep(2)
        await self.coordinator.async_request_refresh()
