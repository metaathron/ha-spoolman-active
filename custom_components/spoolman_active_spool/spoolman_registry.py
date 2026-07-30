"""Helpers for finding Spoolman (Disane87/spoolman-homeassistant) spool
devices and their entities directly in Home Assistant's own registries -
device_registry / entity_registry / state machine. Nothing here ever calls
the Spoolman REST API; all data already lives in HA because the Spoolman
integration's own coordinator keeps it up to date.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.util import slugify

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_PRINTER, SPOOLMAN_DOMAIN


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
    """Read one *dedicated* "_spool_<id>_<suffix>" sensor's own state.

    Only useful for fields Spoolman gives their own sensor entity (e.g.
    "weight", "id"). material/vendor/name/color are NOT among them - they
    are "filament_*" attributes on the spool's main sensor instead (see
    spool_meta_attrs() below), so its own unique_id has no trailing suffix
    and is invisible to the "_{suffix}" match here.
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


# The "filament_*" attributes live on the spool's main sensor entity
# (sensor.spoolman_spool_<id>), alongside whatever *other* dedicated sensor
# entities exist for that same device (e.g. "..._weight"). Scanning every
# sensor entity of the device and reading its attributes - rather than
# matching a specific entity by suffix - finds them regardless of which
# entity happens to carry them.
SPOOL_META_ATTR_KEYS = (
    "filament_material",
    "filament_vendor_name",
    "filament_name",
    "filament_color_hex",
    "filament_multi_color_hexes",
    "filament_multi_color_direction",
)


def spool_meta_attrs(hass: HomeAssistant, device_id: str) -> dict[str, str]:
    """First non-empty value per SPOOL_META_ATTR_KEYS key, scanning every
    sensor entity of the device."""
    ent_reg = er.async_get(hass)
    found: dict[str, str] = {}
    for entry in er.async_entries_for_device(
        ent_reg, device_id, include_disabled_entities=False
    ):
        if entry.platform != SPOOLMAN_DOMAIN or entry.domain != "sensor":
            continue
        state = hass.states.get(entry.entity_id)
        if state is None:
            continue
        for key in SPOOL_META_ATTR_KEYS:
            if key not in found:
                value = state.attributes.get(key)
                if value not in (None, ""):
                    found[key] = value
        if len(found) == len(SPOOL_META_ATTR_KEYS):
            break
    return found


def spool_entity_picture(hass: HomeAssistant, device_id: str) -> str | None:
    """Return the color-swatch image path Spoolman already generated for a
    spool, if any (its "spool" or "filament_color_hex" sensor sets one).
    """
    ent_reg = er.async_get(hass)
    for entry in er.async_entries_for_device(
        ent_reg, device_id, include_disabled_entities=False
    ):
        if entry.platform != SPOOLMAN_DOMAIN or entry.domain != "sensor":
            continue
        state = hass.states.get(entry.entity_id)
        if state is not None and state.attributes.get("entity_picture"):
            return state.attributes["entity_picture"]
    return None


def spool_label(hass: HomeAssistant, device: DeviceEntry, spool_id: int) -> str:
    """Human-readable "material - vendor - name" label for a spool device."""
    meta = spool_meta_attrs(hass, device.id)
    material = meta.get("filament_material") or "?"
    vendor = meta.get("filament_vendor_name") or "?"
    name = meta.get("filament_name") or f"Cívka {spool_id}"
    return f"{material} - {vendor} - {name}"


def printer_entries(hass: HomeAssistant) -> list:
    """Every loaded printer (non-hub) config entry of this integration."""
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_PRINTER) == ENTRY_TYPE_PRINTER
        and entry.state is ConfigEntryState.LOADED
    ]


def printer_device_identifier(entry_id: str) -> tuple[str, str]:
    """Stable device identifier for the device owned by one config entry
    (a printer's device, or the webhook hub's device).
    """
    return (DOMAIN, entry_id)
