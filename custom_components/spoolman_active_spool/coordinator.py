"""Coordinator that polls one printer's Moonraker for its active spool_id.

This is the *only* thing polled by this integration. Everything else
(spool name, material, weight, ...) is read straight from entities that
Disane87/spoolman-homeassistant already maintains in Home Assistant - see
spoolman_registry.py.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_API_KEY,
    CONF_MOONRAKER_URL,
    CONF_POLL_INTERVAL,
    CONF_VERIFY_SSL,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)
from .moonraker import (
    async_get_afc_lane_spool_ids,
    async_get_spoolman_status,
    async_list_afc_lanes,
)

_LOGGER = logging.getLogger(__name__)


class ActiveSpoolCoordinator(DataUpdateCoordinator[dict]):
    """Polls GET /server/spoolman/status for one printer."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        poll_interval = entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} ({entry.title})",
            update_interval=timedelta(seconds=poll_interval),
        )
        self.entry = entry
        self.moonraker_url = entry.data[CONF_MOONRAKER_URL].rstrip("/")
        self.verify_ssl = entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
        self.api_key = entry.data.get(CONF_API_KEY) or None
        # Detected once (first successful poll) and then cached - AFC lanes
        # don't come and go at runtime, and re-listing every printer object
        # on every poll would be wasted work for the overwhelming majority
        # of printers, which have none. Empty list = "no lanes", exactly
        # like a plain single-extruder printer; nothing else in this
        # integration behaves differently until this is non-empty.
        self.lanes: list[str] = []
        self._lanes_detected = False
        _LOGGER.debug(
            "Spoolman Active Spool (%s): polling every %s s",
            entry.title,
            poll_interval,
        )

    async def _async_update_data(self) -> dict:
        if not self._lanes_detected:
            self.lanes = await async_list_afc_lanes(
                self.hass, self.moonraker_url, self.verify_ssl, self.api_key
            )
            self._lanes_detected = True
            if self.lanes:
                _LOGGER.info(
                    "Spoolman Active Spool (%s): detected AFC lanes: %s",
                    self.entry.title,
                    ", ".join(self.lanes),
                )

        try:
            status = await async_get_spoolman_status(
                self.hass, self.moonraker_url, self.verify_ssl, self.api_key
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            # Keep the last known spool_id instead of flipping every entity
            # to unavailable on a transient Moonraker hiccup.
            if self.data is not None:
                _LOGGER.debug(
                    "Spoolman Active Spool (%s): status request failed (%s), "
                    "keeping last known data",
                    self.entry.title,
                    err,
                )
                return self.data
            raise UpdateFailed(str(err)) from err

        lane_spool_ids: dict[str, int | None] = {}
        if self.lanes:
            try:
                lane_spool_ids = await async_get_afc_lane_spool_ids(
                    self.hass, self.moonraker_url, self.verify_ssl, self.lanes, self.api_key
                )
            except (aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.debug(
                    "Spoolman Active Spool (%s): lane status request failed (%s), "
                    "keeping last known lane data",
                    self.entry.title,
                    err,
                )
                lane_spool_ids = (
                    self.data.get("lane_spool_ids", {}) if self.data else {}
                )

        _LOGGER.debug(
            "Spoolman Active Spool (%s): polled status, spool_id=%s, lanes=%s",
            self.entry.title,
            status.get("spool_id"),
            lane_spool_ids,
        )
        return {
            "spool_id": status.get("spool_id"),
            "spoolman_connected": status.get("spoolman_connected"),
            "lane_spool_ids": lane_spool_ids,
        }
