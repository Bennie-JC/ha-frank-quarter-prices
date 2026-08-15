"""Diagnostics support for the Frank Quarter Prices integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_COUNTRY, DEFAULT_COUNTRY
from .market_time import market_timezone
from .optimal_period import (
    get_optimal_cheap_duration_minutes,
    get_optimal_cheap_enabled,
    get_optimal_expensive_duration_minutes,
    get_optimal_expensive_enabled,
)
from .price import MARKET_PRICE_FIELD, get_apply_feed_in_vat, get_feed_in_adjustment
from .price_zone import (
    get_cheap_zone_margin_percent,
    get_expensive_zone_margin_percent,
)

if TYPE_CHECKING:
    from . import FrankQuarterPricesConfigEntry

# No secrets are stored by this integration (the Frank market prices API
# requires no authentication), so nothing needs to be redacted.
TO_REDACT: set[str] = set()


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FrankQuarterPricesConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    ``runtime_data`` only exists while the entry is loaded: Home Assistant
    deletes it on unload, and it is never set when setup fails. The diagnostics
    endpoint has no such precondition — it serves any entry that exists — so
    reading it unguarded would answer with a 500 exactly when the entry is in
    ``SETUP_RETRY`` (the Frank API was down at startup) and a user is trying to
    collect diagnostics to report that. The settings below need no coordinator,
    so they are always reported.
    """
    coordinator = getattr(entry, "runtime_data", None)
    country = entry.options.get(
        CONF_COUNTRY, entry.data.get(CONF_COUNTRY, DEFAULT_COUNTRY)
    )

    return {
        "entry": {
            "title": entry.title,
            "state": str(entry.state),
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "coordinator": {
            "loaded": coordinator is not None,
            "last_update_success": (
                coordinator.last_update_success if coordinator else None
            ),
            "data": coordinator.data if coordinator else None,
        },
        # The derived cheap/expensive zones themselves already travel inside
        # ``coordinator.data``; only the resolved settings behind them are added
        # here, so the effective values are visible even on a day that yields no
        # zone at all.
        "resolved_options": {
            # The market whose day the prices describe, and the timezone that
            # defines it — the two most useful facts when a day is not
            # validating as complete. Home Assistant's own timezone is shown
            # alongside precisely because the two may legitimately differ.
            "country": country,
            "market_timezone": str(market_timezone(country)),
            "homeassistant_timezone": str(hass.config.time_zone),
            "cheap_margin_percent": get_cheap_zone_margin_percent(entry.options),
            "expensive_margin_percent": get_expensive_zone_margin_percent(
                entry.options
            ),
            # The optimal-period settings as they are actually in force. The
            # derived periods themselves already travel inside
            # ``coordinator.data``, so only the resolved settings are added
            # here — enough to explain an unavailable planner entity without
            # dumping a second copy of the daily price array.
            #
            # A duration of ``null`` means the stored value is not a usable
            # duration and the planner is deliberately not running. The raw
            # stored value is not repeated here because ``entry.options`` above
            # already carries it verbatim, which is exactly what a bug report
            # needs to see next to this.
            "optimal_cheap_enabled": get_optimal_cheap_enabled(entry.options),
            "optimal_cheap_duration_minutes": get_optimal_cheap_duration_minutes(
                entry.options
            ),
            "optimal_expensive_enabled": get_optimal_expensive_enabled(entry.options),
            "optimal_expensive_duration_minutes": (
                get_optimal_expensive_duration_minutes(entry.options)
            ),
            "return_price_source": MARKET_PRICE_FIELD,
            "return_price_apply_vat": get_apply_feed_in_vat(entry.options),
            "return_price_feed_in_adjustment": get_feed_in_adjustment(entry.options),
        },
    }
