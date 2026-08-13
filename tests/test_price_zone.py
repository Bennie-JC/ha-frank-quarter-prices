"""Unit tests for the daily cheap/expensive price-zone derivation.

The algorithm is pure and Home Assistant free, so everything here works on
plain block dicts. Two properties get the most attention because they are the
ones a naive implementation gets wrong:

* a zone is the **longest contiguous run** of qualifying quarters, never
  "first qualifying quarter until last qualifying quarter";
* contiguity is decided on the blocks' real timestamps, so the 92-quarter
  spring-forward day and the 100-quarter fall-back day behave correctly.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from custom_components.frank_quarter_prices.const import (
    DEFAULT_ZONE_MARGIN_PERCENT,
    ZONE_MODE_CHEAP,
    ZONE_MODE_EXPENSIVE,
)
from custom_components.frank_quarter_prices.price_zone import (
    calculate_price_zone,
    clamp_margin_percent,
    get_cheap_zone_margin_percent,
    get_expensive_zone_margin_percent,
    is_within_zone,
)

TZ = ZoneInfo("Europe/Amsterdam")

NORMAL_DAY = date(2026, 8, 6)  # 96 quarters
SPRING_FORWARD = date(2026, 3, 29)  # 23-hour local day ->  92 quarters
FALL_BACK = date(2026, 10, 25)  # 25-hour local day -> 100 quarters

# Prices used to shape a test day. BASE never qualifies at a sane margin; LOW
# and HIGH are the day's extremes.
BASE = 0.30
LOW = 0.10
HIGH = 0.60


def local_midnight(day: date) -> datetime:
    """Return local midnight for ``day`` as an aware datetime."""
    return datetime(day.year, day.month, day.day, tzinfo=TZ)


def day_blocks(
    day: date, prices: list[float], resolution_minutes: int = 15
) -> list[dict[str, Any]]:
    """Build the blocks covering one local calendar day.

    Steps through *absolute* time from local midnight to the next local
    midnight — exactly what the API returns — so the 23-hour and 25-hour days
    come out with 92 and 100 quarters rather than a naive 96.
    """
    cursor = local_midnight(day).astimezone(timezone.utc)
    end = local_midnight(day + timedelta(days=1)).astimezone(timezone.utc)
    step = timedelta(minutes=resolution_minutes)

    blocks: list[dict[str, Any]] = []
    index = 0
    while cursor < end:
        nxt = min(cursor + step, end)
        blocks.append(
            {
                "from": cursor.astimezone(TZ),
                "till": nxt.astimezone(TZ),
                "duration_minutes": int((nxt - cursor).total_seconds() // 60),
                "total_price_eur_kwh": prices[index % len(prices)],
            }
        )
        cursor = nxt
        index += 1
    return blocks


def quarter_count(day: date, resolution_minutes: int = 15) -> int:
    """Return how many blocks of the given resolution the local day holds.

    Both ends are converted to UTC first. Subtracting two datetimes that share
    one ``tzinfo`` object is a *naive* subtraction in Python, which would report
    24 hours for every day and hide the 23-hour and 25-hour DST days entirely.
    """
    span = local_midnight(day + timedelta(days=1)).astimezone(
        timezone.utc
    ) - local_midnight(day).astimezone(timezone.utc)
    return int(span.total_seconds() // 60 // resolution_minutes)


def flat_day(day: date, value: float, resolution_minutes: int = 15) -> list[float]:
    """Return a price list of ``value`` for every block of ``day``."""
    return [value] * quarter_count(day, resolution_minutes)


def at(zone: dict[str, Any], edge: str) -> str:
    """Return a zone boundary as a local ``HH:MM`` string."""
    return zone[edge].astimezone(TZ).strftime("%H:%M")


def cheap(prices: list[float], margin: float = DEFAULT_ZONE_MARGIN_PERCENT, **kwargs):
    """Derive the cheap zone for a day shaped by ``prices``."""
    day = kwargs.pop("day", NORMAL_DAY)
    return calculate_price_zone(
        day_blocks(day, prices, **kwargs), ZONE_MODE_CHEAP, margin
    )


def expensive(
    prices: list[float], margin: float = DEFAULT_ZONE_MARGIN_PERCENT, **kwargs
):
    """Derive the expensive zone for a day shaped by ``prices``."""
    day = kwargs.pop("day", NORMAL_DAY)
    return calculate_price_zone(
        day_blocks(day, prices, **kwargs), ZONE_MODE_EXPENSIVE, margin
    )


# --- Cheap zone: the headline case -----------------------------------------


def test_cheap_zone_is_the_longest_run_not_first_to_last():
    """A stray cheap quarter at 03:00 must not bridge into the 12:30 stretch.

    This is the exact failure the naive "first qualifying -> last qualifying"
    implementation produces: 03:00-15:15 instead of 12:30-15:15.
    """
    prices = flat_day(NORMAL_DAY, BASE)
    prices[12] = LOW  # 03:00-03:15, isolated
    for index in range(50, 61):  # 12:30 .. 15:15
        prices[index] = LOW

    zone = cheap(prices)

    assert (at(zone, "start"), at(zone, "end")) == ("12:30", "15:15")
    assert zone["quarter_count"] == 11
    assert zone["duration_minutes"] == 165


def test_cheap_threshold_and_reference_values():
    """The threshold is day_min plus a share of the day's own price range."""
    prices = flat_day(NORMAL_DAY, BASE)
    prices[50] = LOW

    zone = cheap(prices, margin=15.0)

    assert zone["day_min_price"] == LOW
    assert zone["day_max_price"] == BASE
    assert zone["day_reference_price"] == LOW
    assert zone["margin_percent"] == 15.0
    # spread = 0.30 - 0.10 = 0.20; 0.10 + 0.20 * 0.15
    assert zone["threshold_eur_kwh"] == pytest.approx(0.13)


@pytest.mark.parametrize(
    ("margin", "expected_quarters"),
    [
        (0.0, 1),  # threshold 0.10 -> only the day minimum itself
        (5.0, 2),  # threshold 0.11 -> also the 0.11 block
        (10.0, 3),  # threshold 0.12 -> also the 0.12 block
        (15.0, 4),  # threshold 0.13 -> also the 0.13 block
        (49.0, 4),  # threshold 0.198 -> still only the shaped run
    ],
)
def test_cheap_margin_widens_the_zone(margin, expected_quarters):
    """A larger configured margin admits more quarters into the zone.

    Day range 0.10-0.30, so a spread of 0.20 and a threshold of
    ``0.10 + 0.20 * margin``.
    """
    prices = flat_day(NORMAL_DAY, BASE)
    prices[40:44] = [0.10, 0.11, 0.12, 0.13]

    zone = cheap(prices, margin=margin)

    assert zone["quarter_count"] == expected_quarters
    assert at(zone, "start") == "10:00"


def test_cheap_zone_of_a_single_quarter():
    """One qualifying quarter is a valid 15-minute zone."""
    prices = flat_day(NORMAL_DAY, BASE)
    prices[60] = LOW

    zone = cheap(prices)

    assert (at(zone, "start"), at(zone, "end")) == ("15:00", "15:15")
    assert zone["quarter_count"] == 1
    assert zone["duration_minutes"] == 15


def test_cheap_zone_longest_of_two_separate_windows_wins():
    """Two disjoint qualifying windows resolve to the longer one."""
    prices = flat_day(NORMAL_DAY, BASE)
    for index in range(8, 11):  # 02:00-02:45, three quarters
        prices[index] = LOW
    for index in range(70, 75):  # 17:30-18:45, five quarters
        prices[index] = LOW

    zone = cheap(prices)

    assert (at(zone, "start"), at(zone, "end")) == ("17:30", "18:45")
    assert zone["quarter_count"] == 5


def test_cheap_zone_equal_length_windows_earliest_wins():
    """Two equally long windows resolve deterministically to the earlier one."""
    prices = flat_day(NORMAL_DAY, BASE)
    for index in range(8, 12):  # 02:00-03:00
        prices[index] = LOW
    for index in range(80, 84):  # 20:00-21:00, same length
        prices[index] = LOW

    zone = cheap(prices)

    assert (at(zone, "start"), at(zone, "end")) == ("02:00", "03:00")
    assert zone["quarter_count"] == 4


def test_cheap_zone_can_start_at_local_midnight():
    """A zone anchored at 00:00 is found, not skipped as a boundary case."""
    prices = flat_day(NORMAL_DAY, BASE)
    for index in range(6):  # 00:00-01:30
        prices[index] = LOW

    zone = cheap(prices)

    assert (at(zone, "start"), at(zone, "end")) == ("00:00", "01:30")
    assert zone["start"] == local_midnight(NORMAL_DAY)


def test_cheap_zone_can_end_at_local_midnight():
    """A zone running to the end of the day ends at the next local midnight."""
    prices = flat_day(NORMAL_DAY, BASE)
    for index in range(90, 96):  # 22:30-24:00
        prices[index] = LOW

    zone = cheap(prices)

    assert at(zone, "start") == "22:30"
    assert zone["end"] == local_midnight(NORMAL_DAY + timedelta(days=1))
    assert zone["duration_minutes"] == 90


# --- Cheap zone: awkward price shapes --------------------------------------


def test_cheap_zone_with_negative_cheapest_price():
    """A negative minimum needs no special-casing: the spread is still positive.

    Day range -0.20 to 0.30, so a spread of 0.50 and a 15% threshold of
    -0.20 + 0.075 = -0.125.
    """
    prices = flat_day(NORMAL_DAY, BASE)
    prices[40] = -0.20
    prices[41] = -0.18  # inside the threshold
    prices[42] = -0.05  # outside

    zone = cheap(prices, margin=15.0)

    assert zone["threshold_eur_kwh"] == pytest.approx(-0.125)
    assert zone["threshold_eur_kwh"] > zone["day_min_price"]
    assert (at(zone, "start"), at(zone, "end")) == ("10:00", "10:30")
    assert zone["quarter_count"] == 2


def test_cheap_zone_with_zero_cheapest_price():
    """A zero minimum still gets a real band, because the spread drives it.

    This is precisely what the old absolute-price formula got wrong: it
    multiplied the margin by ``abs(0.0)`` and collapsed the band to nothing.
    Day range 0.00-0.30 gives a 15% threshold of 0.045.
    """
    prices = flat_day(NORMAL_DAY, BASE)
    prices[40] = 0.0
    prices[41] = 0.0
    prices[42] = 0.001

    zone = cheap(prices, margin=15.0)

    assert zone["threshold_eur_kwh"] == pytest.approx(0.045)
    assert zone["quarter_count"] == 3
    assert (at(zone, "start"), at(zone, "end")) == ("10:00", "10:45")


def test_cheap_zone_when_all_prices_are_equal():
    """A perfectly flat day yields no zone at all.

    Every quarter is simultaneously the cheapest and the most expensive, so
    there is no cheap-versus-expensive distinction to draw. Publishing the whole
    day as both would be worse than publishing nothing.
    """
    assert cheap(flat_day(NORMAL_DAY, 0.25)) is None
    assert expensive(flat_day(NORMAL_DAY, 0.25)) is None


def test_cheap_zone_minimum_always_qualifies_at_zero_margin():
    """Rounding never pushes the day's own minimum out of its own zone."""
    prices = flat_day(NORMAL_DAY, 0.123456)
    prices[40] = 0.098765

    zone = cheap(prices, margin=0.0)

    assert zone["threshold_eur_kwh"] == 0.098765
    assert zone["quarter_count"] == 1


# --- Expensive zone: mirror image ------------------------------------------


def test_expensive_zone_is_the_longest_run_not_first_to_last():
    """A stray expensive quarter must not bridge into the real peak stretch."""
    prices = flat_day(NORMAL_DAY, BASE)
    prices[12] = HIGH  # 03:00, isolated
    for index in range(79, 82):  # 19:45 .. 20:30
        prices[index] = HIGH

    zone = expensive(prices)

    assert (at(zone, "start"), at(zone, "end")) == ("19:45", "20:30")
    assert zone["quarter_count"] == 3


def test_expensive_threshold_and_reference_values():
    """The threshold is day_max minus a share of the day's own price range."""
    prices = flat_day(NORMAL_DAY, BASE)
    prices[79] = HIGH

    zone = expensive(prices, margin=15.0)

    assert zone["day_reference_price"] == HIGH
    assert zone["day_max_price"] == HIGH
    # spread = 0.60 - 0.30 = 0.30; 0.60 - 0.30 * 0.15
    assert zone["threshold_eur_kwh"] == pytest.approx(0.555)


@pytest.mark.parametrize(
    ("margin", "expected_quarters"),
    [
        (0.0, 1),  # threshold 0.60 -> only the day maximum itself
        (5.0, 1),  # threshold 0.5725 -> still only the maximum
        (10.0, 2),  # threshold 0.545 -> also the 0.55 block
        (20.0, 3),  # threshold 0.49 -> also the 0.50 block
        (30.0, 4),  # threshold 0.435 -> also the 0.44 block
    ],
)
def test_expensive_margin_widens_the_zone(margin, expected_quarters):
    """A larger configured margin admits more quarters into the expensive zone.

    Day range 0.05-0.60, so a spread of 0.55 and a threshold of
    ``0.60 - 0.55 * margin``.
    """
    prices = flat_day(NORMAL_DAY, 0.05)
    prices[40:44] = [0.60, 0.55, 0.50, 0.44]

    zone = expensive(prices, margin=margin)

    assert at(zone, "start") == "10:00"
    assert zone["quarter_count"] == expected_quarters


def test_expensive_zone_equal_length_windows_earliest_wins():
    """The expensive zone uses the same earliest-wins tie-break."""
    prices = flat_day(NORMAL_DAY, BASE)
    for index in range(8, 12):
        prices[index] = HIGH
    for index in range(80, 84):
        prices[index] = HIGH

    zone = expensive(prices)

    assert (at(zone, "start"), at(zone, "end")) == ("02:00", "03:00")


def test_expensive_zone_with_all_negative_prices():
    """With every price negative the threshold still moves below the maximum.

    Day range -0.50 to -0.10, so a spread of 0.40 and a 15% threshold of
    -0.10 - 0.06 = -0.16.
    """
    prices = flat_day(NORMAL_DAY, -0.50)
    prices[40] = -0.10
    prices[41] = -0.11  # inside the threshold
    prices[42] = -0.20  # outside

    zone = expensive(prices, margin=15.0)

    assert zone["threshold_eur_kwh"] == pytest.approx(-0.16)
    assert zone["threshold_eur_kwh"] < zone["day_max_price"]
    assert zone["quarter_count"] == 2


def test_expensive_zone_when_all_prices_are_equal():
    """A flat day yields no expensive zone either."""
    assert expensive(flat_day(NORMAL_DAY, 0.25)) is None


# --- Missing / unusable data ------------------------------------------------


@pytest.mark.parametrize("prices", [None, [], "not a list"])
def test_no_zone_without_usable_data(prices):
    """No data means no zone, never a fabricated one."""
    assert calculate_price_zone(prices, ZONE_MODE_CHEAP, 15.0) is None
    assert calculate_price_zone(prices, ZONE_MODE_EXPENSIVE, 15.0) is None


def test_blocks_without_price_or_timestamps_are_skipped():
    """Malformed blocks are ignored rather than joining unrelated runs."""
    blocks = day_blocks(NORMAL_DAY, flat_day(NORMAL_DAY, BASE))
    blocks[40]["total_price_eur_kwh"] = LOW
    blocks[42]["total_price_eur_kwh"] = LOW
    # Block 41 is unusable, so 40 and 42 must not become one run.
    del blocks[41]["total_price_eur_kwh"]

    zone = calculate_price_zone(blocks, ZONE_MODE_CHEAP, 15.0)

    assert zone["quarter_count"] == 1
    assert at(zone, "start") == "10:00"


def test_partial_day_still_yields_a_zone_from_what_is_known():
    """A partial list derives a zone from the blocks it is handed.

    That is this layer's job. Deciding whether a list is a *complete local day*
    — and therefore whether a daily zone may be published at all — belongs to
    the coordinator, which gates on its own ``_complete_days`` set. See
    ``test_zone_incomplete_day.py``; the two must never both own that rule.
    """
    blocks = day_blocks(NORMAL_DAY, flat_day(NORMAL_DAY, BASE))[40:60]
    blocks[0]["total_price_eur_kwh"] = LOW
    blocks[1]["total_price_eur_kwh"] = LOW

    zone = calculate_price_zone(blocks, ZONE_MODE_CHEAP, 15.0)

    assert (at(zone, "start"), at(zone, "end")) == ("10:00", "10:30")


def test_a_gap_in_the_day_breaks_contiguity():
    """A missing block splits a run even though the list stays index-adjacent."""
    blocks = day_blocks(NORMAL_DAY, flat_day(NORMAL_DAY, BASE))
    for index in range(40, 46):
        blocks[index]["total_price_eur_kwh"] = LOW
    removed = blocks.pop(43)  # 10:45 disappears entirely
    assert removed["from"].astimezone(TZ).strftime("%H:%M") == "10:45"

    zone = calculate_price_zone(blocks, ZONE_MODE_CHEAP, 15.0)

    # 10:00-10:45 (three quarters) beats 11:00-11:30 (two quarters).
    assert (at(zone, "start"), at(zone, "end")) == ("10:00", "10:45")
    assert zone["quarter_count"] == 3


def test_unsorted_input_is_ordered_before_grouping():
    """Blocks arriving out of order still produce the correct run."""
    prices = flat_day(NORMAL_DAY, BASE)
    for index in range(40, 44):
        prices[index] = LOW
    blocks = day_blocks(NORMAL_DAY, prices)
    shuffled = blocks[48:] + blocks[:48]

    zone = calculate_price_zone(shuffled, ZONE_MODE_CHEAP, 15.0)

    assert (at(zone, "start"), at(zone, "end")) == ("10:00", "11:00")


def test_unknown_mode_is_rejected():
    """An unknown mode is a programming error, not a silent empty zone."""
    prices = flat_day(NORMAL_DAY, BASE)
    prices[40] = LOW  # a non-flat day, so the mode check is actually reached
    with pytest.raises(ValueError, match="Unknown price-zone mode"):
        calculate_price_zone(day_blocks(NORMAL_DAY, prices), "sideways", 15.0)


# --- Hourly fallback resolution ---------------------------------------------


def test_hourly_fallback_day_is_supported():
    """A 24-block hourly day derives a zone just like a quarter-hour day."""
    prices = flat_day(NORMAL_DAY, BASE, resolution_minutes=60)
    prices[10] = LOW
    prices[11] = LOW

    zone = cheap(prices, resolution_minutes=60)

    assert (at(zone, "start"), at(zone, "end")) == ("10:00", "12:00")
    assert zone["quarter_count"] == 2
    assert zone["duration_minutes"] == 120


# --- DST ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "expected_blocks"),
    [(SPRING_FORWARD, 92), (NORMAL_DAY, 96), (FALL_BACK, 100)],
)
def test_zone_can_span_almost_a_whole_dst_day(day, expected_blocks):
    """92-, 96- and 100-quarter days are all walked end to end.

    The day's own maximum can never fall inside the cheap band -- that is the
    point of the formula -- so the widest possible cheap zone is "everything
    except the peak". Here the peak is the final quarter, which makes the zone
    start at midnight and run to the last block, exercising the day-boundary
    arithmetic on all three day lengths.
    """
    assert quarter_count(day) == expected_blocks
    prices = flat_day(day, 0.25)
    prices[-1] = 0.26  # a single peak at the very end of the day

    zone = cheap(prices, margin=0.0, day=day)

    assert zone["quarter_count"] == expected_blocks - 1
    assert zone["start"] == local_midnight(day)
    assert zone["duration_minutes"] == (expected_blocks - 1) * 15
    # It ends exactly where the peak quarter begins.
    assert zone["end"] == day_blocks(day, prices)[-1]["from"]


@pytest.mark.parametrize(
    ("day", "expected_blocks"),
    [(SPRING_FORWARD, 92), (NORMAL_DAY, 96), (FALL_BACK, 100)],
)
def test_a_flat_dst_day_yields_no_zone(day, expected_blocks):
    """A flat day is flat whatever its length; no zone on any of the three."""
    assert quarter_count(day) == expected_blocks
    assert cheap(flat_day(day, 0.25), day=day) is None
    assert expensive(flat_day(day, 0.25), day=day) is None


def test_fall_back_repeated_hour_does_not_break_contiguity():
    """The twice-occurring 02:00-03:00 local hour stays one continuous run.

    Compared on local wall clock the repeated hour looks like a jump backwards
    and would split the run; compared on absolute instants it does not.
    """
    prices = flat_day(FALL_BACK, BASE)
    # Blocks 4..15 span 01:00 CEST through the repeated 02:00-03:00 hour.
    for index in range(4, 16):
        prices[index] = LOW

    zone = cheap(prices, day=FALL_BACK)

    assert zone["quarter_count"] == 12
    # Twelve quarters of real elapsed time, even though the local clock shows
    # only two hours of wall-clock movement.
    assert zone["duration_minutes"] == 180
    assert at(zone, "start") == "01:00"
    assert at(zone, "end") == "03:00"


def test_spring_forward_missing_hour_does_not_break_contiguity():
    """The skipped 02:00-03:00 local hour keeps the run continuous."""
    prices = flat_day(SPRING_FORWARD, BASE)
    for index in range(4, 12):  # 01:00 CET -> 04:00 CEST across the jump
        prices[index] = LOW

    zone = cheap(prices, day=SPRING_FORWARD)

    assert zone["quarter_count"] == 8
    assert zone["duration_minutes"] == 120
    assert at(zone, "start") == "01:00"
    assert at(zone, "end") == "04:00"


# --- Margin option resolution ------------------------------------------------


def test_margins_default_to_fifteen_percent():
    """An entry with no margin keys stored resolves to 15% for both zones."""
    for options in ({}, None, {"country": "NL"}):
        assert get_cheap_zone_margin_percent(options) == 15.0
        assert get_expensive_zone_margin_percent(options) == 15.0


def test_configured_margins_are_honoured():
    """Stored margins override the defaults independently."""
    options = {
        "cheap_zone_margin_percent": 20.0,
        "expensive_zone_margin_percent": 10.0,
    }
    assert get_cheap_zone_margin_percent(options) == 20.0
    assert get_expensive_zone_margin_percent(options) == 10.0


def test_invalid_margins_fall_back_to_the_default():
    """A non-numeric stored margin falls back rather than raising."""
    for value in ("abc", None, True, [15]):
        assert get_cheap_zone_margin_percent({"cheap_zone_margin_percent": value}) == (
            15.0
        )


def test_out_of_range_margins_are_clamped():
    """Values outside 0-49 are clamped, so a zone is always well defined.

    49 rather than 50 is what keeps the two bands disjoint by construction; a
    stored 50, 99 or 100 from an earlier pre-release build must not be able to
    reintroduce an overlap.
    """
    assert clamp_margin_percent(-10) == 0.0
    assert clamp_margin_percent(-100) == 0.0
    assert clamp_margin_percent(50) == 49.0
    assert clamp_margin_percent(250) == 49.0
    assert clamp_margin_percent(42) == 42.0
    assert get_cheap_zone_margin_percent({"cheap_zone_margin_percent": 500}) == 49.0
    assert get_expensive_zone_margin_percent({"expensive_zone_margin_percent": 99}) == (
        49.0
    )


def test_calculate_clamps_the_margin_it_publishes():
    """The margin published in the result is the clamped one actually applied."""
    prices = flat_day(NORMAL_DAY, BASE)
    prices[40] = LOW
    zone = cheap(prices, margin=999.0)
    assert zone["margin_percent"] == 49.0


# --- Zone membership ---------------------------------------------------------


def _zone(start_hhmm: str, end_hhmm: str) -> dict[str, Any]:
    """Build a minimal zone dict spanning two local times on the normal day."""
    base = local_midnight(NORMAL_DAY)
    start_h, start_m = (int(part) for part in start_hhmm.split(":"))
    end_h, end_m = (int(part) for part in end_hhmm.split(":"))
    return {
        "start": base + timedelta(hours=start_h, minutes=start_m),
        "end": base + timedelta(hours=end_h, minutes=end_m),
    }


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        ("12:29", False),  # just before
        ("12:30", True),  # exactly at the start -> inside
        ("13:00", True),  # inside
        ("15:14", True),  # last minute inside
        ("15:15", False),  # exactly at the end -> outside
        ("16:00", False),  # after
    ],
)
def test_zone_membership_boundaries(moment, expected):
    """The rule is start <= now < end: the zone ends at its till boundary."""
    hour, minute = (int(part) for part in moment.split(":"))
    now = local_midnight(NORMAL_DAY) + timedelta(hours=hour, minutes=minute)

    assert is_within_zone(_zone("12:30", "15:15"), now) is expected


def test_zone_membership_compares_absolute_instants():
    """A UTC "now" is compared correctly against a local zone."""
    zone = _zone("12:30", "15:15")
    inside_utc = (local_midnight(NORMAL_DAY) + timedelta(hours=13)).astimezone(
        timezone.utc
    )
    assert is_within_zone(zone, inside_utc) is True


@pytest.mark.parametrize("zone", [None, {}, {"start": "12:30", "end": "15:15"}])
def test_zone_membership_without_a_zone_is_unknown(zone):
    """Without a usable zone the answer is None, never a misleading False."""
    assert is_within_zone(zone, local_midnight(NORMAL_DAY)) is None


def test_zone_membership_rejects_a_naive_moment():
    """A naive datetime cannot be compared safely and yields None."""
    naive = datetime(2026, 8, 6, 13)  # noqa: DTZ001 - naive on purpose
    assert is_within_zone(_zone("12:30", "15:15"), naive) is None


# --- Realistic-day sanity: the two zones must not contradict each other ------
#
# These use REAL Frank all-in price shapes. The all-in price is
# ``market_price * 1.21 + sourcing_markup + energy_tax``, so it carries a fixed
# floor of about EUR 0.129/kWh that does not vary with the market at all.
#
# A margin applied to the *absolute* all-in price is a band whose width is
# driven by that floor rather than by the day's actual spread, and on a flat
# winter day it exceeds the whole spread. Measured over a year of real Frank
# data that produced contradictory zones on 33 of 317 days at the default 15%
# margin, and on 90 of 317 at 25% -- including 2025-10-04, whose all-in prices
# ran 0.13037 to 0.14943 (a ratio of 1.146, inside a 15% band) and which was
# reported as entirely cheap *and* entirely expensive for 24 hours.
#
# Making the margin a share of the day's own spread removes the failure mode by
# construction. The two tests below are the regressions for it.

_TAX_FLOOR = 0.01815 + 0.11085  # sourcing markup + energy tax, both fixed


def all_in(market_price: float) -> float:
    """Return the all-in consumer price for a market price, as the client does."""
    tax = round(max(market_price, 0.0) * 0.21, 6)
    return round(market_price + tax + _TAX_FLOOR, 6)


def realistic_day(low_market: float, high_market: float) -> list[float]:
    """Return a 96-quarter day whose price sweeps low -> high -> low."""
    half = 48
    up = [low_market + (high_market - low_market) * i / (half - 1) for i in range(half)]
    return [all_in(p) for p in up + up[::-1]]


def zones_overlap(cheap, expensive) -> bool:
    """Return whether the two zones share any instant."""
    return cheap["start"] < expensive["end"] and expensive["start"] < cheap["end"]


def test_cheap_and_expensive_zones_never_overlap_on_a_flat_day():
    """A flat but real day must not be both entirely cheap and entirely expensive.

    Reproduces 2025-10-04 (all-in 0.13037-0.14943). Whatever the margin, a
    quarter cannot honestly be reported as both the cheap and the expensive part
    of the same day.
    """
    prices = realistic_day(0.0009, 0.0166)  # -> all-in ~0.1299 .. 0.1495
    blocks = day_blocks(NORMAL_DAY, prices)

    cheap = calculate_price_zone(blocks, ZONE_MODE_CHEAP, 15.0)
    expensive = calculate_price_zone(blocks, ZONE_MODE_EXPENSIVE, 15.0)

    assert not zones_overlap(cheap, expensive), (
        f"cheap {at(cheap, 'start')}-{at(cheap, 'end')} "
        f"({cheap['quarter_count']}q) overlaps expensive "
        f"{at(expensive, 'start')}-{at(expensive, 'end')} "
        f"({expensive['quarter_count']}q)"
    )


def test_neither_zone_swallows_a_whole_realistic_day():
    """Neither zone may cover all 96 quarters of a day that has a real spread."""
    prices = realistic_day(0.05, 0.09)  # a calm winter day
    blocks = day_blocks(NORMAL_DAY, prices)

    cheap = calculate_price_zone(blocks, ZONE_MODE_CHEAP, 25.0)
    expensive = calculate_price_zone(blocks, ZONE_MODE_EXPENSIVE, 25.0)

    assert cheap["quarter_count"] < 96, "cheap zone swallowed the entire day"
    assert expensive["quarter_count"] < 96, "expensive zone swallowed the entire day"


def test_zones_are_disjoint_on_a_day_with_a_wide_spread():
    """On a high-spread summer day the current formula does behave correctly.

    Kept alongside the two xfail cases above so the contrast is explicit: the
    bug is specific to flat days, which is why it survived the original suite.
    """
    prices = realistic_day(0.02, 0.35)  # a typical summer day
    blocks = day_blocks(NORMAL_DAY, prices)

    cheap = calculate_price_zone(blocks, ZONE_MODE_CHEAP, 15.0)
    expensive = calculate_price_zone(blocks, ZONE_MODE_EXPENSIVE, 15.0)

    assert not zones_overlap(cheap, expensive)
    assert cheap["quarter_count"] < 96
    assert expensive["quarter_count"] < 96


# --- The repeated hour of the fall-back day ---------------------------------
#
# CPython short-circuits ``<`` between two aware datetimes that share the *same*
# ``tzinfo`` object to a naive wall-clock comparison that ignores ``fold``, and
# ``ZoneInfo`` is cached per key -- so a zone boundary built from a price block
# and a ``dt_util.now()`` probe always share one object. On the fall-back day
# 02:00-03:00 runs twice and the two passes then compare *equal*, which made the
# period sensors switch an hour early and flap on/off/on. ``is_within_zone``
# therefore converts to UTC before comparing.


def _fold_zone(start_fold: int, end_hour: int = 4) -> dict[str, Any]:
    """Return a zone starting 02:30 in the given fold of the fall-back day."""
    return {
        "start": datetime(2026, 10, 25, 2, 30, tzinfo=TZ, fold=start_fold),
        "end": datetime(2026, 10, 25, end_hour, 0, tzinfo=TZ),
    }


def test_membership_distinguishes_the_two_passes_of_the_repeated_hour():
    """02:30 CEST and 02:30 CET are an hour apart and must not compare equal."""
    zone = _fold_zone(start_fold=1)  # starts 02:30 CET, the *second* pass
    first_pass = datetime(2026, 10, 25, 2, 30, tzinfo=TZ, fold=0)  # 00:30 UTC
    second_pass = datetime(2026, 10, 25, 2, 30, tzinfo=TZ, fold=1)  # 01:30 UTC

    # The first pass is a real hour *before* the zone opens.
    assert first_pass.astimezone(timezone.utc) < zone["start"].astimezone(timezone.utc)
    assert is_within_zone(zone, first_pass) is False
    # The second pass is exactly the zone's start boundary.
    assert is_within_zone(zone, second_pass) is True


def test_membership_does_not_reopen_a_zone_in_the_second_pass():
    """A zone that ended in the first pass must not switch back on an hour later."""
    zone = {
        "start": datetime(2026, 10, 25, 1, 0, tzinfo=TZ),
        "end": datetime(2026, 10, 25, 2, 30, tzinfo=TZ, fold=0),  # 00:30 UTC
    }
    still_inside = datetime(2026, 10, 25, 2, 15, tzinfo=TZ, fold=0)
    after_in_second_pass = datetime(2026, 10, 25, 2, 15, tzinfo=TZ, fold=1)

    assert is_within_zone(zone, still_inside) is True
    # An hour of real time later the zone stays closed -- no on/off/on flap.
    assert is_within_zone(zone, after_in_second_pass) is False


def test_membership_is_stable_whichever_zone_object_is_used():
    """The comparison is on instants, so an equivalent UTC probe agrees."""
    zone = _fold_zone(start_fold=1)
    for fold in (0, 1):
        probe = datetime(2026, 10, 25, 2, 45, tzinfo=TZ, fold=fold)
        as_utc = probe.astimezone(timezone.utc)
        assert is_within_zone(zone, probe) == is_within_zone(zone, as_utc)
