"""Pure unit tests for the dynamic "marktprijs+" price helper.

No Home Assistant imports: the helper lives in the framework-free ``price``
module so it can be exercised with plain dictionaries.

The expected values are Frank's own ``marketPricePlus`` figures for real
quarter-hour blocks, so these tests pin the published contract rather than the
implementation's own arithmetic.
"""

from __future__ import annotations

import pytest

from custom_components.frank_quarter_prices.price import calculate_dynamic_price


def _block(market_price, market_price_tax, markup, **extra):
    """Build a minimal price block carrying the three dynamic-basis components."""
    block = {
        "market_price": market_price,
        "market_price_tax": market_price_tax,
        "sourcing_markup_price": markup,
    }
    block.update(extra)
    return block


def _taxed(market_price, markup=0.01815):
    """Build a block whose VAT is the API's 21% of the market price."""
    return _block(market_price, round(market_price * 0.21, 6), markup)


# --- Required vectors --------------------------------------------------------


def test_dynamic_price_positive():
    """Positive market price: all three components add up, no clamping."""
    assert calculate_dynamic_price(_taxed(0.08123)) == pytest.approx(0.116438)


def test_dynamic_price_zero_market():
    """Zero market price: VAT on it is zero too, so only the markup remains."""
    assert calculate_dynamic_price(_block(0.0, 0.0, 0.01815)) == pytest.approx(0.01815)


def test_dynamic_price_negative_market():
    """Negative market price stays negative; nothing is inverted or clamped.

    The API returns a negative VAT on a negative market price, so the negative
    market price is made *more* negative before the markup is added.
    """
    value = calculate_dynamic_price(_block(-0.05, -0.0105, 0.01815))
    assert value == pytest.approx(-0.04235)
    assert value < 0


# --- Real published Frank values ---------------------------------------------
#
# Captured from the public ``marketPrices`` endpoint together with Frank's own
# ``marketPricePlus`` field. Each expected value below IS that published field,
# so the helper is checked against Frank's contract, not against itself.
#
#   date        block   market_price  market_price_tax  markup    marketPricePlus
#   2026-09-06  00:00      0.17334          0.03640      0.01815      0.22789
#   2026-09-06  13:00     -0.00385         -0.00081      0.01815      0.01349
#   2026-09-06  11:00      0.00000          0.00000      0.01815      0.01815
#   2026-09-06  20:00      0.22499          0.04725      0.01815      0.29039
#   2026-09-09  10:00      0.11190          0.02350      0.01815      0.15355


@pytest.mark.parametrize(
    ("market_price", "market_price_tax", "markup", "market_price_plus"),
    [
        (0.17334, 0.03640, 0.01815, 0.22789),
        (-0.00385, -0.00081, 0.01815, 0.01349),
        (0.00000, 0.00000, 0.01815, 0.01815),
        (0.22499, 0.04725, 0.01815, 0.29039),
        (0.11190, 0.02350, 0.01815, 0.15355),
    ],
)
def test_dynamic_price_matches_published_market_price_plus(
    market_price, market_price_tax, markup, market_price_plus
):
    """The helper reproduces Frank's published ``marketPricePlus`` exactly."""
    block = _block(market_price, market_price_tax, markup)
    assert calculate_dynamic_price(block) == pytest.approx(market_price_plus)


def test_dynamic_price_is_not_the_mixed_vat_basis():
    """Regression guard: the VAT on the market price must not be dropped.

    ``market_price`` excludes VAT while ``sourcing_markup_price`` already
    includes it. Adding only those two mixes VAT bases and understates the
    result -- for this block it gives 0.19149 instead of Frank's 0.22789.
    """
    block = _block(0.17334, 0.03640, 0.01815)
    value = calculate_dynamic_price(block)
    assert value == pytest.approx(0.22789)
    assert value != pytest.approx(0.17334 + 0.01815)


def test_dynamic_price_is_the_all_in_price_minus_energy_tax():
    """The dynamic basis is the all-in consumer price without the energy tax."""
    market_price, tax, markup, energy_tax = 0.22499, 0.04725, 0.01815, 0.11085
    all_in = round(market_price + tax + markup + energy_tax, 6)
    block = _block(market_price, tax, markup, energy_tax_price=energy_tax)
    assert calculate_dynamic_price(block) == pytest.approx(all_in - energy_tax)


# --- Per-quarter components, nothing hard-coded ------------------------------


def test_dynamic_price_per_quarter_markup_not_constant():
    """Two blocks with the same market price but different markups differ."""
    assert calculate_dynamic_price(_block(0.10, 0.021, 0.01815)) == pytest.approx(
        0.13915
    )
    assert calculate_dynamic_price(_block(0.10, 0.021, 0.02500)) == pytest.approx(0.146)


def test_dynamic_price_per_quarter_vat_not_constant():
    """The VAT term is read from the block, not derived from a hard-coded rate."""
    assert calculate_dynamic_price(_block(0.10, 0.021, 0.01815)) == pytest.approx(
        0.13915
    )
    # A block whose VAT component differs must produce a different result.
    assert calculate_dynamic_price(_block(0.10, 0.009, 0.01815)) == pytest.approx(
        0.12715
    )


# --- Missing and invalid components ------------------------------------------


def test_dynamic_price_missing_markup_returns_none():
    """A block missing the sourcing markup yields None, not a wrong price."""
    assert calculate_dynamic_price({"market_price": 0.10, "market_price_tax": 0.021}) is None


def test_dynamic_price_missing_market_price_tax_returns_none():
    """A block missing the market-price VAT yields None rather than dropping it."""
    assert (
        calculate_dynamic_price(
            {"market_price": 0.10, "sourcing_markup_price": 0.01815}
        )
        is None
    )


def test_dynamic_price_missing_market_returns_none():
    """A block missing the market price yields None."""
    assert (
        calculate_dynamic_price(
            {"market_price_tax": 0.021, "sourcing_markup_price": 0.01815}
        )
        is None
    )


def test_dynamic_price_non_numeric_components_return_none():
    """Non-numeric or boolean components yield None."""
    assert calculate_dynamic_price(_block(0.10, 0.021, "0.01815")) is None
    assert calculate_dynamic_price(_block(0.10, 0.021, True)) is None
    assert calculate_dynamic_price(_block(0.10, "0.021", 0.01815)) is None
    assert calculate_dynamic_price(_block("0.10", 0.021, 0.01815)) is None
    assert calculate_dynamic_price(_block(0.10, None, 0.01815)) is None


def test_dynamic_price_none_block_returns_none():
    """A missing block yields None so the entity publishes unknown."""
    assert calculate_dynamic_price(None) is None
    assert calculate_dynamic_price({}) is None


def test_dynamic_price_rounding():
    """The result is rounded to the same 6-decimal precision as every other price."""
    block = _block(0.0812333333, 0.0170590, 0.01815)
    assert calculate_dynamic_price(block) == pytest.approx(0.116442)
