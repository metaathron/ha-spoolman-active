"""Image platform for Spoolman Active Spool (Moonraker) - QR codes.

Only set up by the webhook hub entry. For every existing (and later added)
Spoolman spool device, creates a QR-code image entity encoding the URL
that sets that spool active via the hub's webhook. Also creates one
spool-independent QR code that opens the "remove active spool" picker
(same URL, without a spool_id). The QR content never changes for a given
spool + webhook_id + base_url, so it is rendered once at entity creation
and cached - no polling.
"""

from __future__ import annotations

import io
import logging

import qrcode
import qrcode.image.svg

from homeassistant.components.image import Image, ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntry, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .spoolman_registry import printer_device_identifier, spool_id_from_device
from .webhook_hub import spool_qr_url, webhook_full_url

_LOGGER = logging.getLogger(__name__)

CONTENT_TYPE = "image/svg+xml"


def _generate_qr_svg(url: str) -> bytes:
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathFillImage)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    dev_reg = dr.async_get(hass)
    known_device_ids: set[str] = set()
    warned_no_url = False

    def _build(device: DeviceEntry) -> SpoolQrImage | None:
        nonlocal warned_no_url
        spool_id = spool_id_from_device(device)
        if spool_id is None:
            return None
        url = spool_qr_url(hass, entry, spool_id)
        if url is None:
            if not warned_no_url:
                warned_no_url = True
                _LOGGER.warning(
                    "Spoolman Active Spool: no base URL available for QR codes - "
                    "set one manually on the webhook hub, or configure Home "
                    "Assistant's URL under Settings > System > Network"
                )
            return None
        known_device_ids.add(device.id)
        return SpoolQrImage(hass, entry, device, spool_id, url)

    initial = [
        entity
        for device in dev_reg.devices.values()
        if (entity := _build(device)) is not None
    ]

    remove_url = webhook_full_url(hass, entry)
    if remove_url is not None:
        initial.append(RemoveActiveSpoolQrImage(hass, entry, remove_url))
    elif not warned_no_url:
        warned_no_url = True
        _LOGGER.warning(
            "Spoolman Active Spool: no base URL available for QR codes - "
            "set one manually on the webhook hub, or configure Home "
            "Assistant's URL under Settings > System > Network"
        )

    if initial:
        async_add_entities(initial)

    @callback
    def _handle_device_registry_update(event: Event) -> None:
        if event.data.get("action") != "create":
            return
        device = dev_reg.async_get(event.data["device_id"])
        if device is None:
            return
        entity = _build(device)
        if entity is not None:
            async_add_entities([entity])

    entry.async_on_unload(
        hass.bus.async_listen(
            dr.EVENT_DEVICE_REGISTRY_UPDATED, _handle_device_registry_update
        )
    )


class SpoolQrImage(ImageEntity):
    """A QR code linking to "set this spool active" for one physical spool."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:qrcode"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device: DeviceEntry,
        spool_id: int,
        url: str,
    ) -> None:
        super().__init__(hass)
        self._attr_unique_id = f"{entry.entry_id}_spool_{spool_id}_qr"
        self._attr_name = "QR kód"
        self.entity_id = f"image.spoolman_spool_{spool_id}_qr_code"
        self._attr_device_info = DeviceInfo(identifiers=device.identifiers)
        self._attr_content_type = CONTENT_TYPE
        self._attr_image_last_updated = dt_util.utcnow()
        self._cached_image = Image(
            content_type=CONTENT_TYPE, content=_generate_qr_svg(url)
        )


class RemoveActiveSpoolQrImage(ImageEntity):
    """A QR code linking to the "remove active spool" picker - not tied to
    any one spool, since it lets you pick which printer to clear."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:qrcode-remove"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, url: str) -> None:
        super().__init__(hass)
        self._attr_unique_id = f"{entry.entry_id}_remove_active_spool_qr"
        self._attr_name = "QR kód pro odebrání aktivní cívky"
        self.entity_id = "image.spoolman_qr_remove_active_spool"
        self._attr_device_info = DeviceInfo(
            identifiers={printer_device_identifier(entry.entry_id)},
            name=entry.title,
            manufacturer="Spoolman Active Spool (Moonraker)",
            model="QR odkazy",
        )
        self._attr_content_type = CONTENT_TYPE
        self._attr_image_last_updated = dt_util.utcnow()
        self._cached_image = Image(
            content_type=CONTENT_TYPE, content=_generate_qr_svg(url)
        )
