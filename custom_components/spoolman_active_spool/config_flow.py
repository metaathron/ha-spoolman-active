"""Config flow for the Spoolman Active Spool (Moonraker) integration.

Two kinds of entry, chosen from a menu:

- "printer": one config entry per printer / Moonraker instance. Add the
  flow again for each additional printer.
- "webhook": the QR-code webhook hub. Single instance - once it exists,
  the menu is skipped and "user" goes straight to the printer step.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig

from .const import (
    CONF_BASE_URL,
    CONF_ENTRY_TYPE,
    CONF_LOCAL_ONLY,
    CONF_MOONRAKER_URL,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    CONF_VERIFY_SSL,
    CONF_WEBHOOK_ID,
    DEFAULT_LOCAL_ONLY,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    ENTRY_TYPE_HUB,
    ENTRY_TYPE_PRINTER,
    MIN_POLL_INTERVAL,
    REQUEST_TIMEOUT,
)
from .webhook_hub import resolve_base_url_value

_LOGGER = logging.getLogger(__name__)

WEBHOOK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


# ---------------------------------------------------------------- printer --


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
            vol.Required(
                CONF_POLL_INTERVAL,
                default=defaults.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
            ): NumberSelector(
                NumberSelectorConfig(min=MIN_POLL_INTERVAL, max=3600, step=1, unit_of_measurement="s")
            ),
        }
    )


async def _validate_moonraker(hass: HomeAssistant, url: str, verify_ssl: bool) -> None:
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


# ----------------------------------------------------------------- webhook --


async def _noop_webhook_handler(hass, webhook_id, request):  # noqa: ANN001
    return None


async def _validate_webhook_id(
    hass: HomeAssistant, webhook_id: str, *, unchanged: bool
) -> str | None:
    """Return an error code, or None if the webhook_id is usable."""
    if not WEBHOOK_ID_RE.match(webhook_id):
        return "invalid_webhook_id"
    if unchanged:
        return None
    try:
        webhook.async_register(
            hass, DOMAIN, "validation", webhook_id, _noop_webhook_handler
        )
    except ValueError:
        return "webhook_id_taken"
    webhook.async_unregister(hass, webhook_id)
    return None


def _webhook_schema(hass: HomeAssistant, defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    local_only = defaults.get(CONF_LOCAL_ONLY, DEFAULT_LOCAL_ONLY)
    base_url_default = defaults.get(CONF_BASE_URL)
    if base_url_default is None:
        base_url_default = _best_effort_base_url(hass, local_only)
    return vol.Schema(
        {
            vol.Required(
                CONF_WEBHOOK_ID,
                default=defaults.get(CONF_WEBHOOK_ID) or webhook.async_generate_id(),
            ): str,
            vol.Required(CONF_LOCAL_ONLY, default=local_only): bool,
            vol.Optional(CONF_BASE_URL, default=base_url_default): str,
        }
    )


def _best_effort_base_url(hass: HomeAssistant, local_only: bool) -> str:
    return resolve_base_url_value(hass, None, local_only) or ""


# ------------------------------------------------------------------- flow --


class SpoolmanActiveSpoolConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup and reconfigure for both entry kinds."""

    VERSION = 1

    def _hub_exists(self) -> bool:
        return any(
            e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB
            for e in self._async_current_entries(include_ignore=False)
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._hub_exists():
            return await self.async_step_printer()
        return self.async_show_menu(menu_options=["printer", "webhook"])

    # --------------------------------------------------------- printer --

    async def _async_try_connect_printer(self, data: dict[str, Any]) -> dict[str, str]:
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

    @staticmethod
    def _coerce_printer(user_input: dict[str, Any]) -> dict[str, Any]:
        user_input[CONF_NAME] = user_input[CONF_NAME].strip()
        user_input[CONF_MOONRAKER_URL] = _normalize_url(user_input[CONF_MOONRAKER_URL])
        user_input[CONF_POLL_INTERVAL] = int(user_input[CONF_POLL_INTERVAL])
        return user_input

    async def async_step_printer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input = self._coerce_printer(user_input)
            errors = await self._async_try_connect_printer(user_input)
            if not errors:
                await self.async_set_unique_id(user_input[CONF_MOONRAKER_URL].lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_ENTRY_TYPE: ENTRY_TYPE_PRINTER,
                        CONF_MOONRAKER_URL: user_input[CONF_MOONRAKER_URL],
                        CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL],
                        CONF_POLL_INTERVAL: user_input[CONF_POLL_INTERVAL],
                    },
                )

        return self.async_show_form(
            step_id="printer", data_schema=_connection_schema(), errors=errors
        )

    async def async_step_reconfigure_printer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            user_input = self._coerce_printer(user_input)
            errors = await self._async_try_connect_printer(user_input)
            if not errors:
                await self.async_set_unique_id(user_input[CONF_MOONRAKER_URL].lower())
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    title=user_input[CONF_NAME],
                    data={
                        CONF_ENTRY_TYPE: ENTRY_TYPE_PRINTER,
                        CONF_MOONRAKER_URL: user_input[CONF_MOONRAKER_URL],
                        CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL],
                        CONF_POLL_INTERVAL: user_input[CONF_POLL_INTERVAL],
                    },
                )

        return self.async_show_form(
            step_id="reconfigure_printer",
            data_schema=_connection_schema(
                {
                    CONF_NAME: reconfigure_entry.title,
                    CONF_MOONRAKER_URL: reconfigure_entry.data[CONF_MOONRAKER_URL],
                    CONF_VERIFY_SSL: reconfigure_entry.data.get(
                        CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL
                    ),
                    CONF_POLL_INTERVAL: reconfigure_entry.data.get(
                        CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                    ),
                }
            ),
            errors=errors,
        )

    # ---------------------------------------------------------- webhook --

    async def async_step_webhook(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._hub_exists():
            return self.async_abort(reason="already_configured")

        errors: dict[str, str] = {}
        if user_input is not None:
            webhook_id = user_input[CONF_WEBHOOK_ID].strip()
            base_url = user_input.get(CONF_BASE_URL, "").strip().rstrip("/")
            error = await _validate_webhook_id(self.hass, webhook_id, unchanged=False)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title="QR odkazy (webhook)",
                    data={
                        CONF_ENTRY_TYPE: ENTRY_TYPE_HUB,
                        CONF_WEBHOOK_ID: webhook_id,
                        CONF_LOCAL_ONLY: user_input[CONF_LOCAL_ONLY],
                        CONF_BASE_URL: base_url,
                    },
                )

        return self.async_show_form(
            step_id="webhook", data_schema=_webhook_schema(self.hass), errors=errors
        )

    async def async_step_reconfigure_webhook(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            webhook_id = user_input[CONF_WEBHOOK_ID].strip()
            base_url = user_input.get(CONF_BASE_URL, "").strip().rstrip("/")
            unchanged = webhook_id == reconfigure_entry.data.get(CONF_WEBHOOK_ID)
            error = await _validate_webhook_id(self.hass, webhook_id, unchanged=unchanged)
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data={
                        CONF_ENTRY_TYPE: ENTRY_TYPE_HUB,
                        CONF_WEBHOOK_ID: webhook_id,
                        CONF_LOCAL_ONLY: user_input[CONF_LOCAL_ONLY],
                        CONF_BASE_URL: base_url,
                    },
                )

        return self.async_show_form(
            step_id="reconfigure_webhook",
            data_schema=_webhook_schema(
                self.hass,
                {
                    CONF_WEBHOOK_ID: reconfigure_entry.data[CONF_WEBHOOK_ID],
                    CONF_LOCAL_ONLY: reconfigure_entry.data.get(
                        CONF_LOCAL_ONLY, DEFAULT_LOCAL_ONLY
                    ),
                    CONF_BASE_URL: reconfigure_entry.data.get(CONF_BASE_URL) or None,
                },
            ),
            errors=errors,
        )

    # ------------------------------------------------------- reconfigure --

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Entry point for Reconfigure - dispatch by entry type."""
        entry = self._get_reconfigure_entry()
        if entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_PRINTER) == ENTRY_TYPE_HUB:
            return await self.async_step_reconfigure_webhook(user_input)
        return await self.async_step_reconfigure_printer(user_input)
