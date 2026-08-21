"""Small helpers for talking to one printer's Moonraker instance.

Kept in one place so button.py, select.py and coordinator.py all send
requests the same way (timeout, SSL handling, response unwrapping).
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import AFC_LANE_OBJECT_PREFIX, ONLINE_CHECK_TIMEOUT, REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)


def _ssl_kwarg(verify_ssl: bool) -> dict[str, Any]:
    return {} if verify_ssl else {"ssl": False}


def _headers(api_key: str | None) -> dict[str, str]:
    """X-Api-Key header - only needed if Moonraker has "force_logins" (or
    trusted-client auth) disabled and requires a key on every request. No
    key configured -> no header, identical to before this existed."""
    return {"X-Api-Key": api_key} if api_key else {}


def _unwrap(payload: Any) -> dict[str, Any]:
    """Moonraker wraps HTTP responses as {"result": {...}}."""
    if isinstance(payload, dict) and "result" in payload:
        return payload["result"]
    return payload


async def async_get_spoolman_status(
    hass: HomeAssistant, moonraker_url: str, verify_ssl: bool, api_key: str | None = None
) -> dict[str, Any]:
    """GET /server/spoolman/status - spool_id, spoolman_connected, pending_reports."""
    session = async_get_clientsession(hass)
    url = f"{moonraker_url.rstrip('/')}/server/spoolman/status"
    async with session.get(
        url,
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        headers=_headers(api_key),
        **_ssl_kwarg(verify_ssl),
    ) as response:
        response.raise_for_status()
        return _unwrap(await response.json())


async def async_check_online(
    hass: HomeAssistant, moonraker_url: str, verify_ssl: bool, api_key: str | None = None
) -> bool:
    """Best-effort liveness check for the webhook picker page's "offline"
    hint - hits Moonraker's own /server/info with a short timeout. Any
    connection error, timeout or non-2xx response counts as offline; this
    never raises, so a dead printer never breaks page rendering."""
    session = async_get_clientsession(hass)
    url = f"{moonraker_url.rstrip('/')}/server/info"
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=ONLINE_CHECK_TIMEOUT),
            headers=_headers(api_key),
            **_ssl_kwarg(verify_ssl),
        ) as response:
            response.raise_for_status()
            return True
    except (aiohttp.ClientError, TimeoutError, OSError):
        return False


async def async_list_afc_lanes(
    hass: HomeAssistant, moonraker_url: str, verify_ssl: bool, api_key: str | None = None
) -> list[str]:
    """Auto-detect AFC lanes (e.g. a 4-extruder Snapmaker U1's E0-E3, via the
    AFC-Lite stub or the full AFC-Klipper-Add-On) by listing Klipper's
    printer objects and keeping the ones named "AFC_lane <name>". A printer
    with no such objects (a single extruder, no AFC/AFC-Lite - the common
    case) simply gets an empty list back; every caller treats that exactly
    like "no lanes", so nothing changes for those printers. Never raises -
    a failed/timed-out check just means "no lanes detected yet", retried on
    the next poll.
    """
    session = async_get_clientsession(hass)
    url = f"{moonraker_url.rstrip('/')}/printer/objects/list"
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            headers=_headers(api_key),
            **_ssl_kwarg(verify_ssl),
        ) as response:
            response.raise_for_status()
            payload = _unwrap(await response.json())
    except (aiohttp.ClientError, TimeoutError, OSError) as err:
        _LOGGER.debug(
            "Spoolman Active Spool: /printer/objects/list request to %s failed (%s) - "
            "treating as \"no AFC lanes detected\" for now",
            moonraker_url,
            err,
        )
        return []

    objects = payload.get("objects", []) if isinstance(payload, dict) else []
    lanes = sorted(
        obj[len(AFC_LANE_OBJECT_PREFIX):]
        for obj in objects
        if isinstance(obj, str) and obj.startswith(AFC_LANE_OBJECT_PREFIX)
    )
    afc_related = [obj for obj in objects if isinstance(obj, str) and "afc" in obj.lower()]
    _LOGGER.debug(
        "Spoolman Active Spool: %s - %d printer object(s) total, AFC-related: %s, "
        "matched as lanes (prefix %r): %s",
        moonraker_url,
        len(objects),
        afc_related,
        AFC_LANE_OBJECT_PREFIX,
        lanes,
    )
    return lanes


async def async_get_afc_lane_spool_ids(
    hass: HomeAssistant,
    moonraker_url: str,
    verify_ssl: bool,
    lanes: list[str],
    api_key: str | None = None,
) -> dict[str, int | None]:
    """GET /printer/objects/query for every "AFC_lane <name>" object at
    once - {lane: spool_id}, spool_id is None when the lane has nothing
    assigned. Raises on request failure, same as async_get_spoolman_status,
    so the coordinator can fall back to its last known values."""
    if not lanes:
        return {}
    session = async_get_clientsession(hass)
    query = "&".join(
        f"{AFC_LANE_OBJECT_PREFIX}{lane}".replace(" ", "%20") for lane in lanes
    )
    url = f"{moonraker_url.rstrip('/')}/printer/objects/query?{query}"
    async with session.get(
        url,
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        headers=_headers(api_key),
        **_ssl_kwarg(verify_ssl),
    ) as response:
        response.raise_for_status()
        payload = _unwrap(await response.json())

    status = payload.get("status", {}) if isinstance(payload, dict) else {}
    result: dict[str, int | None] = {}
    for lane in lanes:
        obj = status.get(f"{AFC_LANE_OBJECT_PREFIX}{lane}", {})
        raw_spool_id = obj.get("spool_id") if isinstance(obj, dict) else None
        try:
            spool_id = int(raw_spool_id) if raw_spool_id else None
        except (TypeError, ValueError):
            spool_id = None
        result[lane] = spool_id if spool_id else None
    return result


async def async_set_lane_spool(
    hass: HomeAssistant,
    moonraker_url: str,
    verify_ssl: bool,
    lane: str,
    spool_id: int | None,
    api_key: str | None = None,
) -> None:
    """SET_SPOOL_ID LANE=<lane> SPOOL_ID=<id> via Moonraker's generic gcode
    endpoint - the AFC-Lite/SpoolLink gcode macro Snapmaker's Extended
    Firmware provides for per-extruder spool assignment. There is no
    per-tool equivalent of /server/spoolman/spool_id in stock Moonraker
    (yet), so this is the only way to target one lane specifically.
    SPOOL_ID=0 clears the lane's assignment, same convention as the macro
    itself.
    """
    session = async_get_clientsession(hass)
    url = f"{moonraker_url.rstrip('/')}/printer/gcode/script"
    script = f"SET_SPOOL_ID LANE={lane} SPOOL_ID={spool_id if spool_id else 0}"
    async with session.post(
        url,
        json={"script": script},
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        headers=_headers(api_key),
        **_ssl_kwarg(verify_ssl),
    ) as response:
        response.raise_for_status()


async def async_set_active_spool(
    hass: HomeAssistant,
    moonraker_url: str,
    verify_ssl: bool,
    spool_id: int | None,
    api_key: str | None = None,
) -> None:
    """POST /server/spoolman/spool_id - spool_id=None clears the active spool.

    Moonraker parses the body with ``get_int("spool_id", None)``: sending an
    explicit ``{"spool_id": null}`` makes it try to convert None to int and
    fail with a 400. To clear the active spool the key must be omitted
    entirely so Moonraker falls back to its own default.
    """
    session = async_get_clientsession(hass)
    url = f"{moonraker_url.rstrip('/')}/server/spoolman/spool_id"
    payload = {"spool_id": spool_id} if spool_id is not None else {}
    async with session.post(
        url,
        json=payload,
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        headers=_headers(api_key),
        **_ssl_kwarg(verify_ssl),
    ) as response:
        response.raise_for_status()
