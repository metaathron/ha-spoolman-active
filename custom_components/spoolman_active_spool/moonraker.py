"""Small helpers for talking to one printer's Moonraker instance.

Kept in one place so button.py, select.py and coordinator.py all send
requests the same way (timeout, SSL handling, response unwrapping).
"""

from __future__ import annotations

from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import ONLINE_CHECK_TIMEOUT, REQUEST_TIMEOUT


def _ssl_kwarg(verify_ssl: bool) -> dict[str, Any]:
    return {} if verify_ssl else {"ssl": False}


def _unwrap(payload: Any) -> dict[str, Any]:
    """Moonraker wraps HTTP responses as {"result": {...}}."""
    if isinstance(payload, dict) and "result" in payload:
        return payload["result"]
    return payload


async def async_get_spoolman_status(
    hass: HomeAssistant, moonraker_url: str, verify_ssl: bool
) -> dict[str, Any]:
    """GET /server/spoolman/status - spool_id, spoolman_connected, pending_reports."""
    session = async_get_clientsession(hass)
    url = f"{moonraker_url.rstrip('/')}/server/spoolman/status"
    async with session.get(
        url,
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        **_ssl_kwarg(verify_ssl),
    ) as response:
        response.raise_for_status()
        return _unwrap(await response.json())


async def async_check_online(
    hass: HomeAssistant, moonraker_url: str, verify_ssl: bool
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
            **_ssl_kwarg(verify_ssl),
        ) as response:
            response.raise_for_status()
            return True
    except (aiohttp.ClientError, TimeoutError, OSError):
        return False


async def async_set_active_spool(
    hass: HomeAssistant,
    moonraker_url: str,
    verify_ssl: bool,
    spool_id: int | None,
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
        **_ssl_kwarg(verify_ssl),
    ) as response:
        response.raise_for_status()
