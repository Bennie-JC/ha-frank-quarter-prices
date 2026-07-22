"""Feed-in (return-to-grid) price calculation helpers.

This module is intentionally free of Home Assistant imports so the calculation
can be unit-tested in isolation.

Verified Frank Energie price fields (public, unauthenticated ``marketPrices``
GraphQL query, checked against the live API in 2026-07):

* ``market_price``          -- the raw EPEX/spot electricity market price,
                               **excluding** VAT, energy tax and any markup.
* ``market_price_tax``      -- 21% VAT charged on ``market_price`` on the
                               *purchase* side (``market_price_tax`` /
                               ``market_price`` == 0.21 exactly). It is a
                               consumption-side tax and is **not** part of the
                               feed-in compensation.
* ``sourcing_markup_price`` -- Frank's sourcing/purchase markup
                               (inkoopvergoeding); a purchase-only cost.
* ``energy_tax_price``      -- energy tax (energiebelasting); a purchase-only
                               tax.
* ``total_price_eur_kwh``   -- the sum of the four fields above; the all-in
                               consumer *purchase* price.

The public endpoint exposes **no** explicit feed-in / return / selling price
field (every such field name is rejected with a GraphQL validation error), so
the verified market-price component used for electricity returned to the grid
is the raw ``market_price``. Purchase-side VAT, energy tax and markups are
deliberately excluded. Because only the pure market price is used, the value is
independent of net metering (saldering) and stays correct after the Dutch
net-metering scheme ends on 1 January 2027.

If Frank ever exposes an explicit feed-in-price field it should be preferred
over this reconstruction; ``calculate_feed_in_price`` already returns that field
when it is present in the price block.
"""

from __future__ import annotations

from typing import Any, Mapping

from .const import (
    CONF_APPLY_FEED_IN_VAT,
    CONF_FEED_IN_ADJUSTMENT,
    DEFAULT_APPLY_FEED_IN_VAT,
    DEFAULT_FEED_IN_ADJUSTMENT,
    FEED_IN_VAT_RATE,
)

# Price block key holding the verified market-price component used as the
# feed-in base.
MARKET_PRICE_FIELD: str = "market_price"

# Optional price block key for an explicit feed-in price. Not provided by the
# current public API, but honoured if it ever appears so no calculation is
# needed. Kept distinct from the purchase fields on purpose.
FEED_IN_PRICE_FIELD: str = "feed_in_price"

# Stable values for the ``calculation_method`` attribute.
CALC_API_FEED_IN_PRICE: str = "api_feed_in_price"
CALC_MARKET_PRICE_PLUS_ADJUSTMENT: str = "market_price_plus_adjustment"
CALC_MARKET_PRICE_PLUS_ADJUSTMENT_VAT: str = (
    "market_price_plus_adjustment_including_vat"
)

# Precision used for the price sensors (matches the existing price sensors).
_PRICE_PRECISION = 6


def _as_number(value: Any) -> float | None:
    """Return ``value`` as a float, or ``None`` when it is not numeric.

    Booleans are rejected: ``True``/``False`` are ints in Python but never a
    valid price.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def calculate_feed_in_price(
    price_block: Mapping[str, Any] | None,
    adjustment: float,
    apply_vat: bool = False,
) -> float | None:
    """Calculate the current feed-in price in EUR/kWh.

    When the price block carries an explicit feed-in-price field it is used
    unchanged (the API value takes precedence). Otherwise the price is the
    verified ``market_price`` plus the configured ``adjustment``:

        feed_in_price = market_price + adjustment

    When ``apply_vat`` is ``True``, 21% VAT is applied to the complete
    compensation (market price plus adjustment):

        feed_in_price = (market_price + adjustment) * 1.21

    VAT is an explicit user choice, never inferred from API fields, and is not
    applied to an explicit API feed-in price. The adjustment may be positive,
    negative or zero. The result may be negative and is never clamped. Returns
    ``None`` (so the entity becomes unavailable) when the required source data
    is missing or non-numeric.
    """
    if not isinstance(price_block, Mapping):
        return None

    # Prefer an explicit API feed-in price if one is ever provided.
    explicit = _as_number(price_block.get(FEED_IN_PRICE_FIELD))
    if explicit is not None:
        return round(explicit, _PRICE_PRECISION)

    market_price = _as_number(price_block.get(MARKET_PRICE_FIELD))
    if market_price is None:
        return None

    adjustment_value = _as_number(adjustment)
    if adjustment_value is None:
        adjustment_value = 0.0

    base_price = market_price + adjustment_value
    if apply_vat:
        base_price *= 1.0 + FEED_IN_VAT_RATE

    return round(base_price, _PRICE_PRECISION)


def calculation_method(
    price_block: Mapping[str, Any] | None, apply_vat: bool = False
) -> str:
    """Return the stable calculation-method label for a price block."""
    if isinstance(price_block, Mapping) and _as_number(
        price_block.get(FEED_IN_PRICE_FIELD)
    ) is not None:
        return CALC_API_FEED_IN_PRICE
    if apply_vat:
        return CALC_MARKET_PRICE_PLUS_ADJUSTMENT_VAT
    return CALC_MARKET_PRICE_PLUS_ADJUSTMENT


def get_feed_in_adjustment(options: Mapping[str, Any] | None) -> float:
    """Return the configured feed-in adjustment, defaulting to 0.0.

    Accepts a config entry's ``options`` mapping. Falls back to the default
    when the option is absent or not a valid number, so existing installations
    keep working without reconfiguration.
    """
    if not isinstance(options, Mapping):
        return DEFAULT_FEED_IN_ADJUSTMENT
    value = _as_number(options.get(CONF_FEED_IN_ADJUSTMENT))
    if value is None:
        return DEFAULT_FEED_IN_ADJUSTMENT
    return value


def get_apply_feed_in_vat(options: Mapping[str, Any] | None) -> bool:
    """Return whether 21% VAT should be applied, defaulting to False.

    Accepts a config entry's ``options`` mapping. Existing installations
    without the option behave as if VAT is disabled, preserving their current
    sensor value without reconfiguration.
    """
    if not isinstance(options, Mapping):
        return DEFAULT_APPLY_FEED_IN_VAT
    return bool(options.get(CONF_APPLY_FEED_IN_VAT, DEFAULT_APPLY_FEED_IN_VAT))
