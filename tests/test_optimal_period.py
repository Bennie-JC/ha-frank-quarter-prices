"""The optimal-period algorithm itself, tested in isolation.

``optimal_period.py`` is deliberately free of Home Assistant imports, so every
property of the selection can be pinned down here on plain lists of blocks,
without a coordinator, a config entry or an event loop in the way. The entity
behaviour built on top of it lives in ``test_optimal_period_entities.py``.

Three properties carry the whole feature and each gets its own group below:

* the window is **exactly** the requested duration and truly contiguous — never
  a near miss, never two unrelated stretches concatenated;
* the winner is chosen on the **duration-weighted average**, with prices used
  exactly as published (negatives included, never clamped, never made absolute);
* ties resolve to the **earliest** window, deterministically, for both modes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from custom_components.frank_quarter_prices.const import (
    CONF_OPTIMAL_CHEAP_DURATION_MINUTES,
    CONF_OPTIMAL_CHEAP_ENABLED,
    CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES,
    CONF_OPTIMAL_EXPENSIVE_ENABLED,
    DEFAULT_OPTIMAL_DURATION_MINUTES,
    MAX_OPTIMAL_DURATION_MINUTES,
    MIN_OPTIMAL_DURATION_MINUTES,
    OPTIMAL_MODE_CHEAP,
    OPTIMAL_MODE_EXPENSIVE,
)
from custom_components.frank_quarter_prices.optimal_period import (
    calculate_optimal_period,
    get_optimal_cheap_duration_minutes,
    get_optimal_cheap_enabled,
    get_optimal_expensive_duration_minutes,
    get_optimal_expensive_enabled,
    is_within_period,
    validate_duration_minutes,
)

NL_TZ = ZoneInfo("Europe/Amsterdam")

DAY = date(2026, 8, 6)
SPRING_FORWARD = date(2026, 3, 29)  # 23-hour day ->  92 quarters
FALL_BACK = date(2026, 10, 25)  # 25-hour day -> 100 quarters


# --- Builders ---------------------------------------------------------------


def block(start: datetime, minutes: int, total: float) -> dict[str, Any]:
    """Return a minimal price block with an explicit total price.

    Only the four keys the algorithm reads are set. ``duration_minutes`` is
    deliberately *not* trusted by the algorithm — the elapsed time between
    ``from`` and ``till`` is — but it is filled in anyway so the fixtures look
    like the real client output.
    """
    till = start + timedelta(minutes=minutes)
    return {
        "from": start,
        "till": till,
        "duration_minutes": minutes,
        "total_price_eur_kwh": total,
    }


def day_from(prices: list[float], resolution: int = 15, day: date = DAY):
    """Return a contiguous run of blocks starting at local midnight on ``day``."""
    start = datetime(day.year, day.month, day.day, tzinfo=NL_TZ)
    blocks = []
    for price in prices:
        blocks.append(block(start, resolution, price))
        start = blocks[-1]["till"]
    return blocks


def real_day(prices_by_index, day: date, resolution: int = 15):
    """Return a full market day stepped through *absolute* time.

    Naive ``midnight + i * 15min`` arithmetic silently produces 96 blocks on
    every day of the year; stepping through UTC is what makes the 92-block
    spring-forward day and the 100-block fall-back day come out right.
    """
    from datetime import timezone

    start = datetime(day.year, day.month, day.day, tzinfo=NL_TZ).astimezone(
        timezone.utc
    )
    end = (
        datetime(day.year, day.month, day.day, tzinfo=NL_TZ) + timedelta(days=1)
    ).astimezone(timezone.utc)

    blocks = []
    index = 0
    while start < end:
        nxt = min(start + timedelta(minutes=resolution), end)
        blocks.append(
            {
                "from": start.astimezone(NL_TZ),
                "till": nxt.astimezone(NL_TZ),
                "duration_minutes": int((nxt - start).total_seconds() // 60),
                "total_price_eur_kwh": prices_by_index(index),
            }
        )
        start = nxt
        index += 1
    return blocks


def window(period: dict[str, Any]) -> tuple[str, str]:
    """Return the period's local ``HH:MM`` start and end, for readable asserts."""
    return (f"{period['start']:%H:%M}", f"{period['end']:%H:%M}")


def elapsed(period: dict[str, Any]) -> timedelta:
    """Return the period's real elapsed length.

    Converting to UTC first is not decoration. Subtracting two aware datetimes
    that share the same ``tzinfo`` object gives the *naive wall-clock* delta,
    which is off by an hour in both directions across a daylight-saving
    transition — exactly the trap the algorithm avoids, and one this test file
    would otherwise fall into while claiming to check it.
    """
    utc = ZoneInfo("UTC")
    return period["end"].astimezone(utc) - period["start"].astimezone(utc)


def cheap(prices, duration):
    """Shorthand for the cheap-mode derivation."""
    return calculate_optimal_period(prices, duration, OPTIMAL_MODE_CHEAP)


def expensive(prices, duration):
    """Shorthand for the expensive-mode derivation."""
    return calculate_optimal_period(prices, duration, OPTIMAL_MODE_EXPENSIVE)


# --- Option resolution ------------------------------------------------------


def test_features_are_off_when_the_options_are_absent():
    """An entry from before the feature gains nothing without being asked."""
    assert get_optimal_cheap_enabled({}) is False
    assert get_optimal_expensive_enabled({}) is False
    assert get_optimal_cheap_enabled(None) is False
    assert get_optimal_expensive_enabled(None) is False


def test_durations_default_when_the_options_are_absent():
    """A missing duration resolves to the documented 120-minute default."""
    assert get_optimal_cheap_duration_minutes({}) == DEFAULT_OPTIMAL_DURATION_MINUTES
    assert get_optimal_expensive_duration_minutes({}) == (
        DEFAULT_OPTIMAL_DURATION_MINUTES
    )


def test_stored_options_are_read_independently():
    """Cheap and expensive have their own toggle and their own duration."""
    options = {
        CONF_OPTIMAL_CHEAP_ENABLED: True,
        CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 180,
        CONF_OPTIMAL_EXPENSIVE_ENABLED: False,
        CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES: 60,
    }
    assert get_optimal_cheap_enabled(options) is True
    assert get_optimal_expensive_enabled(options) is False
    assert get_optimal_cheap_duration_minutes(options) == 180
    assert get_optimal_expensive_duration_minutes(options) == 60


@pytest.mark.parametrize("value", [15, 30, 45, 60, 90, 120, 180, 240, 360, 705, 720])
def test_every_value_the_form_can_produce_is_valid(value):
    """The whole supported range, used exactly — never rounded, never clamped."""
    assert validate_duration_minutes(value) == value


@pytest.mark.parametrize(
    "value",
    [
        None,  # not a number
        "120",  # a string, even a plausible one
        "abc",
        True,  # a bool is an int in Python, but never a duration
        [],
        0,  # zero is not a period
        -15,  # negative
        -500,
        10,  # below the minimum
        14,
        17,  # in range, but off the 15-minute step
        22.5,  # fractional
        90.5,
        721,  # above the maximum
        1000,
        9999,
        float("nan"),
        float("inf"),
    ],
)
def test_an_unusable_stored_duration_is_rejected_not_repaired(value):
    """Invalid means invalid: not clamped, not rounded, and NOT defaulted.

    Falling back to 120 here would silently run an automation planner on a
    duration the user never chose and cannot see. ``None`` is the signal that
    the configuration is unusable, which the entities surface as unavailable.
    """
    assert validate_duration_minutes(value) is None


def test_a_whole_float_is_accepted_as_that_many_minutes():
    """The number selector hands back floats; 120.0 is 120 minutes."""
    assert validate_duration_minutes(120.0) == 120
    assert isinstance(validate_duration_minutes(120.0), int)


def test_a_missing_key_defaults_but_an_invalid_one_does_not():
    """The one distinction that matters: absent is not the same as corrupt.

    An entry from before this feature existed has no key at all and must keep
    working on the documented default. A key that is present but unusable is a
    different situation and must not be silently replaced by that same default.
    """
    assert get_optimal_cheap_duration_minutes({}) == DEFAULT_OPTIMAL_DURATION_MINUTES
    assert get_optimal_expensive_duration_minutes({}) == (
        DEFAULT_OPTIMAL_DURATION_MINUTES
    )

    assert (
        get_optimal_cheap_duration_minutes({CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 0})
        is None
    )
    assert (
        get_optimal_expensive_duration_minutes(
            {CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES: -15}
        )
        is None
    )


# --- Exact duration ---------------------------------------------------------


@pytest.mark.parametrize(
    ("duration", "expected_blocks"),
    [(15, 1), (30, 2), (60, 4), (120, 8), (240, 16), (720, 48)],
)
def test_every_documented_duration_selects_exactly_that_much_time(
    duration, expected_blocks
):
    """15 up to the 720-minute maximum: the window is exactly that long."""
    prices = real_day(lambda i: 0.10 + i * 0.001, DAY)

    for period in (cheap(prices, duration), expensive(prices, duration)):
        assert period is not None, duration
        assert period["duration_minutes"] == duration
        assert period["block_count"] == expected_blocks
        # And the timestamps agree with the reported duration.
        elapsed = (period["end"] - period["start"]).total_seconds() / 60
        assert elapsed == duration


@pytest.mark.parametrize("duration", [MIN_OPTIMAL_DURATION_MINUTES, 105, 375])
def test_a_105_minute_window_is_never_returned_for_120(duration):
    """No near miss: the answer is the exact duration or nothing at all."""
    prices = real_day(lambda i: 0.10 + (i % 7) * 0.01, DAY)
    period = cheap(prices, duration)
    assert period["duration_minutes"] == duration


def test_a_duration_longer_than_the_day_yields_nothing():
    """25 hours does not fit in a 24-hour day, so there is no period."""
    prices = real_day(lambda i: 0.10, DAY)
    assert cheap(prices, 25 * 60) is None
    assert expensive(prices, 25 * 60) is None


def test_a_duration_equal_to_the_whole_day_is_the_whole_day():
    """The degenerate upper bound still returns an exact, contiguous window."""
    prices = real_day(lambda i: 0.10 + i * 0.001, DAY)
    period = cheap(prices, 24 * 60)
    assert period is not None
    assert period["block_count"] == 96
    assert window(period) == ("00:00", "00:00")


def test_an_empty_or_unusable_day_yields_nothing():
    """Nothing to search means no period, never a fabricated one."""
    assert cheap([], 60) is None
    assert cheap(None, 60) is None
    assert expensive([{"from": None, "till": None}], 60) is None


@pytest.mark.parametrize("duration", [0, -60])
def test_a_non_positive_duration_yields_nothing(duration):
    """A zero or negative duration is not a window."""
    prices = real_day(lambda i: 0.10, DAY)
    assert cheap(prices, duration) is None
    assert expensive(prices, duration) is None


def test_an_unknown_mode_is_a_programming_error():
    """A typo'd mode fails loudly rather than silently returning a cheap window."""
    with pytest.raises(ValueError, match="Unknown optimal-period mode"):
        calculate_optimal_period(real_day(lambda i: 0.1, DAY), 60, "cheapest")


# --- Where the window lands -------------------------------------------------


def test_the_cheapest_window_at_the_start_of_the_day_is_found():
    """A dip in the first hour is selected, edge of the list included."""
    prices = [0.01] * 4 + [0.30] * 92
    period = cheap(day_from(prices), 60)
    assert window(period) == ("00:00", "01:00")


def test_the_cheapest_window_at_the_end_of_the_day_is_found():
    """A dip in the last hour is selected, edge of the list included."""
    prices = [0.30] * 92 + [0.01] * 4
    period = cheap(day_from(prices), 60)
    assert window(period) == ("23:00", "00:00")


def test_the_cheapest_window_in_the_middle_is_found():
    """The ordinary case: a midday solar dip."""
    prices = [0.30] * 96
    for index in range(44, 52):  # 11:00 .. 13:00
        prices[index] = 0.01
    period = cheap(day_from(prices), 120)
    assert window(period) == ("11:00", "13:00")


def test_the_most_expensive_window_is_the_evening_peak():
    """Expensive mode picks the highest average, not the lowest."""
    prices = [0.10] * 96
    for index in range(72, 80):  # 18:00 .. 20:00
        prices[index] = 0.45
    period = expensive(day_from(prices), 120)
    assert window(period) == ("18:00", "20:00")


def test_cheap_and_expensive_pick_opposite_ends_of_the_same_day():
    """One day, two modes, two genuinely different answers."""
    prices = [0.10] * 96
    for index in range(44, 52):
        prices[index] = 0.01
    for index in range(72, 80):
        prices[index] = 0.45
    day = day_from(prices)

    assert window(cheap(day, 120)) == ("11:00", "13:00")
    assert window(expensive(day, 120)) == ("18:00", "20:00")
    assert (
        cheap(day, 120)["average_price_eur_kwh"]
        < (expensive(day, 120)["average_price_eur_kwh"])
    )


def test_the_best_window_may_straddle_a_cheap_run_and_its_neighbours():
    """The window is not "the cheapest blocks"; it is the cheapest *window*.

    Only three quarters are rock bottom, so a 60-minute window has to take a
    fourth quarter with it — and the cheapest available neighbour is the one it
    should take, even though that neighbour is not itself among the cheapest
    blocks of the day.
    """
    prices = [0.30] * 96
    prices[40] = 0.20  # 10:00 -- the cheaper neighbour, before the run
    prices[41] = prices[42] = prices[43] = 0.01  # 10:15 .. 11:00
    prices[44] = 0.25  # 11:00 -- the dearer neighbour, after the run
    period = cheap(day_from(prices), 60)
    assert window(period) == ("10:00", "11:00")


# --- Contiguity -------------------------------------------------------------


def test_a_gap_cannot_be_bridged():
    """Two cheap stretches either side of a hole are not one cheap window.

    The cheapest blocks of the day are 02:00-02:30 and 03:00-03:30, but the
    30 minutes between them are missing entirely, so those four quarters can
    never form a 60-minute window.
    """
    prices = [0.30] * 96
    prices[8] = prices[9] = 0.01  # 02:00 .. 02:30
    prices[12] = prices[13] = 0.01  # 03:00 .. 03:30
    day = day_from(prices)
    del day[10:12]  # the 02:30 .. 03:00 blocks disappear

    period = cheap(day, 60)
    assert period is not None
    # Not the impossible 02:00-03:30 concatenation, and not 30 minutes of it.
    assert period["duration_minutes"] == 60
    assert period["start"] != day[8]["from"] or period["end"] == day[11]["till"]
    assert (period["end"] - period["start"]) == timedelta(minutes=60)


def test_a_window_never_spans_a_hole_however_cheap_both_sides_are():
    """With the whole day expensive except the two sides of a gap, none wins."""
    prices = [0.01] * 96
    day = day_from(prices)
    del day[10:12]

    period = cheap(day, 60)
    # A 60-minute window still exists elsewhere in the day, and whichever one
    # is chosen must be four blocks that really touch each other.
    assert period["block_count"] == 4
    assert (period["end"] - period["start"]) == timedelta(minutes=60)


def test_an_expensive_quarter_inside_a_cheap_stretch_is_not_skipped():
    """The window is contiguous, so a spike inside it counts against it.

    The four cheapest quarters of the day are 05:00, 05:15, 05:45 and 06:00,
    but 05:30 between them is the most expensive quarter of the day. A window
    that skipped it would win on price and be a lie.
    """
    prices = [0.20] * 96
    for index in (20, 21, 23, 24):
        prices[index] = 0.01
    prices[22] = 0.90  # 05:30

    period = cheap(day_from(prices), 60)
    assert period["max_price_eur_kwh"] < 0.90
    assert window(period) != ("05:00", "06:00")


def test_only_the_blocks_of_one_contiguous_segment_can_form_a_window():
    """A day arriving in two pieces yields a window inside one piece only."""
    prices = [0.10] * 96
    day = day_from(prices)
    del day[40:44]  # a full hour missing at 10:00

    period = cheap(day, 240)
    assert period is not None
    assert period["block_count"] == 16
    # The window lies wholly before or wholly after the hole.
    assert period["end"] <= day[39]["till"] or period["start"] >= day[40]["from"]


def test_an_overlap_breaks_the_chain_like_a_gap_does():
    """Two blocks claiming the same minutes cannot both be inside one window."""
    prices = [0.10] * 96
    day = day_from(prices)
    # Stretch 10:00 to run until 10:30, overlapping the 10:15 block.
    day[40] = block(day[40]["from"], 30, 0.10)

    period = cheap(day, 24 * 60)
    # The day no longer covers 24 contiguous hours anywhere.
    assert period is None


# --- Weighted average -------------------------------------------------------


def test_the_average_is_the_plain_mean_for_equal_blocks():
    """On the ordinary quarter-hour day the weighting is a no-op."""
    prices = [0.90] * 96
    prices[40] = 0.10
    prices[41] = 0.20
    prices[42] = 0.30
    prices[43] = 0.40

    period = cheap(day_from(prices), 60)
    assert window(period) == ("10:00", "11:00")
    assert period["average_price_eur_kwh"] == pytest.approx(0.25)


def test_a_longer_block_weighs_proportionally_more():
    """A 60-minute block counts four times a 15-minute one, not once.

    Two candidate 90-minute windows, separated by a gap so nothing can straddle
    them. The first is a 60-minute block at 0.40 plus two quarters at 0.10; the
    second is six quarters at 0.25. Counting each block once — the naive mean —
    scores the first at 0.20 and would pick it. Weighting by duration scores it
    at (0.40*60 + 0.10*15 + 0.10*15) / 90 = 0.30, so the flat window correctly
    wins instead.
    """
    start = datetime(2026, 8, 6, tzinfo=NL_TZ)
    mixed = [
        block(start, 60, 0.40),
        block(start + timedelta(minutes=60), 15, 0.10),
        block(start + timedelta(minutes=75), 15, 0.10),
    ]
    # A one-hour hole, so the only candidates are the two groups themselves.
    cursor = start + timedelta(minutes=150)
    flat = []
    for _ in range(6):
        flat.append(block(cursor, 15, 0.25))
        cursor = flat[-1]["till"]

    period = cheap(mixed + flat, 90)
    assert period["average_price_eur_kwh"] == pytest.approx(0.25)
    assert period["start"] == flat[0]["from"]
    assert period["block_count"] == 6

    # And the weighted score the losing window really was judged on.
    assert expensive(mixed + flat, 90)["average_price_eur_kwh"] == pytest.approx(0.30)


def test_the_reported_min_and_max_come_from_the_window_not_the_day():
    """The extremes describe the selected window alone."""
    prices = [0.90] * 96
    prices[40] = 0.10
    prices[41] = 0.12
    prices[42] = 0.14
    prices[43] = 0.16

    period = cheap(day_from(prices), 60)
    assert period["min_price_eur_kwh"] == pytest.approx(0.10)
    assert period["max_price_eur_kwh"] == pytest.approx(0.16)
    assert period["average_price_eur_kwh"] == pytest.approx(0.13)


def test_the_resolution_of_the_window_is_reported():
    """A quarter-hour window reports 15; an hourly one reports 60."""
    quarters = real_day(lambda i: 0.10, DAY)
    hours = real_day(lambda i: 0.10, DAY, resolution=60)

    assert cheap(quarters, 60)["resolution_minutes"] == 15
    assert cheap(hours, 60)["resolution_minutes"] == 60


# --- Tie-breaking -----------------------------------------------------------


def test_equal_averages_resolve_to_the_earliest_window_when_cheap():
    """Two identical dips: the first one wins."""
    prices = [0.30] * 96
    for index in (20, 21, 22, 23):  # 05:00 .. 06:00
        prices[index] = 0.01
    for index in (60, 61, 62, 63):  # 15:00 .. 16:00
        prices[index] = 0.01

    assert window(cheap(day_from(prices), 60)) == ("05:00", "06:00")


def test_equal_averages_resolve_to_the_earliest_window_when_expensive():
    """The same rule, deliberately not mirrored to "latest"."""
    prices = [0.10] * 96
    for index in (20, 21, 22, 23):
        prices[index] = 0.90
    for index in (60, 61, 62, 63):
        prices[index] = 0.90

    assert window(expensive(day_from(prices), 60)) == ("05:00", "06:00")


def test_a_flat_day_yields_the_earliest_window_for_both_modes():
    """Unlike a price *zone*, an optimal period is meaningful on a flat day.

    A zone needs a cheap-versus-expensive distinction and a flat day has none,
    so v0.1.6 withholds both zones. A fixed-duration window needs no such
    distinction: every candidate ties, and the documented tie-break answers.
    """
    flat = real_day(lambda i: 0.2345, DAY)

    for period in (cheap(flat, 120), expensive(flat, 120)):
        assert period is not None
        assert window(period) == ("00:00", "02:00")
        assert period["average_price_eur_kwh"] == pytest.approx(0.2345)
        assert period["min_price_eur_kwh"] == period["max_price_eur_kwh"]


@pytest.mark.parametrize("duration", [15, 120, 480, 720])
def test_float_drift_cannot_decide_a_tie_on_a_long_window(duration):
    """A 12-hour window slides its sum across 49 positions and still ties.

    The sliding window adds and subtracts each block once, so the running
    weighted sum accumulates a little floating-point noise as it moves. Rounding
    the average to six decimals before comparing is what keeps that noise from
    quietly overriding the documented earliest-wins rule on a flat day.
    """
    flat = real_day(lambda i: 0.213456, DAY)

    for period in (cheap(flat, duration), expensive(flat, duration)):
        assert window(period)[0] == "00:00", duration
        assert period["average_price_eur_kwh"] == 0.213456


def test_the_tie_break_is_stable_across_repeated_derivations():
    """The same day and duration always produce the identical window."""
    flat = real_day(lambda i: 0.10, DAY)
    results = {window(cheap(flat, 180)) for _ in range(20)}
    assert len(results) == 1


# --- Negative prices --------------------------------------------------------


def test_the_cheap_window_prefers_the_most_negative_average():
    """Negative prices are low prices; they are not clamped to zero."""
    prices = [0.10] * 96
    for index in (44, 45, 46, 47):  # 11:00 .. 12:00
        prices[index] = -0.08
    for index in (48, 49, 50, 51):  # 12:00 .. 13:00, negative but less so
        prices[index] = -0.02

    period = cheap(day_from(prices), 60)
    assert window(period) == ("11:00", "12:00")
    assert period["average_price_eur_kwh"] == pytest.approx(-0.08)


def test_the_expensive_window_on_an_all_negative_day_is_the_least_negative():
    """Highest average still means highest, even when every price is below zero."""
    prices = [-0.20] * 96
    for index in (72, 73, 74, 75):  # 18:00 .. 19:00
        prices[index] = -0.01

    period = expensive(day_from(prices), 60)
    assert window(period) == ("18:00", "19:00")
    assert period["average_price_eur_kwh"] == pytest.approx(-0.01)


def test_absolute_values_are_never_used():
    """-0.30 must read as cheaper than 0.05, not as more extreme than it.

    Taking the absolute price would make the -0.30 stretch look like the most
    *expensive* hour of the day, which is the exact inversion this pins down.
    """
    prices = [0.05] * 96
    for index in (20, 21, 22, 23):
        prices[index] = -0.30
    day = day_from(prices)

    assert window(cheap(day, 60)) == ("05:00", "06:00")
    assert window(expensive(day, 60)) != ("05:00", "06:00")
    assert expensive(day, 60)["average_price_eur_kwh"] == pytest.approx(0.05)


def test_a_window_may_mix_positive_and_negative_prices():
    """The average is the average, sign changes inside the window included."""
    prices = [0.50] * 96
    prices[40] = -0.10
    prices[41] = -0.05
    prices[42] = 0.05
    prices[43] = 0.10

    period = cheap(day_from(prices), 60)
    assert window(period) == ("10:00", "11:00")
    assert period["average_price_eur_kwh"] == pytest.approx(0.0)
    assert period["min_price_eur_kwh"] == pytest.approx(-0.10)
    assert period["max_price_eur_kwh"] == pytest.approx(0.10)


# --- Hourly fallback --------------------------------------------------------


@pytest.mark.parametrize("duration", [60, 120, 240, 720])
def test_a_duration_that_is_a_whole_number_of_hours_works_on_hourly_data(duration):
    """The hourly fallback supports every duration it can actually compose."""
    hours = real_day(lambda i: 0.10 + i * 0.01, DAY, resolution=60)
    period = cheap(hours, duration)
    assert period is not None
    assert period["duration_minutes"] == duration
    assert period["block_count"] == duration // 60


@pytest.mark.parametrize("duration", [15, 30, 45, 90, 105, 150])
def test_a_duration_hourly_data_cannot_compose_yields_nothing(duration):
    """Never split a source block to reach a duration Frank did not publish.

    90 minutes out of hourly data would mean inventing the price of half an
    hour that was never quoted. The honest answer is that there is no such
    period, which the entities surface as unavailable.
    """
    hours = real_day(lambda i: 0.10 + i * 0.01, DAY, resolution=60)
    assert cheap(hours, duration) is None
    assert expensive(hours, duration) is None


def test_the_same_duration_works_on_quarter_data_and_not_on_hourly():
    """The one comparison that shows the behaviour is resolution-driven."""
    quarters = real_day(lambda i: 0.10, DAY)
    hours = real_day(lambda i: 0.10, DAY, resolution=60)

    assert cheap(quarters, 90) is not None
    assert cheap(hours, 90) is None


# --- Daylight saving --------------------------------------------------------


def test_the_spring_forward_day_has_92_quarters_and_still_yields_a_window():
    """The 23-hour day: duration is elapsed time, not wall-clock arithmetic."""
    prices = real_day(lambda i: 0.10 + (i % 11) * 0.01, SPRING_FORWARD)
    assert len(prices) == 92

    period = cheap(prices, 120)
    assert period is not None
    assert period["duration_minutes"] == 120
    assert elapsed(period) == timedelta(minutes=120)


def test_a_window_across_the_spring_forward_jump_is_two_real_hours():
    """The requested duration is elapsed time, not a wall-clock difference.

    The whole day is flat, so the earliest valid 120-minute window wins — and
    it must be 120 *real* minutes wide. Priced so the cheapest stretch is
    forced to straddle the 02:00 jump, the local clock reads 01:00 to 04:00
    while only two hours have actually passed.
    """
    prices = real_day(lambda i: 0.01 if 4 <= i < 12 else 0.90, SPRING_FORWARD)
    period = cheap(prices, 120)

    assert period["block_count"] == 8
    assert elapsed(period) == timedelta(minutes=120)
    # Three hours on the wall clock, two in reality.
    assert window(period) == ("01:00", "04:00")
    assert period["end"] - period["start"] == timedelta(hours=3)


def test_the_fall_back_day_has_100_quarters_and_still_yields_a_window():
    """The 25-hour day, with 02:00-03:00 local occurring twice."""
    prices = real_day(lambda i: 0.10 + (i % 13) * 0.01, FALL_BACK)
    assert len(prices) == 100

    period = cheap(prices, 180)
    assert period is not None
    assert period["duration_minutes"] == 180
    assert elapsed(period) == timedelta(minutes=180)


def test_the_repeated_fall_back_hour_can_be_part_of_the_window():
    """The cheapest stretch really is inside the hour that happens twice.

    Both passes of 02:00-03:00 are priced far below the rest of the day, so a
    120-minute window has to take all eight of those quarters. That only works
    if the two passes are treated as eight distinct, contiguous blocks rather
    than as four blocks seen twice.
    """
    prices = real_day(lambda i: 0.90 if not 8 <= i < 16 else 0.01, FALL_BACK)
    period = cheap(prices, 120)

    assert period["block_count"] == 8
    assert period["average_price_eur_kwh"] == pytest.approx(0.01)
    # Local wall clock says 02:00 to 03:00 -- one hour -- but two really passed.
    assert window(period) == ("02:00", "03:00")
    assert period["end"] - period["start"] == timedelta(hours=1)
    assert elapsed(period) == timedelta(minutes=120)


def test_the_two_folds_of_the_fall_back_hour_are_not_collapsed():
    """Both passes are present, an hour apart, in the right order."""
    prices = real_day(lambda i: float(i), FALL_BACK)
    starts = [block_["from"].astimezone(ZoneInfo("UTC")) for block_ in prices]

    assert len(set(starts)) == len(starts)
    assert starts == sorted(starts)


@pytest.mark.parametrize("day", [SPRING_FORWARD, FALL_BACK])
def test_a_dst_day_is_still_selected_on_price_not_on_position(day):
    """The cheapest stretch is found wherever it is on a DST day too."""
    prices = real_day(lambda i: 0.01 if 40 <= i < 48 else 0.50, day)
    period = cheap(prices, 120)

    assert period["average_price_eur_kwh"] == pytest.approx(0.01)
    assert period["block_count"] == 8


# --- Membership -------------------------------------------------------------


def test_membership_uses_start_inclusive_end_exclusive():
    """The documented ``start <= now < end`` rule, at the exact boundaries."""
    period = cheap(real_day(lambda i: 0.10, DAY), 60)
    start = period["start"]
    end = period["end"]

    assert is_within_period(period, start - timedelta(seconds=1)) is False
    assert is_within_period(period, start) is True
    assert is_within_period(period, start + timedelta(minutes=30)) is True
    assert is_within_period(period, end - timedelta(seconds=1)) is True
    assert is_within_period(period, end) is False
    assert is_within_period(period, end + timedelta(seconds=1)) is False


def test_membership_of_a_missing_period_is_unknown_not_false():
    """ "No period" must stay distinguishable from "outside the period"."""
    now = datetime(2026, 8, 6, 12, tzinfo=NL_TZ)
    assert is_within_period(None, now) is None
    assert is_within_period({}, now) is None
    assert is_within_period({"start": "12:00", "end": "14:00"}, now) is None


def test_membership_distinguishes_the_two_folds_of_the_fall_back_hour():
    """02:30 CEST and 02:30 CET are an hour apart and judged separately."""
    prices = real_day(lambda i: 0.90 if not 8 <= i < 12 else 0.01, FALL_BACK)
    period = cheap(prices, 60)  # the *first* pass of 02:00-03:00

    first_fold = datetime(2026, 10, 25, 2, 30, tzinfo=NL_TZ, fold=0)
    second_fold = datetime(2026, 10, 25, 2, 30, tzinfo=NL_TZ, fold=1)
    assert second_fold.astimezone(ZoneInfo("UTC")) - first_fold.astimezone(
        ZoneInfo("UTC")
    ) == timedelta(hours=1)

    assert is_within_period(period, first_fold) is True
    assert is_within_period(period, second_fold) is False


# --- Independence from the price-zone margins -------------------------------


@pytest.mark.parametrize("margin", [0.0, 5.0, 15.0, 25.0, 49.0])
def test_the_algorithm_takes_no_margin_at_all(margin):
    """There is no parameter to pass a margin to; the signature is the proof.

    ``calculate_optimal_period`` accepts a price list, a duration and a mode.
    A zone margin cannot reach it, whatever the user configures.
    """
    prices = real_day(lambda i: 0.01 if 44 <= i < 52 else 0.30, DAY)
    period = cheap(prices, 120)
    assert window(period) == ("11:00", "13:00")
    assert "margin_percent" not in period
    assert "threshold_eur_kwh" not in period


def test_the_window_can_lie_wholly_outside_the_cheap_zone():
    """The two features really can disagree, and that is correct.

    The day has one very cheap quarter and a separate long moderately cheap
    stretch. A 15% cheap *zone* selects only the run around the single lowest
    quarter; the cheapest contiguous **three hours** is somewhere else
    entirely. Neither is wrong -- they answer different questions.
    """
    from custom_components.frank_quarter_prices.price_zone import calculate_price_zone

    prices = [0.40] * 96
    prices[8] = 0.00  # 02:00, the single cheapest quarter of the day
    for index in range(40, 52):  # 10:00 .. 13:00, moderately cheap for 3 hours
        prices[index] = 0.15
    day = day_from(prices)

    zone = calculate_price_zone(day, "cheap", 15.0)
    period = cheap(day, 180)

    assert window(period) == ("10:00", "13:00")
    # The zone is the single rock-bottom quarter; the period is elsewhere.
    assert f"{zone['start']:%H:%M}" == "02:00"
    assert period["start"] > zone["end"]


def test_the_selected_window_is_identical_at_every_margin():
    """Belt and braces: derive at every documented margin, one answer.

    The margin cannot influence the result -- but the whole point of the
    feature is that a user tuning their zones does not silently move their
    charging window, so it is asserted rather than argued.

    The day is deliberately stepped rather than flat-with-a-dip, so the margin
    is provably load-bearing: the cheap zone grows from two hours to four to
    six as the margin widens. Without that the test would pass on a day where
    the margin happens to change nothing, which proves nothing at all.
    """
    from custom_components.frank_quarter_prices.price_zone import calculate_price_zone

    def price_at(index: int) -> float:
        if 44 <= index < 52:  # 11:00-13:00, the cheapest two hours
            return 0.05
        if 52 <= index < 60:  # 13:00-15:00
            return 0.10
        if 60 <= index < 68:  # 15:00-17:00
            return 0.20
        return 0.40

    prices = real_day(price_at, DAY)

    windows = set()
    zone_ends = set()
    for margin in (0.0, 5.0, 15.0, 25.0, 49.0):
        windows.add(window(cheap(prices, 120)))
        zone_ends.add(f"{calculate_price_zone(prices, 'cheap', margin)['end']:%H:%M}")

    # The margin really is reaching the zone code and moving its boundary...
    assert zone_ends == {"13:00", "15:00", "17:00"}
    # ...while the optimal window does not budge.
    assert windows == {("11:00", "13:00")}


# --- Robustness -------------------------------------------------------------


def test_unusable_blocks_are_skipped_without_joining_two_runs():
    """A block with no price cannot silently bridge the two sides of a hole."""
    prices = [0.10] * 96
    day = day_from(prices)
    day[40]["total_price_eur_kwh"] = None

    period = cheap(day, 24 * 60)
    # Dropping 10:00 leaves the day no longer contiguous end to end.
    assert period is None


def test_blocks_arriving_out_of_order_are_sorted_first():
    """A shuffled list still produces the same window."""
    prices = [0.30] * 96
    for index in range(44, 52):
        prices[index] = 0.01
    ordered = day_from(prices)
    shuffled = ordered[48:] + ordered[:48]

    assert window(cheap(shuffled, 120)) == window(cheap(ordered, 120))


def test_naive_datetimes_are_rejected():
    """A block without a timezone cannot be placed on an absolute timeline."""
    # The naive datetimes are the point of the test, hence the suppressions.
    naive = [
        {
            "from": datetime(2026, 8, 6, 10, 0),  # noqa: DTZ001
            "till": datetime(2026, 8, 6, 10, 15),  # noqa: DTZ001
            "total_price_eur_kwh": 0.10,
        }
    ]
    assert cheap(naive, 15) is None


def test_the_result_carries_its_own_mode():
    """Cheap and expensive results are self-describing."""
    prices = real_day(lambda i: 0.10 + i * 0.001, DAY)
    assert cheap(prices, 60)["mode"] == OPTIMAL_MODE_CHEAP
    assert expensive(prices, 60)["mode"] == OPTIMAL_MODE_EXPENSIVE


def test_the_maximum_duration_is_at_most_half_a_normal_day():
    """The documented 12-hour ceiling, asserted rather than assumed.

    It must stay short enough to be composable on the 23-hour spring-forward
    day, which is the shortest day of the year.
    """
    assert MAX_OPTIMAL_DURATION_MINUTES == 720
    assert MAX_OPTIMAL_DURATION_MINUTES <= 23 * 60
    assert MIN_OPTIMAL_DURATION_MINUTES == 15

    shortest_day = real_day(lambda i: 0.10, SPRING_FORWARD)
    assert cheap(shortest_day, MAX_OPTIMAL_DURATION_MINUTES) is not None
