"""Select platform for Spoolman Active Spool (Moonraker).

One dropdown per printer, listing every spool known to Home Assistant
(via the Spoolman integration's own devices), labelled and sorted as
"material - vendor - name". Picking an option posts to this printer's
Moonraker; the dropdown's current value follows the coordinator, so it
also reflects spools set active some other way (a macro, Mainsail, one
of our own buttons) once the next poll comes in.
"""

from __future__ import annotations

import asyncio
import logging

import aiohttp

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ActiveSpoolCoordinator
from .moonraker import async_set_active_spool
from .spoolman_registry import (
    iter_spool_devices,
    printer_device_identifier,
    printer_object_id,
    spool_state_value,
)

_LOGGER = logging.getLogger(__name__)

ICON = "mdi:movie-roll"
NO_SELECTION = "Žádná"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ActiveSpoolCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    async_add_entities([ActiveSpoolSelect(hass, entry, coordinator)])


class ActiveSpoolSelect(CoordinatorEntity[ActiveSpoolCoordinator], SelectEntity):
    """Dropdown to set (and show) the active spool for one printer."""

    _attr_has_entity_name = False
    _attr_icon = ICON

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, coordinator: ActiveSpoolCoordinator
    ) -> None:
        super().__init__(coordinator)
        self._hass = hass
        self._entry = entry
        self._dev_reg = dr.async_get(hass)
        self._moonraker_url = coordinator.moonraker_url
        self._verify_ssl = coordinator.verify_ssl

        # label -> spool_id, rebuilt whenever spool devices appear/disappear
        self._label_by_spool_id: dict[int, str] = {}
        self._spool_id_by_label: dict[str, int] = {}

        self._attr_unique_id = f"{entry.entry_id}_active_spool_select"
        self._attr_name = "Aktivní cívka"
        self.entity_id = (
            f"select.spoolman_active_{printer_object_id(entry.title)}_spool"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={printer_device_identifier(entry.entry_id)},
            name=entry.title,
            manufacturer="Spoolman Active Spool (Moonraker)",
            model="Tiskárna",
        )

        self._refresh_options()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._refresh_options()
        self._refresh_current_option()
        self.async_on_remove(
            self.hass.bus.async_listen(
                dr.EVENT_DEVICE_REGISTRY_UPDATED, self._handle_device_registry_update
            )
        )

    @callback
    def _handle_device_registry_update(self, event: Event) -> None:
        if event.data.get("action") not in ("create", "remove"):
            return
        self._refresh_options()
        self._refresh_current_option()
        self.async_write_ha_state()

    def _refresh_options(self) -> None:
        """Rebuild the "materiál - výrobce - název #id" option list from HA state."""
        rows: list[tuple[str, str, str, int]] = []
        for spool_id, device in iter_spool_devices(self._dev_reg):
            material = spool_state_value(self._hass, device.id, "material") or "?"
            vendor = spool_state_value(self._hass, device.id, "vendor") or "?"
            name = (
                spool_state_value(self._hass, device.id, "filament_name")
                or f"Cívka {spool_id}"
            )
            rows.append((material, vendor, name, spool_id))

        rows.sort(key=lambda row: (row[0].lower(), row[1].lower(), row[2].lower()))

        self._label_by_spool_id = {}
        self._spool_id_by_label = {}
        for material, vendor, name, spool_id in rows:
            label = f"{material} - {vendor} - {name} #{spool_id}"
            self._label_by_spool_id[spool_id] = label
            self._spool_id_by_label[label] = spool_id

        self._attr_options = [NO_SELECTION, *self._label_by_spool_id.values()]

    def _refresh_current_option(self) -> None:
        spool_id = self.coordinator.data.get("spool_id") if self.coordinator.data else None
        self._attr_current_option = (
            self._label_by_spool_id.get(spool_id, NO_SELECTION)
            if spool_id is not None
            else NO_SELECTION
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self._refresh_current_option()
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        spool_id = None if option == NO_SELECTION else self._spool_id_by_label.get(option)
        if option != NO_SELECTION and spool_id is None:
            _LOGGER.warning(
                "Spoolman Active Spool (%s): unknown option %s selected",
                self._entry.title,
                option,
            )
            return

        try:
            await async_set_active_spool(
                self._hass, self._moonraker_url, self._verify_ssl, spool_id
            )
        except aiohttp.ClientError as err:
            _LOGGER.error(
                "Failed to set active spool on %s: %s", self._moonraker_url, err
            )
            raise

        self._attr_current_option = option
        self.async_write_ha_state()
        await asyncio.sleep(2)
        await self.coordinator.async_request_refresh()
