"""The no-overlap invariant, on realistic and on real measured price days.

v0.1.6 originally set each threshold as a percentage of the *absolute* all-in
price. That price carries a fixed ~0.129 EUR/kWh energy-tax and markup floor
which has nothing to do with the market, so the band width was driven by the
floor rather than by the day's spread. On a flat winter day the band exceeded
the whole spread and the same quarter was reported as cheap *and* expensive.
Measured over a year of real Frank data: 33 of 317 days at the default 15%
margin, 90 of 317 at 25%, and one day (2025-10-04) where both zones covered all
24 hours and both period binary sensors read ``on`` continuously.

Making each margin a share of the day's own price *range* removes that by
construction::

    cheap_threshold     = day_min + spread * cheap%            / 100
    expensive_threshold = day_min + spread * (100 - expensive%) / 100

so ``cheap_threshold < expensive_threshold`` exactly when
``cheap% + expensive% < 100``. Capping each margin at 49 guarantees at most 98.

These tests hold that invariant against realistic price shapes rather than
against the ~10x-too-wide spreads the first fixtures used, because an
unrealistic spread hides precisely this failure.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from custom_components.frank_quarter_prices.const import (
    MAX_ZONE_MARGIN_PERCENT,
    MIN_ZONE_MARGIN_PERCENT,
    ZONE_MODE_CHEAP,
    ZONE_MODE_EXPENSIVE,
)
from custom_components.frank_quarter_prices.price_zone import (
    calculate_price_zone,
    calculate_price_zones,
)

TZ = ZoneInfo("Europe/Amsterdam")
DAY = date(2026, 8, 6)

# The fixed purchase-side floor every Frank all-in price carries.
TAX_FLOOR = 0.01815 + 0.11085


def all_in(market_price: float) -> float:
    """Return the all-in consumer price for a market price, as the client does."""
    tax = round(max(market_price, 0.0) * 0.21, 6)
    return round(market_price + tax + TAX_FLOOR, 6)


def day_blocks(prices: list[float], day: date = DAY) -> list[dict[str, Any]]:
    """Build one market day of quarter-hour blocks from all-in prices."""
    cursor = datetime(day.year, day.month, day.day, tzinfo=TZ).astimezone(timezone.utc)
    blocks: list[dict[str, Any]] = []
    for price in prices:
        nxt = cursor + timedelta(minutes=15)
        blocks.append(
            {
                "from": cursor.astimezone(TZ),
                "till": nxt.astimezone(TZ),
                "duration_minutes": 15,
                "total_price_eur_kwh": price,
            }
        )
        cursor = nxt
    return blocks


def sweep(low: float, high: float, count: int = 96) -> list[float]:
    """Return an all-in price curve sweeping low -> high -> low."""
    half = count // 2
    up = [low + (high - low) * i / (half - 1) for i in range(half)]
    return [all_in(p) for p in up + up[: count - half][::-1]]


def sweep_raw(low: float, high: float, count: int = 96) -> list[float]:
    """Return an all-in curve sweeping low -> high -> low, with no tax floor."""
    half = count // 2
    up = [low + (high - low) * i / (half - 1) for i in range(half)]
    return up + up[: count - half][::-1]


def spans_overlap(cheap: dict[str, Any], expensive: dict[str, Any]) -> bool:
    """Return whether the two selected windows share any instant."""
    return cheap["start"] < expensive["end"] and expensive["start"] < cheap["end"]


# --- Realistic day shapes ----------------------------------------------------
#
# All-in ranges taken from, or sized against, real measured Frank days.

REALISTIC_DAYS: dict[str, list[float]] = {
    # 2025-10-04, measured: all-in 0.13037-0.14943, a ratio of 1.146. Inside a
    # 15% absolute band -- this is the day that broke the old formula hardest.
    "measured_2025_10_04_very_flat": sweep(0.0009, 0.0166),
    # 2026-01-25, measured: all-in 0.24508-0.29698. Under the old formula this
    # produced a 67-quarter cheap zone and a 63-quarter expensive zone at once.
    "measured_2026_01_25_flat_winter": sweep(0.0960, 0.1386),
    # An ordinary winter day: high absolute prices, modest spread.
    "normal_winter": sweep(0.08, 0.16),
    # An ordinary summer day: solar-driven, wide spread.
    "normal_summer": sweep(0.02, 0.30),
    # A high but nearly flat day -- the worst case for an absolute-price margin.
    "high_price_flat": sweep(0.28, 0.30),
    # A very wide spread, as seen on scarcity days.
    "wide_spread": sweep(0.00, 0.55),
    # Negative market prices throughout (heavy solar, low demand).
    "all_negative": sweep(-0.09, -0.01),
    # Crossing zero, which is the common shape on a sunny spring day.
    "mixed_negative_positive": sweep(-0.05, 0.22),
}


@pytest.mark.parametrize("name", sorted(REALISTIC_DAYS))
@pytest.mark.parametrize("margin", [0.0, 1.0, 5.0, 15.0, 25.0, 49.0])
def test_zones_never_overlap_on_any_realistic_day(name, margin):
    """No realistic day and no valid margin may produce overlapping zones."""
    blocks = day_blocks(REALISTIC_DAYS[name])

    cheap, expensive = calculate_price_zones(blocks, margin, margin)

    assert cheap is not None, f"{name} @ {margin}% produced no cheap zone"
    assert expensive is not None
    assert cheap["threshold_eur_kwh"] < expensive["threshold_eur_kwh"], name
    assert not spans_overlap(cheap, expensive), (
        f"{name} @ {margin}%: cheap {cheap['quarter_count']}q overlaps "
        f"expensive {expensive['quarter_count']}q"
    )


@pytest.mark.parametrize("name", sorted(REALISTIC_DAYS))
def test_neither_zone_swallows_a_realistic_day(name):
    """Neither zone may cover the entire day at the default margin."""
    blocks = day_blocks(REALISTIC_DAYS[name])

    cheap, expensive = calculate_price_zones(blocks, 15.0, 15.0)

    assert cheap["quarter_count"] < len(blocks), f"{name}: cheap swallowed the day"
    assert expensive["quarter_count"] < len(blocks), f"{name}: expensive swallowed it"


@pytest.mark.parametrize("name", sorted(REALISTIC_DAYS))
def test_no_quarter_is_both_cheap_and_expensive(name):
    """No single quarter may satisfy both price bands."""
    prices = REALISTIC_DAYS[name]
    blocks = day_blocks(prices)

    cheap, expensive = calculate_price_zones(blocks, 15.0, 15.0)
    cheap_threshold = cheap["threshold_eur_kwh"]
    expensive_threshold = expensive["threshold_eur_kwh"]

    both = [p for p in prices if p <= cheap_threshold and p >= expensive_threshold]
    assert not both, f"{name}: {len(both)} quarter(s) qualify as cheap and expensive"


# --- The invariant across the whole supported margin space -------------------


@pytest.mark.parametrize("name", sorted(REALISTIC_DAYS))
def test_threshold_invariant_holds_for_every_margin_combination(name):
    """cheap_threshold < expensive_threshold for every valid margin pair.

    A deterministic sweep of the entire supported space rather than a sampled
    property test, so it needs no extra dependency and cannot flake: 50 x 50
    combinations of whole-percent margins on each realistic day.
    """
    blocks = day_blocks(REALISTIC_DAYS[name])
    margins = [
        float(m)
        for m in range(int(MIN_ZONE_MARGIN_PERCENT), int(MAX_ZONE_MARGIN_PERCENT) + 1)
    ]

    for cheap_margin in margins:
        for expensive_margin in margins:
            cheap, expensive = calculate_price_zones(
                blocks, cheap_margin, expensive_margin
            )
            assert cheap is not None and expensive is not None, (
                f"{name}: {cheap_margin}/{expensive_margin} produced no zone"
            )
            assert cheap["threshold_eur_kwh"] < expensive["threshold_eur_kwh"], (
                f"{name}: {cheap_margin}/{expensive_margin} thresholds crossed"
            )


def test_the_two_margins_can_be_maximal_together():
    """49% + 49% is still safe; that is why the cap is 49 and not 50."""
    blocks = day_blocks(REALISTIC_DAYS["high_price_flat"])

    cheap, expensive = calculate_price_zones(blocks, 49.0, 49.0)

    assert cheap["threshold_eur_kwh"] < expensive["threshold_eur_kwh"]
    assert not spans_overlap(cheap, expensive)


def test_margins_above_the_cap_are_clamped_not_honoured():
    """A stored 50/50 from an older pre-release build cannot reintroduce overlap."""
    blocks = day_blocks(REALISTIC_DAYS["high_price_flat"])

    cheap, expensive = calculate_price_zones(blocks, 50.0, 100.0)

    assert cheap["margin_percent"] == 49.0
    assert expensive["margin_percent"] == 49.0
    assert cheap["threshold_eur_kwh"] < expensive["threshold_eur_kwh"]
    assert not spans_overlap(cheap, expensive)


# --- Flat days ---------------------------------------------------------------


def test_a_flat_day_yields_neither_zone():
    """day_min == day_max means there is no cheap-vs-expensive distinction."""
    blocks = day_blocks([all_in(0.09)] * 96)

    cheap, expensive = calculate_price_zones(blocks, 15.0, 15.0)

    assert cheap is None
    assert expensive is None


def test_a_flat_day_yields_neither_zone_at_any_margin():
    """Flatness is not something a margin can rescue."""
    blocks = day_blocks([all_in(0.09)] * 96)

    for margin in (0.0, 15.0, 49.0):
        assert calculate_price_zones(blocks, margin, margin) == (None, None)


def test_a_single_cheap_quarter_is_enough_to_break_flatness():
    """One differing quarter gives a real spread, and both zones return."""
    prices = [all_in(0.09)] * 96
    prices[40] = all_in(0.05)
    blocks = day_blocks(prices)

    cheap, expensive = calculate_price_zones(blocks, 15.0, 15.0)

    assert cheap is not None and expensive is not None
    assert cheap["quarter_count"] == 1
    assert cheap["threshold_eur_kwh"] < expensive["threshold_eur_kwh"]


def test_zones_are_withheld_as_a_pair():
    """Never one zone without the other: the six entities move together."""
    flat = day_blocks([all_in(0.09)] * 96)
    assert calculate_price_zones(flat, 15.0, 15.0) == (None, None)
    assert calculate_price_zones(None, 15.0, 15.0) == (None, None)
    assert calculate_price_zones([], 15.0, 15.0) == (None, None)


def test_single_mode_helper_also_refuses_a_flat_day():
    """The single-zone entry point agrees with the paired one on flat days."""
    flat = day_blocks([all_in(0.09)] * 96)
    assert calculate_price_zone(flat, ZONE_MODE_CHEAP, 15.0) is None
    assert calculate_price_zone(flat, ZONE_MODE_EXPENSIVE, 15.0) is None


# --- The measured real-world days, spelled out -------------------------------


def test_measured_2025_10_04_no_longer_produces_contradictory_zones():
    """The worst measured day: all-in 0.13037-0.14943, ratio 1.146.

    Under the absolute-price formula both zones covered all 96 quarters and both
    period binary sensors read ``on`` for 24 hours.
    """
    blocks = day_blocks(REALISTIC_DAYS["measured_2025_10_04_very_flat"])
    totals = [b["total_price_eur_kwh"] for b in blocks]
    # The fixture really does reproduce the measured range.
    assert min(totals) == pytest.approx(0.1299, abs=0.002)
    assert max(totals) == pytest.approx(0.1495, abs=0.002)
    assert max(totals) / min(totals) == pytest.approx(1.15, abs=0.02)

    cheap, expensive = calculate_price_zones(blocks, 15.0, 15.0)

    assert cheap["quarter_count"] < 96
    assert expensive["quarter_count"] < 96
    assert not spans_overlap(cheap, expensive)


def test_measured_2026_01_25_no_longer_produces_contradictory_zones():
    """A flat winter day: all-in 0.24508-0.29698.

    Under the absolute-price formula this gave a 67-quarter cheap zone and a
    63-quarter expensive zone on the same 96-quarter day.
    """
    blocks = day_blocks(REALISTIC_DAYS["measured_2026_01_25_flat_winter"])
    totals = [b["total_price_eur_kwh"] for b in blocks]
    assert min(totals) == pytest.approx(0.245, abs=0.003)
    assert max(totals) == pytest.approx(0.297, abs=0.003)

    cheap, expensive = calculate_price_zones(blocks, 15.0, 15.0)

    assert cheap["quarter_count"] + expensive["quarter_count"] <= 96
    assert not spans_overlap(cheap, expensive)


def test_negative_market_prices_still_order_the_thresholds():
    """A day of negative *market* prices behaves normally.

    Note the all-in price stays positive even so: the Dutch energy tax and
    markup floor (~0.129 EUR/kWh) is larger than any realistic negative market
    price, so ``total_price_eur_kwh`` does not go negative in NL. The zones are
    derived from the all-in price, so this is the ordinary case, not an edge.
    """
    blocks = day_blocks(REALISTIC_DAYS["all_negative"])
    totals = [b["total_price_eur_kwh"] for b in blocks]
    assert min(totals) > 0, "the NL tax floor keeps the all-in price positive"

    cheap, expensive = calculate_price_zones(blocks, 15.0, 15.0)

    assert cheap["threshold_eur_kwh"] > cheap["day_min_price"]
    assert expensive["threshold_eur_kwh"] < expensive["day_max_price"]
    assert cheap["threshold_eur_kwh"] < expensive["threshold_eur_kwh"]
    assert not spans_overlap(cheap, expensive)


def test_genuinely_negative_all_in_prices_are_handled():
    """A day whose all-in totals are themselves negative still works.

    NL cannot currently produce this (the tax floor prevents it) and BE carries
    no energy tax, so the algorithm must not assume a positive price anywhere.
    The spread is what drives the thresholds, so nothing here is special-cased.
    """
    prices = [round(p, 6) for p in sweep_raw(-0.20, -0.04)]
    blocks = day_blocks(prices)
    assert max(prices) < 0

    cheap, expensive = calculate_price_zones(blocks, 15.0, 15.0)

    assert cheap["day_min_price"] < 0
    assert cheap["day_max_price"] < 0
    # spread = 0.16; cheap -0.20 + 0.024, expensive -0.04 - 0.024
    assert cheap["threshold_eur_kwh"] == pytest.approx(-0.176)
    assert expensive["threshold_eur_kwh"] == pytest.approx(-0.064)
    assert cheap["threshold_eur_kwh"] < expensive["threshold_eur_kwh"]
    assert not spans_overlap(cheap, expensive)


def test_zero_priced_day_is_flat_and_yields_no_zone():
    """An all-zero day is flat, so neither zone is published."""
    blocks = day_blocks([0.0] * 96)
    assert calculate_price_zones(blocks, 15.0, 15.0) == (None, None)
