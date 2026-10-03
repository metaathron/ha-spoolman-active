"""Small helpers for talking to one printer's Moonraker instance.

Kept in one place so button.py, select.py and coordinator.py all send
requests the same way (timeout, SSL handling, response unwrapping).
"""

from __future__ import annotations

import logging
import re
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


_EXTRUDER_OBJECT_RE = re.compile(r"^extruder(\d*)$")


async def async_detect_tool_count(
    hass: HomeAssistant, moonraker_url: str, verify_ssl: bool, api_key: str | None = None
) -> int:
    """How many real toolheads this printer has, and whether it exposes
    Snapmaker's own "print_task_config" object - the only place this
    integration has found per-tool spool data (see async_get_tool_status
    below). Counted from Klipper's standard
    "extruder", "extruder1", "extruder2", ... printer objects, which scale
    with real hardware - unlike print_task_config's own arrays, which seem
    to be a fixed size (32) regardless of how many toolheads actually
    exist. Returns 1 ("just one toolhead, nothing special to do") unless
    BOTH more than one extruder object AND print_task_config are present -
    so a single-extruder printer, and a multi-extruder printer that
    doesn't expose this Snapmaker-specific object at all, behave
    identically to before this existed. Never raises - a failed/timed-out
    check just means "assume one toolhead for now", retried next poll.
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
            "assuming a single toolhead for now",
            moonraker_url,
            err,
        )
        return 1

    objects = payload.get("objects", []) if isinstance(payload, dict) else []
    extruder_count = sum(
        1 for obj in objects if isinstance(obj, str) and _EXTRUDER_OBJECT_RE.match(obj)
    )
    has_print_task_config = "print_task_config" in objects
    _LOGGER.debug(
        "Spoolman Active Spool: %s - %d extruder object(s), print_task_config present: %s",
        moonraker_url,
        extruder_count,
        has_print_task_config,
    )
    if extruder_count > 1 and has_print_task_config:
        return extruder_count
    return 1


_FEED_EXTRUDER_RE = re.compile(r"^extruder(\d*)$")


async def async_get_tool_status(
    hass: HomeAssistant,
    moonraker_url: str,
    verify_ssl: bool,
    tool_count: int,
    api_key: str | None = None,
) -> dict[int, dict[str, Any]]:
    """One GET /printer/objects/query covering everything this integration
    exposes per toolhead, in a single request:

    - print_task_config.filament_spool_id - which Spoolman spool is
      loaded in each toolhead. That array appears to be a fixed size well
      beyond any real toolhead count, so it's trimmed here to tool_count
      (the printer's *actual* number of extruders, from
      async_detect_tool_count above). 0 means "nothing loaded", same
      convention as everywhere else in this integration.
    - "filament_feed left"/"filament_feed right" - whether filament is
      physically detected in that toolhead right now (filament_detected,
      already a plain bool) and the raw state machine value
      (channel_state, e.g. "load_finish"/"wait_insert"). Both objects key
      their toolheads as "extruder0".."extruder3" regardless of which
      physical side they're on, so they're merged into one tool-indexed
      dict here.

    Raises on request failure, same as the other query calls, so the
    coordinator can fall back to its last known values.
    """
    if tool_count <= 1:
        return {}

    result: dict[int, dict[str, Any]] = {
        tool: {"spool_id": None, "filament_detected": None, "channel_state": None}
        for tool in range(tool_count)
    }

    session = async_get_clientsession(hass)
    url = (
        f"{moonraker_url.rstrip('/')}/printer/objects/query"
        "?print_task_config&filament_feed%20left&filament_feed%20right"
    )
    async with session.get(
        url,
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        headers=_headers(api_key),
        **_ssl_kwarg(verify_ssl),
    ) as response:
        response.raise_for_status()
        payload = _unwrap(await response.json())

    status = payload.get("status", {}) if isinstance(payload, dict) else {}

    config = status.get("print_task_config", {})
    raw_spool_ids = config.get("filament_spool_id", []) if isinstance(config, dict) else []
    for tool in range(tool_count):
        raw = raw_spool_ids[tool] if tool < len(raw_spool_ids) else None
        try:
            spool_id = int(raw) if raw else None
        except (TypeError, ValueError):
            spool_id = None
        result[tool]["spool_id"] = spool_id if spool_id else None

    for feed_key in ("filament_feed left", "filament_feed right"):
        feed = status.get(feed_key, {})
        if not isinstance(feed, dict):
            continue
        for extruder_key, info in feed.items():
            if not isinstance(info, dict):
                continue
            match = _FEED_EXTRUDER_RE.match(extruder_key)
            if match is None:
                continue
            tool = int(match.group(1) or 0)
            if tool not in result:
                continue
            result[tool]["filament_detected"] = info.get("filament_detected")
            result[tool]["channel_state"] = info.get("channel_state")

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
