"""Config flow for PVHub integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_API_URL,
    CONF_PLANT_ID,
    CONF_COOKIE,
    CONF_TOKEN,
    CONF_SIGNATURE,
    CONF_TIMESTAMP,
    CONF_LANG,
    CONF_TIMEZONE,
    DEFAULT_API_URL,
    DEFAULT_LANG,
)


class PVHubConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PVHub."""

    VERSION = 1

    # ---------------------------------------------------------
    # Initial setup
    # ---------------------------------------------------------
    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial setup step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=self._schema(),
            )

        return self.async_create_entry(
            title="PVHub",
            data=user_input,
        )

    # ---------------------------------------------------------
    # Menu step (HA shows "Reconfigure")
    # ---------------------------------------------------------
    async def async_step_menu(self, user_input=None) -> FlowResult:
        return self.async_show_menu(
            step_id="menu",
            menu_options=["reconfigure"],
        )

    # ---------------------------------------------------------
    # Reconfigure existing entry
    # ---------------------------------------------------------
    async def async_step_reconfigure(self, user_input=None) -> FlowResult:
        """Handle reconfiguration of the integration."""
        entry = self._get_reconfigure_entry()
        if entry is None:
            return self.async_abort(reason="no_config_entry")

        if user_input is None:
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=self._schema(entry.data),
            )

        # Update entry
        self.hass.config_entries.async_update_entry(
            entry,
            data=user_input,
        )

        await self.hass.config_entries.async_reload(entry.entry_id)
        return self.async_abort(reason="reconfigured")

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------
    def _schema(self, defaults=None):
        """Shared schema for both setup and reconfigure."""
        defaults = defaults or {}
        return vol.Schema(
            {
                vol.Required(CONF_API_URL, default=defaults.get(CONF_API_URL, DEFAULT_API_URL)): str,
                vol.Required(CONF_PLANT_ID, default=defaults.get(CONF_PLANT_ID, "")): str,
                vol.Required(CONF_COOKIE, default=defaults.get(CONF_COOKIE, "")): str,
                vol.Required(CONF_TOKEN, default=defaults.get(CONF_TOKEN, "")): str,
                vol.Required(CONF_SIGNATURE, default=defaults.get(CONF_SIGNATURE, "")): str,
                vol.Required(CONF_TIMESTAMP, default=defaults.get(CONF_TIMESTAMP, "")): str,
                vol.Optional(CONF_LANG, default=defaults.get(CONF_LANG, DEFAULT_LANG)): str,
                vol.Optional(CONF_TIMEZONE, default=defaults.get(CONF_TIMEZONE, "")): str,
            }
        )

    def _get_reconfigure_entry(self):
        """Return the config entry being reconfigured."""
        entries = self.hass.config_entries.async_entries(DOMAIN)
        return entries[0] if entries else None

