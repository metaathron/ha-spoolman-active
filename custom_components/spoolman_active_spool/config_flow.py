"""Config flow for the Spoolman Active Spool (Moonraker) integration.

One config entry represents one printer / one Moonraker instance. Add the
integration again for each additional printer.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_MOONRAKER_URL,
    CONF_NAME,
    CONF_VERIFY_SSL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    REQUEST_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


def _normalize_url(raw: str) -> str:
    """Strip a trailing slash and surrounding whitespace."""
    return raw.strip().rstrip("/")


def _connection_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "")): str,
            vol.Required(
                CONF_MOONRAKER_URL, default=defaults.get(CONF_MOONRAKER_URL, "")
            ): str,
            vol.Required(
                CONF_VERIFY_SSL,
                default=defaults.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
            ): bool,
        }
    )


async def _validate_moonraker(hass, url: str, verify_ssl: bool) -> None:
    """Ping Moonraker's spoolman status endpoint. Raises on failure."""
    session = async_get_clientsession(hass)
    check_url = f"{url}/server/spoolman/status"
    ssl_kwarg: dict[str, Any] = {} if verify_ssl else {"ssl": False}
    async with session.get(
        check_url,
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        **ssl_kwarg,
    ) as response:
        response.raise_for_status()


class SpoolmanActiveSpoolConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle initial setup and reconfigure for one printer."""

    VERSION = 1

    async def _async_try_connect(self, data: dict[str, Any]) -> dict[str, str]:
        try:
            await _validate_moonraker(
                self.hass, data[CONF_MOONRAKER_URL], data[CONF_VERIFY_SSL]
            )
        except aiohttp.ClientError:
            return {"base": "cannot_connect"}
        except TimeoutError:
            return {"base": "cannot_connect"}
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error validating Moonraker connection")
            return {"base": "unknown"}
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input[CONF_NAME] = user_input[CONF_NAME].strip()
            user_input[CONF_MOONRAKER_URL] = _normalize_url(
                user_input[CONF_MOONRAKER_URL]
            )
            errors = await self._async_try_connect(user_input)
            if not errors:
                await self.async_set_unique_id(
                    user_input[CONF_MOONRAKER_URL].lower()
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_MOONRAKER_URL: user_input[CONF_MOONRAKER_URL],
                        CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL],
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=_connection_schema(), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the printer's name, Moonraker URL, or SSL verification."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            user_input[CONF_NAME] = user_input[CONF_NAME].strip()
            user_input[CONF_MOONRAKER_URL] = _normalize_url(
                user_input[CONF_MOONRAKER_URL]
            )
            errors = await self._async_try_connect(user_input)
            if not errors:
                await self.async_set_unique_id(
                    user_input[CONF_MOONRAKER_URL].lower()
                )
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    title=user_input[CONF_NAME],
                    data={
                        CONF_MOONRAKER_URL: user_input[CONF_MOONRAKER_URL],
                        CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL],
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(
                {
                    CONF_NAME: reconfigure_entry.title,
                    CONF_MOONRAKER_URL: reconfigure_entry.data[CONF_MOONRAKER_URL],
                    CONF_VERIFY_SSL: reconfigure_entry.data.get(
                        CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL
                    ),
                }
            ),
            errors=errors,
        )
