"""Binary sensor platform for Spoolman Active Spool (Moonraker).

Only ever creates entities on multi-toolhead printers with Snapmaker's own
"filament_feed left"/"filament_feed right" objects (see
async_get_tool_status() in moonraker.py) - one "Zaveden filament" per
toolhead, read-only, same as the per-tool spool sensor in sensor.py.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ActiveSpoolCoordinator
from .spoolman_registry import (
    printer_device_identifier,
    printer_object_id,
    printer_tool_device_identifier,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ActiveSpoolCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    if coordinator.tool_count > 1:
        async_add_entities(
            ToolFilamentDetectedSensor(hass, entry, coordinator, tool)
            for tool in range(coordinator.tool_count)
        )


class ToolFilamentDetectedSensor(
    CoordinatorEntity[ActiveSpoolCoordinator], BinarySensorEntity
):
    """Whether filament is actually loaded in one toolhead's nozzle right
    now - Snapmaker's own "filament_feed left"/"filament_feed right"
    channel_state == "load_finish" (see async_get_tool_status() in
    moonraker.py). filament_detected alone isn't enough: it already goes
    true as soon as filament reaches the feeder, before it's actually
    fed through to the toolhead - channel_state is what distinguishes
    "loaded in the feeder" from "loaded in the head". The raw
    filament_detected value is kept as an attribute for anyone who wants
    it.

    Lives on the same "<printer> - Tool <n>" device as the matching spool
    sensors in sensor.py (MirrorSensor, tool=N) - see that module's
    docstring for why that's a separate device from the main printer
    device.
    """

    _attr_has_entity_name = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: ActiveSpoolCoordinator,
        tool: int,
    ) -> None:
        super().__init__(coordinator)
        self._tool = tool

        printer_slug = printer_object_id(entry.title)
        self._attr_unique_id = f"{entry.entry_id}_tool_{tool}_filament_loaded"
        self._attr_name = f"Zaveden filament (Tool {tool})"
        self.entity_id = (
            f"binary_sensor.spoolman_active_{printer_slug}_tool_{tool}_filament_loaded"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={printer_tool_device_identifier(entry.entry_id, tool)},
            name=f"{entry.title} - Tool {tool}",
            manufacturer="Spoolman Active Spool (Moonraker)",
            model="Tool",
            via_device=printer_device_identifier(entry.entry_id),
        )
        self._refresh()

    @property
    def icon(self) -> str:
        return "mdi:printer-3d-nozzle" if self._attr_is_on else "mdi:printer-3d-nozzle-off"

    @callback
    def _handle_coordinator_update(self) -> None:
        self._refresh()
        self.async_write_ha_state()

    def _refresh(self) -> None:
        tool_info = (
            self.coordinator.data.get("tool_status", {}).get(self._tool, {})
            if self.coordinator.data
            else {}
        )
        channel_state = tool_info.get("channel_state")
        self._attr_is_on = (
            channel_state == "load_finish" if channel_state is not None else None
        )
        self._attr_extra_state_attributes = {
            "channel_state": channel_state,
            "filament_detected": tool_info.get("filament_detected"),
        }
