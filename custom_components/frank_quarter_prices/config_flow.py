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
    CONF_CHEAP_ZONE_MARGIN_PERCENT,
    CONF_COUNTRY,
    CONF_EXPENSIVE_ZONE_MARGIN_PERCENT,
    CONF_FEED_IN_ADJUSTMENT,
    CONF_OPTIMAL_CHEAP_DURATION_MINUTES,
    CONF_OPTIMAL_CHEAP_ENABLED,
    CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES,
    CONF_OPTIMAL_EXPENSIVE_ENABLED,
    DEFAULT_APPLY_FEED_IN_VAT,
    DEFAULT_COUNTRY,
    DEFAULT_FEED_IN_ADJUSTMENT,
    DEFAULT_NAME,
    DEFAULT_OPTIMAL_DURATION_MINUTES,
    DEFAULT_OPTIMAL_ENABLED,
    DEFAULT_ZONE_MARGIN_PERCENT,
    DOMAIN,
    FEED_IN_ADJUSTMENT_STEP,
    MAX_FEED_IN_ADJUSTMENT,
    MAX_OPTIMAL_DURATION_MINUTES,
    MAX_ZONE_MARGIN_PERCENT,
    MIN_FEED_IN_ADJUSTMENT,
    MIN_OPTIMAL_DURATION_MINUTES,
    MIN_ZONE_MARGIN_PERCENT,
    MINUTES_UNIT,
    OPTIMAL_DURATION_STEP_MINUTES,
    PERCENT_UNIT,
    PRICE_UNIT_EUR_KWH,
    SUPPORTED_COUNTRIES,
    ZONE_MARGIN_PERCENT_STEP,
)
from .optimal_period import validate_duration_minutes

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
                    SelectOptionDict(
                        value=country, label=_COUNTRY_LABELS.get(country, country)
                    )
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

    One flat step in three logical groups, top to bottom: the feed-in settings,
    the two price-zone margins, then the two optional optimal periods. None of
    them is required during the initial setup, and an existing entry without
    them falls back to its defaults (0.0 adjustment, VAT disabled, 15% for both
    zone margins, both optimal periods off), so an install upgrading from an
    earlier version keeps working untouched.

    **Why the form is flat rather than grouped into collapsible sections.**
    Home Assistant does support sections in a config/options flow
    (``data_entry_flow.section``), and this form is exactly the shape they were
    designed for. They were still not used, for one decisive reason: a section
    *nests the stored values under the section key*. ``feed_in_adjustment``
    would become ``feed_in.feed_in_adjustment`` in the entry's options, which
    would silently reset the feed-in adjustment, the VAT toggle and both zone
    margins for every existing installation on the first save, and would need a
    flatten-on-save / inflate-on-load shim plus an options migration to avoid
    it. That is a real compatibility and fragility cost for a purely cosmetic
    gain, and this release explicitly keeps the options UI simple. The fields
    are therefore ordered so the three groups still read as groups, and each
    carries a description that says which feature it belongs to.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the feed-in, price-zone and optimal-period options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # The number selector enforces the 15-720 range and the type, but
            # *not* the step: it accepts 17 or 22.5 quite happily. The frontend
            # box does enforce the step, so this only bites a submission that
            # bypasses it, but a stored 17 would leave the planner permanently
            # unavailable for a reason the user cannot see. Validating here
            # keeps the stored configuration always usable.
            #
            # The check deliberately lives in the step handler rather than in
            # the schema: wrapping the selector in ``vol.All`` makes the options
            # form fail to serialize for the frontend altogether, so the whole
            # form would stop rendering.
            for key in (
                CONF_OPTIMAL_CHEAP_DURATION_MINUTES,
                CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES,
            ):
                if (
                    key in user_input
                    and validate_duration_minutes(user_input[key]) is None
                ):
                    errors[key] = "invalid_duration"

            if not errors:
                return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        current_adjustment = options.get(
            CONF_FEED_IN_ADJUSTMENT, DEFAULT_FEED_IN_ADJUSTMENT
        )
        current_vat = options.get(CONF_APPLY_FEED_IN_VAT, DEFAULT_APPLY_FEED_IN_VAT)
        current_cheap_margin = options.get(
            CONF_CHEAP_ZONE_MARGIN_PERCENT, DEFAULT_ZONE_MARGIN_PERCENT
        )
        current_expensive_margin = options.get(
            CONF_EXPENSIVE_ZONE_MARGIN_PERCENT, DEFAULT_ZONE_MARGIN_PERCENT
        )
        options_schema = vol.Schema(
            {
                # --- Feed-in price ---
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
                # --- Price zones ---
                vol.Optional(
                    CONF_CHEAP_ZONE_MARGIN_PERCENT, default=current_cheap_margin
                ): _margin_selector(),
                vol.Optional(
                    CONF_EXPENSIVE_ZONE_MARGIN_PERCENT,
                    default=current_expensive_margin,
                ): _margin_selector(),
                # --- Optimal periods ---
                #
                # Each toggle is followed directly by its own duration. The
                # duration stays visible while the feature is off rather than
                # being hidden behind a second flow step: Home Assistant cannot
                # show or hide a field within one step without re-submitting the
                # form, and splitting one small form into two steps to hide two
                # inactive number boxes would make the UI worse, not better. The
                # field descriptions say the duration only applies while the
                # matching toggle is on.
                vol.Optional(
                    CONF_OPTIMAL_CHEAP_ENABLED,
                    default=options.get(
                        CONF_OPTIMAL_CHEAP_ENABLED, DEFAULT_OPTIMAL_ENABLED
                    ),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_OPTIMAL_CHEAP_DURATION_MINUTES,
                    default=options.get(
                        CONF_OPTIMAL_CHEAP_DURATION_MINUTES,
                        DEFAULT_OPTIMAL_DURATION_MINUTES,
                    ),
                ): _duration_selector(),
                vol.Optional(
                    CONF_OPTIMAL_EXPENSIVE_ENABLED,
                    default=options.get(
                        CONF_OPTIMAL_EXPENSIVE_ENABLED, DEFAULT_OPTIMAL_ENABLED
                    ),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES,
                    default=options.get(
                        CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES,
                        DEFAULT_OPTIMAL_DURATION_MINUTES,
                    ),
                ): _duration_selector(),
            }
        )
        if user_input is not None:
            # Re-showing the form after a validation error: keep everything the
            # user just typed, so only the offending field has to be corrected.
            options_schema = self.add_suggested_values_to_schema(
                options_schema, user_input
            )

        return self.async_show_form(
            step_id="init", data_schema=options_schema, errors=errors
        )


def _margin_selector() -> NumberSelector:
    """Return the selector shared by both price-zone margin options."""
    return NumberSelector(
        NumberSelectorConfig(
            min=MIN_ZONE_MARGIN_PERCENT,
            max=MAX_ZONE_MARGIN_PERCENT,
            step=ZONE_MARGIN_PERCENT_STEP,
            unit_of_measurement=PERCENT_UNIT,
            mode=NumberSelectorMode.BOX,
        )
    )


def _duration_selector() -> NumberSelector:
    """Return the selector shared by both optimal-period duration options.

    The 15-minute step means every offered value is a whole number of native
    quarter-hour blocks, so a duration chosen here can always be composed out of
    whole blocks on a quarter-hour day.
    """
    return NumberSelector(
        NumberSelectorConfig(
            min=MIN_OPTIMAL_DURATION_MINUTES,
            max=MAX_OPTIMAL_DURATION_MINUTES,
            step=OPTIMAL_DURATION_STEP_MINUTES,
            unit_of_measurement=MINUTES_UNIT,
            mode=NumberSelectorMode.BOX,
        )
    )
