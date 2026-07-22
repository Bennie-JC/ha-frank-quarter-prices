"""Unit tests for the feed-in price calculation helper."""

from __future__ import annotations

import pytest

from custom_components.frank_quarter_prices.price import (
    CALC_API_FEED_IN_PRICE,
    CALC_MARKET_PRICE_PLUS_ADJUSTMENT,
    CALC_MARKET_PRICE_PLUS_ADJUSTMENT_VAT,
    calculate_feed_in_price,
    calculation_method,
    get_apply_feed_in_vat,
    get_feed_in_adjustment,
)


def _block(**overrides):
    """Return a realistic price block, with optional field overrides."""
    block = {
        "market_price": 0.08,
        "market_price_tax": 0.0168,
        "sourcing_markup_price": 0.018,
        "energy_tax_price": 0.11085,
        "total_price_eur_kwh": 0.22565,
        "per_unit": "KWH",
    }
    block.update(overrides)
    return block


def test_zero_adjustment_uses_market_price():
    """Zero adjustment returns the verified market price unchanged."""
    assert calculate_feed_in_price(_block(), 0.0) == 0.08


def test_positive_adjustment():
    """A positive adjustment is added to the market price."""
    assert calculate_feed_in_price(_block(), 0.018) == pytest.approx(0.098)


def test_negative_adjustment():
    """A negative adjustment is subtracted from the market price."""
    assert calculate_feed_in_price(_block(), -0.017) == pytest.approx(0.063)


def test_negative_result_is_not_clamped():
    """A negative final feed-in price is retained, not clamped to zero."""
    result = calculate_feed_in_price(_block(market_price=0.01), -0.05)
    assert result == pytest.approx(-0.04)
    assert result < 0


def test_missing_market_price_returns_none():
    """Missing market price yields None (entity becomes unavailable)."""
    block = _block()
    del block["market_price"]
    assert calculate_feed_in_price(block, 0.0) is None


def test_non_numeric_market_price_returns_none():
    """Non-numeric market price yields None."""
    assert calculate_feed_in_price(_block(market_price="oops"), 0.0) is None
    assert calculate_feed_in_price(_block(market_price=None), 0.0) is None
    assert calculate_feed_in_price(_block(market_price=True), 0.0) is None


def test_none_block_returns_none():
    """A missing block yields None."""
    assert calculate_feed_in_price(None, 0.0) is None


def test_purchase_only_components_are_ignored():
    """market_price_tax / energy_tax / sourcing markup are never added in."""
    # Only market_price and adjustment should influence the result. Wildly
    # different purchase components must not change the outcome.
    a = calculate_feed_in_price(_block(), 0.0)
    b = calculate_feed_in_price(
        _block(
            market_price_tax=99.0,
            energy_tax_price=99.0,
            sourcing_markup_price=99.0,
            total_price_eur_kwh=999.0,
        ),
        0.0,
    )
    assert a == b == 0.08


def test_explicit_api_feed_in_price_takes_precedence():
    """An explicit feed_in_price field wins over the reconstruction."""
    block = _block(feed_in_price=0.05)
    # Adjustment is ignored when an explicit API value exists.
    assert calculate_feed_in_price(block, 0.5) == 0.05
    assert calculation_method(block) == CALC_API_FEED_IN_PRICE


def test_calculation_method_without_explicit_field():
    """Without an explicit field the method label is the reconstruction."""
    assert calculation_method(_block()) == CALC_MARKET_PRICE_PLUS_ADJUSTMENT


def test_get_feed_in_adjustment_default():
    """Missing option falls back to 0.0."""
    assert get_feed_in_adjustment({}) == 0.0
    assert get_feed_in_adjustment(None) == 0.0


def test_get_feed_in_adjustment_positive_negative_zero():
    """Configured values override the default (positive, negative, zero)."""
    assert get_feed_in_adjustment({"feed_in_adjustment": 0.018}) == 0.018
    assert get_feed_in_adjustment({"feed_in_adjustment": -0.017}) == -0.017
    assert get_feed_in_adjustment({"feed_in_adjustment": 0.0}) == 0.0


def test_get_feed_in_adjustment_invalid_falls_back():
    """Invalid option value falls back to the default."""
    assert get_feed_in_adjustment({"feed_in_adjustment": "abc"}) == 0.0
    assert get_feed_in_adjustment({"feed_in_adjustment": None}) == 0.0


# --- VAT ----------------------------------------------------------------


def test_vat_disabled_preserves_calculation():
    """With VAT disabled the result equals market_price + adjustment."""
    assert calculate_feed_in_price(_block(), 0.02, apply_vat=False) == pytest.approx(
        0.10
    )
    # Default arg is False (backward compatible).
    assert calculate_feed_in_price(_block(), 0.02) == pytest.approx(0.10)


def test_vat_enabled_multiplies_full_compensation():
    """VAT enabled applies 1.21 to (market_price + adjustment)."""
    result = calculate_feed_in_price(_block(), 0.02, apply_vat=True)
    assert result == pytest.approx(round((0.08 + 0.02) * 1.21, 6))
    assert result == pytest.approx(0.121)


def test_vat_applied_after_adjustment_not_only_market_price():
    """VAT must apply after adding the adjustment, not to market price alone."""
    result = calculate_feed_in_price(_block(), 0.02, apply_vat=True)
    # Wrong model would be market_price*1.21 + adjustment = 0.1168.
    assert result != pytest.approx(0.08 * 1.21 + 0.02)


def test_vat_enabled_positive_adjustment():
    """Positive adjustment with VAT."""
    assert calculate_feed_in_price(
        _block(market_price=0.00323), 0.0182, apply_vat=True
    ) == pytest.approx(round((0.00323 + 0.0182) * 1.21, 6))


def test_vat_enabled_negative_adjustment():
    """Negative adjustment with VAT."""
    assert calculate_feed_in_price(_block(), -0.017, apply_vat=True) == pytest.approx(
        round((0.08 - 0.017) * 1.21, 6)
    )


def test_vat_enabled_zero_adjustment():
    """Zero adjustment with VAT is just market_price * 1.21."""
    assert calculate_feed_in_price(_block(), 0.0, apply_vat=True) == pytest.approx(
        round(0.08 * 1.21, 6)
    )


def test_vat_enabled_negative_result_not_clamped():
    """A negative final price with VAT stays negative."""
    result = calculate_feed_in_price(_block(market_price=0.01), -0.05, apply_vat=True)
    assert result == pytest.approx(round((0.01 - 0.05) * 1.21, 6))
    assert result < 0


def test_vat_missing_market_price_returns_none():
    """Missing market price returns None regardless of VAT flag."""
    block = _block()
    del block["market_price"]
    assert calculate_feed_in_price(block, 0.0, apply_vat=True) is None


def test_vat_not_applied_to_explicit_api_price():
    """An explicit API feed-in price is used as-is, without VAT."""
    block = _block(feed_in_price=0.05)
    assert calculate_feed_in_price(block, 0.0, apply_vat=True) == 0.05


def test_calculation_method_with_vat():
    """The method label reflects the VAT flag."""
    assert calculation_method(_block(), apply_vat=False) == (
        CALC_MARKET_PRICE_PLUS_ADJUSTMENT
    )
    assert calculation_method(_block(), apply_vat=True) == (
        CALC_MARKET_PRICE_PLUS_ADJUSTMENT_VAT
    )
    # Explicit API field wins over VAT labelling.
    assert calculation_method(_block(feed_in_price=0.05), apply_vat=True) == (
        CALC_API_FEED_IN_PRICE
    )


def test_get_apply_feed_in_vat_default_false():
    """Missing option defaults to False."""
    assert get_apply_feed_in_vat({}) is False
    assert get_apply_feed_in_vat(None) is False


def test_get_apply_feed_in_vat_true_false():
    """Configured values are honoured."""
    assert get_apply_feed_in_vat({"apply_feed_in_vat": True}) is True
    assert get_apply_feed_in_vat({"apply_feed_in_vat": False}) is False
