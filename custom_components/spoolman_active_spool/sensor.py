"""Sensor platform for Spoolman Active Spool (Moonraker).

For the printer's currently active spool, mirrors every sensor entity
that Disane87/spoolman-homeassistant already created for that spool's
device - "spoolman_spool_<id>_<suffix>" becomes
"spoolman_active_<printer>_spool[_<suffix>]" on this printer's own
device.

Each mirror is its own CoordinatorEntity (the same proven pattern used by
select.py): on every coordinator poll it re-checks which spool is active,
re-points itself at that spool's matching source entity if needed, and
pulls its current value. Between polls, a direct state-change listener on
the source entity keeps the value live. The platform-level listener below
only has to create a mirror the first time a not-yet-seen suffix (e.g. a
custom extra field) shows up.
"""

from __future__ import annotations

import logging
from typing import Callable

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_HUB, ENTRY_TYPE_PRINTER
from .coordinator import ActiveSpoolCoordinator
from .spoolman_registry import (
    find_spool_device,
    printer_device_identifier,
    printer_object_id,
    spool_entity_picture,
    spool_source_entities,
)
from .webhook_hub import webhook_full_url

_LOGGER = logging.getLogger(__name__)


def _mirror_object_id(printer_name: str, suffix: str) -> str:
    base = f"spoolman_active_{printer_object_id(printer_name)}_spool"
    return base if suffix == "id" else f"{base}_{suffix}"


def _friendly_name(suffix: str) -> str:
    if suffix == "id":
        return "Aktivní cívka"
    return suffix.replace("_", " ").capitalize()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_type = entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_PRINTER)
    if entry_type == ENTRY_TYPE_HUB:
        async_add_entities([WebhookUrlSensor(hass, entry)])
        return

    coordinator: ActiveSpoolCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    known_suffixes: set[str] = set()

    def _create_new_mirrors() -> None:
        """Add a MirrorSensor for any suffix we haven't seen before."""
        spool_id = coordinator.data.get("spool_id") if coordinator.data else None
        if spool_id is None:
            return
        device = find_spool_device(dev_reg, spool_id)
        if device is None:
            return

        new_entities = []
        for source in spool_source_entities(ent_reg, device.id, spool_id):
            if source.suffix in known_suffixes:
                continue
            known_suffixes.add(source.suffix)
            new_entities.append(
                MirrorSensor(hass, entry, coordinator, dev_reg, ent_reg, source.suffix)
            )
        if new_entities:
            _LOGGER.debug(
                "Spoolman Active Spool (%s): adding %d new mirror sensor(s): %s",
                entry.title,
                len(new_entities),
                [e._suffix for e in new_entities],  # noqa: SLF001
            )
            async_add_entities(new_entities)

    _create_new_mirrors()

    @callback
    def _handle_coordinator_update() -> None:
        _create_new_mirrors()

    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))


class MirrorSensor(CoordinatorEntity[ActiveSpoolCoordinator], SensorEntity):
    """One mirrored attribute of the printer's active spool."""

    _attr_has_entity_name = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: ActiveSpoolCoordinator,
        dev_reg: dr.DeviceRegistry,
        ent_reg: er.EntityRegistry,
        suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._hass = hass
        self._dev_reg = dev_reg
        self._ent_reg = ent_reg
        self._suffix = suffix
        self._source_entity_id: str | None = None
        self._unsub_state: Callable[[], None] | None = None

        self._attr_unique_id = f"{entry.entry_id}_active_spool_{suffix}"
        self._attr_name = _friendly_name(suffix)
        self.entity_id = f"sensor.{_mirror_object_id(entry.title, suffix)}"
        self._attr_device_info = DeviceInfo(
            identifiers={printer_device_identifier(entry.entry_id)},
            name=entry.title,
            manufacturer="Spoolman Active Spool (Moonraker)",
            model="Tiskárna",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._resync()

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Called on every coordinator poll - re-check which spool is active."""
        self._resync()

    @callback
    def _handle_source_event(self, event: Event[EventStateChangedData]) -> None:
        """Called whenever the source entity's own value changes."""
        self._apply_source_state(event.data["new_state"], self._id_picture_override())

    def _id_picture_override(self) -> str | None:
        """For the primary "Aktivní cívka" mirror (suffix "id"), the colour
        swatch/photo Spoolman generated for the active spool - scanned the
        same robust way spool_entity_picture() always has, rather than
        trusting whichever single source entity this mirror happens to be
        pointed at (material/vendor/colour aren't their own suffixed
        entities - see spool_meta_attrs() in spoolman_registry.py - and
        picture support is no different)."""
        if self._suffix != "id":
            return None
        spool_id = self.coordinator.data.get("spool_id") if self.coordinator.data else None
        if spool_id is None:
            return None
        device = find_spool_device(self._dev_reg, spool_id)
        if device is None:
            return None
        return spool_entity_picture(self._hass, device.id)

    def _resync(self) -> None:
        """Point this mirror at the right source entity for the active spool."""
        spool_id = self.coordinator.data.get("spool_id") if self.coordinator.data else None
        new_source_entity_id: str | None = None
        if spool_id is not None:
            device = find_spool_device(self._dev_reg, spool_id)
            if device is not None:
                for source in spool_source_entities(self._ent_reg, device.id, spool_id):
                    if source.suffix == self._suffix:
                        new_source_entity_id = source.entity_id
                        break

        if new_source_entity_id != self._source_entity_id:
            if self._unsub_state is not None:
                self._unsub_state()
                self._unsub_state = None
            self._source_entity_id = new_source_entity_id
            if new_source_entity_id and self.hass is not None:
                self._unsub_state = async_track_state_change_event(
                    self.hass, [new_source_entity_id], self._handle_source_event
                )

        state = (
            self._hass.states.get(new_source_entity_id)
            if new_source_entity_id
            else None
        )
        self._apply_source_state(state, self._id_picture_override())

    def _apply_source_state(
        self, state: State | None, picture_override: str | None = None
    ) -> None:
        if state is None or state.state in ("unknown", "unavailable"):
            self._attr_native_value = None
            self._attr_native_unit_of_measurement = None
            self._attr_device_class = None
            self._attr_icon = None
            self._attr_entity_picture = None
        else:
            self._attr_native_value = state.state
            self._attr_native_unit_of_measurement = state.attributes.get(
                "unit_of_measurement"
            )
            self._attr_device_class = state.attributes.get("device_class")
            self._attr_icon = state.attributes.get("icon")
            self._attr_entity_picture = state.attributes.get("entity_picture")
        # Same colour swatch/photo as the Spoolman integration's own entity
        # for the active spool, regardless of what the line above found.
        if picture_override:
            self._attr_entity_picture = picture_override
        if self.hass is not None:
            self.async_write_ha_state()


class WebhookUrlSensor(SensorEntity):
    """Diagnostic sensor showing the hub's QR webhook base URL."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:qrcode-scan"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_webhook_url"
        self._attr_name = "QR webhook URL"
        self.entity_id = "sensor.spoolman_qr_webhook_url"
        self._attr_device_info = DeviceInfo(
            identifiers={printer_device_identifier(entry.entry_id)},
            name=entry.title,
            manufacturer="Spoolman Active Spool (Moonraker)",
            model="QR odkazy",
        )

    @property
    def native_value(self) -> str:
        url = webhook_full_url(self._hass, self._entry)
        if url is None:
            return "Nedostupné - nastav Home Assistant URL nebo vyplň base_url"
        return url
