"""Config flow for PVHub 2.0."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .api import PVHubAuthError, PVHubClient, PVHubError
from .const import (
    CONF_API_URL,
    CONF_COOKIE,
    CONF_LANG,
    CONF_PLANT_ID,
    CONF_SIGNATURE,
    CONF_TIMESTAMP,
    CONF_TIMEZONE,
    CONF_TOKEN,
    DEFAULT_API_URL,
    DEFAULT_LANG,
    DOMAIN,
)


_LOGGER = logging.getLogger(__name__)


class PVHubConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a PVHub config flow."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Handle the initial step."""

        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_PLANT_ID])
            self._abort_if_unique_id_configured()

            try:
                await validate_input(self.hass, user_input)
            except PVHubAuthError as exc:
                _LOGGER.debug("PVHub authentication validation failed: %s", exc)
                errors["base"] = "auth_failed"
            except PVHubError as exc:
                _LOGGER.debug("PVHub validation failed: %s", exc)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error while validating PVHub config flow")
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"PVHub {user_input[CONF_PLANT_ID][:8]}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_URL, default=DEFAULT_API_URL): str,
                    vol.Required(CONF_PLANT_ID): str,
                    vol.Required(CONF_COOKIE): str,
                    vol.Required(CONF_TOKEN): str,
                    vol.Required(CONF_SIGNATURE): str,
                    vol.Required(CONF_TIMESTAMP): str,
                    vol.Optional(CONF_LANG, default=DEFAULT_LANG): str,
                    vol.Optional(CONF_TIMEZONE): str,
                }
            ),
            errors=errors,
        )


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Validate copied PVHub request details with one read-only request."""

    client = PVHubClient.from_config(data)
    await hass.async_add_executor_job(client.get_analysis)
