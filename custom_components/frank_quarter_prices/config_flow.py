"""Config flow for the Frank Quarter Prices integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_APPLY_FEED_IN_VAT,
    CONF_COUNTRY,
    CONF_FEED_IN_ADJUSTMENT,
    DEFAULT_APPLY_FEED_IN_VAT,
    DEFAULT_COUNTRY,
    DEFAULT_FEED_IN_ADJUSTMENT,
    DEFAULT_NAME,
    DOMAIN,
    FEED_IN_ADJUSTMENT_STEP,
    MAX_FEED_IN_ADJUSTMENT,
    MIN_FEED_IN_ADJUSTMENT,
    PRICE_UNIT_EUR_KWH,
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

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> FrankQuarterPricesOptionsFlow:
        """Return the options flow handler."""
        return FrankQuarterPricesOptionsFlow()


class FrankQuarterPricesOptionsFlow(OptionsFlow):
    """Handle the options flow for Frank Quarter Prices.

    The options are the feed-in adjustment and an optional 21% VAT toggle.
    Neither is required during the initial setup, and existing entries without
    them fall back to their defaults (0.0 adjustment, VAT disabled).
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the feed-in adjustment and VAT options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current_adjustment = self.config_entry.options.get(
            CONF_FEED_IN_ADJUSTMENT, DEFAULT_FEED_IN_ADJUSTMENT
        )
        current_vat = self.config_entry.options.get(
            CONF_APPLY_FEED_IN_VAT, DEFAULT_APPLY_FEED_IN_VAT
        )
        options_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_FEED_IN_ADJUSTMENT, default=current_adjustment
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_FEED_IN_ADJUSTMENT,
                        max=MAX_FEED_IN_ADJUSTMENT,
                        step=FEED_IN_ADJUSTMENT_STEP,
                        unit_of_measurement=PRICE_UNIT_EUR_KWH,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_APPLY_FEED_IN_VAT, default=current_vat
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=options_schema)
