"""Config flow for the Frank Quarter Prices integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_API_TOKEN, CONF_SITE_REFERENCE, DEFAULT_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_TOKEN): str,
        vol.Optional(CONF_SITE_REFERENCE): str,
    }
)


class FrankQuarterPricesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Frank Quarter Prices."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validation against the Frank API is not implemented yet.
            # Once available, validate credentials here and set errors on failure.
            await self.async_set_unique_id(
                user_input.get(CONF_SITE_REFERENCE) or user_input[CONF_API_TOKEN]
            )
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=DEFAULT_NAME,
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
