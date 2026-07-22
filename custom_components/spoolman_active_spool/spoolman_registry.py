"""Helpers for finding Spoolman (Disane87/spoolman-homeassistant) spool
devices and their entities directly in Home Assistant's own registries -
device_registry / entity_registry / state machine. Nothing here ever calls
the Spoolman REST API; all data already lives in HA because the Spoolman
integration's own coordinator keeps it up to date.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.util import slugify

from .const import DOMAIN, SPOOLMAN_DOMAIN


def printer_object_id(printer_name: str) -> str:
    """entity_id-friendly slug for a printer name."""
    return slugify(printer_name)


def spool_id_from_device(device: DeviceEntry) -> int | None:
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


def find_spool_device(
    device_reg: dr.DeviceRegistry, spool_id: int
) -> DeviceEntry | None:
    """Find the Spoolman device for a given spool id, if it still exists."""
    for device in device_reg.devices.values():
        if spool_id_from_device(device) == spool_id:
            return device
    return None


def iter_spool_devices(device_reg: dr.DeviceRegistry):
    """Yield (spool_id, device) for every Spoolman spool device known to HA."""
    for device in device_reg.devices.values():
        spool_id = spool_id_from_device(device)
        if spool_id is not None:
            yield spool_id, device


@dataclass
class SpoolSourceEntity:
    """One entity that belongs to a Spoolman spool device."""

    entity_id: str
    unique_id: str
    suffix: str  # the part after "..._spool_<id>_", e.g. "weight", "id"


def spool_source_entities(
    ent_reg: er.EntityRegistry, device_id: str, spool_id: int
) -> list[SpoolSourceEntity]:
    """List every sensor entity Spoolman created for one spool device."""
    marker = f"_spool_{spool_id}_"
    results: list[SpoolSourceEntity] = []
    for entry in er.async_entries_for_device(
        ent_reg, device_id, include_disabled_entities=False
    ):
        if entry.platform != SPOOLMAN_DOMAIN or entry.domain != "sensor":
            continue
        if marker not in entry.unique_id:
            continue
        suffix = entry.unique_id.split(marker, 1)[1]
        if not suffix:
            continue
        results.append(
            SpoolSourceEntity(
                entity_id=entry.entity_id, unique_id=entry.unique_id, suffix=suffix
            )
        )
    return results


def spool_state_value(hass: HomeAssistant, device_id: str, suffix: str) -> str | None:
    """Read one attribute (by suffix) of a spool device straight from HA state.

    Used for building the dropdown label (material / vendor / name) without
    ever calling Spoolman's API.
    """
    ent_reg = er.async_get(hass)
    for entry in er.async_entries_for_device(
        ent_reg, device_id, include_disabled_entities=False
    ):
        if entry.platform != SPOOLMAN_DOMAIN or entry.domain != "sensor":
            continue
        if not entry.unique_id.endswith(f"_{suffix}"):
            continue
        state = hass.states.get(entry.entity_id)
        if state is not None and state.state not in ("unknown", "unavailable"):
            return state.state
    return None


def printer_device_identifier(entry_id: str) -> tuple[str, str]:
    """Stable device identifier for the printer device of one config entry."""
    return (DOMAIN, entry_id)
