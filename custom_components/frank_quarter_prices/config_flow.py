"""Config flow for the Frank Quarter Prices integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_COUNTRY,
    DEFAULT_COUNTRY,
    DEFAULT_NAME,
    DOMAIN,
    SUPPORTED_COUNTRIES,
)

_LOGGER = logging.getLogger(__name__)

# Human-readable labels for the supported country codes. The stored option
# value stays the uppercase ISO code (e.g. "NL"), which is sent in the
# x-country header; only the displayed label differs.
_COUNTRY_LABELS: dict[str, str] = {
    "NL": "Netherlands (NL)",
    "BE": "Belgium (BE)",
}

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_COUNTRY, default=DEFAULT_COUNTRY): SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(value=country, label=_COUNTRY_LABELS.get(country, country))
                    for country in SUPPORTED_COUNTRIES
                ],
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
    }
)


class FrankQuarterPricesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Frank Quarter Prices."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step.

        The Frank Energie market prices API requires no authentication, so the
        entry is created immediately once a country is selected.
        """
        if user_input is not None:
            country = user_input[CONF_COUNTRY]
            await self.async_set_unique_id(country)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"{DEFAULT_NAME} ({country})",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
        )
