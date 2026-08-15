"""The market's day must not depend on Home Assistant's configured timezone.

Frank publishes a *market* day: midnight to midnight in Europe/Amsterdam for NL
and Europe/Brussels for BE. Home Assistant's timezone is a display preference —
a user may legitimately run it in UTC — and it must never decide which blocks
belong to today, nor where the day starts and ends when validating that a
fetched day is complete.

Before the fix the coordinator used Home Assistant's local day for both. On a
UTC installation that made every Dutch day two hours short, so:

* no day was ever accepted as complete,
* all six price-zone entities stayed permanently unavailable,
* both days were re-requested on every quarter tick — ~144 requests a day
  instead of ~2.

Every test here therefore drives Home Assistant's timezone away from the market
timezone and asserts that nothing about the market data moves.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.frank_quarter_prices.const import (
    COUNTRY_BE,
    COUNTRY_NL,
    DOMAIN,
    MARKET_TIMEZONES,
)
from custom_components.frank_quarter_prices.market_time import (
    market_date_of,
    market_day_bounds,
    market_midnight,
    market_timezone,
)

from .conftest import build_block_span, build_local_day_blocks

CHEAP_START = "sensor.frank_cheap_zone_start_today"
CHEAP_END = "sensor.frank_cheap_zone_end_today"
EXPENSIVE_START = "sensor.frank_expensive_zone_start_today"
EXPENSIVE_END = "sensor.frank_expensive_zone_end_today"
CHEAP_PERIOD = "binary_sensor.frank_cheap_period"
EXPENSIVE_PERIOD = "binary_sensor.frank_expensive_period"
PRICES_TODAY = "sensor.frank_prices_today"
PRICES_TOMORROW = "sensor.frank_prices_tomorrow"

ZONE_ENTITIES = (
    CHEAP_START,
    CHEAP_END,
    EXPENSIVE_START,
    EXPENSIVE_END,
    CHEAP_PERIOD,
    EXPENSIVE_PERIOD,
)

_CLIENT_METHOD = (
    "custom_components.frank_quarter_prices.frank_client."
    "FrankClient.async_get_prices_for_date"
)

NL_TZ = "Europe/Amsterdam"
BE_TZ = "Europe/Brussels"

DAY = date(2026, 8, 6)
SPRING_FORWARD = date(2026, 3, 29)  # 92 quarters
FALL_BACK = date(2026, 10, 25)  # 100 quarters

# Home Assistant timezones a user might plausibly be running.
HA_TIMEZONES = [
    "Europe/Amsterdam",
    "UTC",
    "Europe/London",
    "America/New_York",
    "Asia/Tokyo",
]


class MarketApi:
    """Client stand-in serving realistic market days and recording requests."""

    def __init__(self, country: str = COUNTRY_NL) -> None:
        """Initialize for a given market."""
        self.calls: list[date] = []
        self.country = country
        self.responses: dict[date, Any] = {}

    def count(self, day: date) -> int:
        """Return how many times ``day`` was requested."""
        return self.calls.count(day)

    async def fetch(self, target_date: date) -> dict[str, Any]:
        """Serve the market day for ``target_date``."""
        self.calls.append(target_date)
        override = self.responses.get(target_date)
        if override is not None:
            return {"prices": list(override)}
        return {
            "prices": build_local_day_blocks(
                target_date, None, timezone_name=MARKET_TIMEZONES[self.country]
            )
        }


def make_entry(country: str = COUNTRY_NL) -> MockConfigEntry:
    """Return a config entry for the given market."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Frank Quarter Prices ({country})",
        data={"country": country},
        options={},
        unique_id=country,
    )


def market_time(
    day: date, hour: int, minute: int = 0, second: int = 0, tz=NL_TZ, fold: int = 0
):
    """Return a market-local datetime.

    ``fold`` selects which pass of an ambiguous wall clock is meant: on the
    fall-back day 02:00-03:00 happens twice, ``fold=0`` being the first pass
    (CEST) and ``fold=1`` the second (CET), a real hour later. It defaults to 0,
    which is what Python assumes anyway, so unambiguous callers are unaffected.
    """
    return datetime(
        day.year,
        day.month,
        day.day,
        hour,
        minute,
        second,
        tzinfo=ZoneInfo(tz),
        fold=fold,
    )


async def setup_with_ha_timezone(hass, entry, moment: datetime, ha_timezone: str):
    """Set up the entry with Home Assistant on ``ha_timezone`` at ``moment``.

    ``moment`` is an absolute instant; Home Assistant renders it in whatever
    timezone it is configured for, which is exactly the divergence under test.
    """
    await hass.config.async_set_time_zone(ha_timezone)
    freezer = freeze_time(moment)
    frozen = freezer.start()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return freezer, frozen


async def tick(hass, frozen, moment: datetime) -> None:
    """Advance the frozen clock and fire the scheduled listeners."""
    frozen.move_to(moment)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def assert_zones_published(hass) -> None:
    """Assert all six zone entities carry a usable value."""
    for entity_id in ZONE_ENTITIES:
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.state not in ("unavailable", "unknown"), (
            f"{entity_id} is {state.state} — the market day did not validate"
        )


# --- The mapping itself ------------------------------------------------------


def test_market_timezone_mapping():
    """NL and BE map to their own market timezones."""
    assert str(market_timezone(COUNTRY_NL)) == NL_TZ
    assert str(market_timezone(COUNTRY_BE)) == BE_TZ


def test_unknown_country_falls_back_to_the_default_market_not_utc():
    """An unexpected country must not silently become UTC.

    UTC is not the day boundary of any Frank market, so falling back to it
    would reintroduce the very bug this module prevents.
    """
    for value in (None, "", "XX", "de"):
        assert str(market_timezone(value)) == NL_TZ


def test_market_day_bounds_span_real_days():
    """The bounds are 23, 24 and 25 hours across the DST transitions.

    Both ends are converted to UTC before subtracting: two datetimes sharing one
    ``tzinfo`` object subtract *naively* in Python and would report 24 hours for
    every day, hiding the DST days entirely. The coordinator converts the same
    way before comparing.
    """
    for day, expected_hours in (
        (SPRING_FORWARD, 23),
        (DAY, 24),
        (FALL_BACK, 25),
    ):
        start, end = market_day_bounds(day, COUNTRY_NL)
        elapsed = end.astimezone(ZoneInfo("UTC")) - start.astimezone(ZoneInfo("UTC"))
        assert elapsed == timedelta(hours=expected_hours), day


def test_market_date_of_uses_the_market_not_the_caller():
    """23:30 UTC is already the next day in the Dutch market."""
    late = datetime(2026, 8, 6, 23, 30, tzinfo=ZoneInfo("UTC"))
    assert market_date_of(late, COUNTRY_NL) == date(2026, 8, 7)
    # And 00:30 in Tokyo is still the previous Dutch day.
    tokyo = datetime(2026, 8, 7, 0, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert market_date_of(tokyo, COUNTRY_NL) == date(2026, 8, 6)


def test_market_midnight_is_market_local():
    """Midnight is the market's midnight, not UTC's."""
    midnight = market_midnight(DAY, COUNTRY_NL)
    assert midnight.hour == 0
    assert midnight.utcoffset() == timedelta(hours=2)  # CEST in August


# --- NL market under every Home Assistant timezone ---------------------------


@pytest.mark.parametrize("ha_timezone", HA_TIMEZONES)
async def test_nl_market_day_is_identical_under_any_ha_timezone(hass, ha_timezone):
    """The same Dutch day is fetched, grouped, validated and zoned."""
    api = MarketApi(COUNTRY_NL)
    entry = make_entry(COUNTRY_NL)
    # 14:07 market time, whatever Home Assistant thinks the local time is.
    moment = market_time(DAY, 14, 7)

    with patch(_CLIENT_METHOD, AsyncMock(side_effect=api.fetch)):
        freezer, _ = await setup_with_ha_timezone(hass, entry, moment, ha_timezone)
        try:
            # Exactly the market day was requested, not a neighbouring one.
            assert api.calls == [DAY, DAY + timedelta(days=1)], ha_timezone
            # A complete 96-quarter Dutch day, grouped correctly.
            assert int(hass.states.get(PRICES_TODAY).state) == 96
            assert int(hass.states.get(PRICES_TOMORROW).state) == 96
            coordinator = entry.runtime_data
            assert DAY in coordinator._complete_days
            # And therefore the zones publish.
            assert_zones_published(hass)
        finally:
            freezer.stop()


@pytest.mark.parametrize("ha_timezone", HA_TIMEZONES)
async def test_nl_zone_boundaries_are_the_same_instants_everywhere(hass, ha_timezone):
    """The zone describes the same absolute window regardless of HA's timezone."""
    api = MarketApi(COUNTRY_NL)
    entry = make_entry(COUNTRY_NL)
    moment = market_time(DAY, 14, 7)

    with patch(_CLIENT_METHOD, AsyncMock(side_effect=api.fetch)):
        freezer, _ = await setup_with_ha_timezone(hass, entry, moment, ha_timezone)
        try:
            start = datetime.fromisoformat(hass.states.get(CHEAP_START).state)
            end = datetime.fromisoformat(hass.states.get(CHEAP_END).state)
            # The realistic curve puts the solar dip at 11:00-13:00 market time.
            assert start.astimezone(ZoneInfo(NL_TZ)).strftime("%H:%M") == "11:00"
            assert end.astimezone(ZoneInfo(NL_TZ)).strftime("%H:%M") == "13:00"
        finally:
            freezer.stop()


# --- BE market ---------------------------------------------------------------


@pytest.mark.parametrize("ha_timezone", ["Europe/Brussels", *HA_TIMEZONES])
async def test_be_market_day_is_identical_under_any_ha_timezone(hass, ha_timezone):
    """Belgium behaves exactly like the Netherlands, on its own timezone."""
    api = MarketApi(COUNTRY_BE)
    entry = make_entry(COUNTRY_BE)
    moment = market_time(DAY, 14, 7, tz=BE_TZ)

    with patch(_CLIENT_METHOD, AsyncMock(side_effect=api.fetch)):
        freezer, _ = await setup_with_ha_timezone(hass, entry, moment, ha_timezone)
        try:
            assert api.calls == [DAY, DAY + timedelta(days=1)], ha_timezone
            assert int(hass.states.get(PRICES_TODAY).state) == 96
            assert entry.runtime_data.country == COUNTRY_BE
            assert DAY in entry.runtime_data._complete_days
            assert_zones_published(hass)
        finally:
            freezer.stop()


# --- DST market days while Home Assistant is on UTC --------------------------


@pytest.mark.parametrize(
    ("day", "expected_blocks"),
    [(SPRING_FORWARD, 92), (DAY, 96), (FALL_BACK, 100)],
)
async def test_dst_market_days_validate_while_ha_is_utc(hass, day, expected_blocks):
    """92-, 96- and 100-quarter market days all validate on a UTC installation.

    This is the combination that broke outright before the fix: the day length
    is set by the *market's* DST, while Home Assistant's own day never changes
    length at all.
    """
    api = MarketApi(COUNTRY_NL)
    entry = make_entry(COUNTRY_NL)
    moment = market_time(day, 14, 7)

    with patch(_CLIENT_METHOD, AsyncMock(side_effect=api.fetch)):
        freezer, _ = await setup_with_ha_timezone(hass, entry, moment, "UTC")
        try:
            assert int(hass.states.get(PRICES_TODAY).state) == expected_blocks
            assert day in entry.runtime_data._complete_days
            assert_zones_published(hass)
        finally:
            freezer.stop()


# --- Midnight mismatch -------------------------------------------------------


async def test_market_date_wins_when_the_two_dates_disagree(hass):
    """At 00:30 market time it is still the previous day in UTC.

    Home Assistant would say 2026-08-05 22:30; the market says 2026-08-06. The
    market must win, or today's prices are fetched for the wrong date.
    """
    api = MarketApi(COUNTRY_NL)
    entry = make_entry(COUNTRY_NL)
    moment = market_time(DAY, 0, 30)  # 22:30 UTC on the previous day

    with patch(_CLIENT_METHOD, AsyncMock(side_effect=api.fetch)):
        freezer, _ = await setup_with_ha_timezone(hass, entry, moment, "UTC")
        try:
            # Before 12:00 market time tomorrow is not requested at all.
            assert api.calls == [DAY]
            today_blocks = hass.states.get(PRICES_TODAY).attributes["prices"]
            first = datetime.fromisoformat(today_blocks[0]["from"])
            assert market_date_of(first, COUNTRY_NL) == DAY
            assert DAY in entry.runtime_data._complete_days
            assert_zones_published(hass)
        finally:
            freezer.stop()


async def test_late_evening_market_date_wins_the_other_way(hass):
    """At 23:30 market time Tokyo is already on the next day."""
    api = MarketApi(COUNTRY_NL)
    entry = make_entry(COUNTRY_NL)
    moment = market_time(DAY, 23, 30)  # 06:30 the next day in Tokyo

    with patch(_CLIENT_METHOD, AsyncMock(side_effect=api.fetch)):
        freezer, _ = await setup_with_ha_timezone(hass, entry, moment, "Asia/Tokyo")
        try:
            assert api.calls == [DAY, DAY + timedelta(days=1)]
            today_blocks = hass.states.get(PRICES_TODAY).attributes["prices"]
            assert (
                market_date_of(
                    datetime.fromisoformat(today_blocks[0]["from"]), COUNTRY_NL
                )
                == DAY
            )
            assert_zones_published(hass)
        finally:
            freezer.stop()


async def test_midnight_rollover_follows_the_market_not_ha(hass):
    """The day rolls at market midnight, and costs no request."""
    api = MarketApi(COUNTRY_NL)
    entry = make_entry(COUNTRY_NL)

    with patch(_CLIENT_METHOD, AsyncMock(side_effect=api.fetch)):
        freezer, frozen = await setup_with_ha_timezone(
            hass, entry, market_time(DAY, 23, 45, 3), "UTC"
        )
        try:
            before = datetime.fromisoformat(hass.states.get(CHEAP_START).state)
            assert market_date_of(before, COUNTRY_NL) == DAY
            calls_before = len(api.calls)

            # 00:00:03 market time -- still 22:00 the previous day in UTC.
            await tick(hass, frozen, market_time(DAY + timedelta(days=1), 0, 0, 3))

            after = datetime.fromisoformat(hass.states.get(CHEAP_START).state)
            assert market_date_of(after, COUNTRY_NL) == DAY + timedelta(days=1)
            # Yesterday's cached tomorrow became today for free.
            assert len(api.calls) == calls_before
            assert_zones_published(hass)
        finally:
            freezer.stop()


# --- Request volume on a UTC installation ------------------------------------


async def test_utc_ha_does_not_cause_repeated_refetching(hass):
    """A UTC installation keeps the v0.1.5 request behaviour: two per day.

    Before the fix this scenario re-requested both days on every quarter tick,
    because no day ever validated as complete.
    """
    api = MarketApi(COUNTRY_NL)
    entry = make_entry(COUNTRY_NL)
    start = market_time(DAY, 14, 7)

    with patch(_CLIENT_METHOD, AsyncMock(side_effect=api.fetch)):
        freezer, frozen = await setup_with_ha_timezone(hass, entry, start, "UTC")
        try:
            setup_calls = len(api.calls)
            assert setup_calls == 2  # today + tomorrow

            # Four hours of quarter ticks: 16 refreshes.
            moment = market_time(DAY, 14, 15, 3)
            for _ in range(16):
                await tick(hass, frozen, moment)
                moment += timedelta(minutes=15)

            assert len(api.calls) == setup_calls, (
                f"{len(api.calls) - setup_calls} extra requests — the day is "
                "not being accepted as complete"
            )
            assert_zones_published(hass)
        finally:
            freezer.stop()


async def test_utc_ha_keeps_the_current_price_available_all_day(hass):
    """The current-price sensor stays available across the whole market day.

    The two hours the old code lost were exactly the ones outside Home
    Assistant's own day window.
    """
    api = MarketApi(COUNTRY_NL)
    entry = make_entry(COUNTRY_NL)

    with patch(_CLIENT_METHOD, AsyncMock(side_effect=api.fetch)):
        freezer, frozen = await setup_with_ha_timezone(
            hass, entry, market_time(DAY, 0, 30), "UTC"
        )
        try:
            for hour in (0, 1, 2, 12, 22, 23):
                await tick(hass, frozen, market_time(DAY, hour, 0, 3))
                state = hass.states.get("sensor.frank_current_price")
                assert state.state not in ("unavailable", "unknown"), (
                    f"no current price at {hour:02d}:00 market time"
                )
        finally:
            freezer.stop()


# --- Binary sensors compare absolute instants --------------------------------


@pytest.mark.parametrize("ha_timezone", HA_TIMEZONES)
async def test_period_binary_sensors_are_correct_under_any_ha_timezone(
    hass, ha_timezone
):
    """``start <= now < end`` is an absolute comparison, so HA's zone is moot."""
    api = MarketApi(COUNTRY_NL)
    entry = make_entry(COUNTRY_NL)

    with patch(_CLIENT_METHOD, AsyncMock(side_effect=api.fetch)):
        # 12:00 market time is inside the 11:00-13:00 cheap dip.
        freezer, frozen = await setup_with_ha_timezone(
            hass, entry, market_time(DAY, 12, 0, 3), ha_timezone
        )
        try:
            assert hass.states.get(CHEAP_PERIOD).state == "on"
            assert hass.states.get(EXPENSIVE_PERIOD).state == "off"

            # 19:00 market time is inside the 18:00-21:00 evening peak.
            await tick(hass, frozen, market_time(DAY, 19, 0, 3))
            assert hass.states.get(CHEAP_PERIOD).state == "off"
            assert hass.states.get(EXPENSIVE_PERIOD).state == "on"
        finally:
            freezer.stop()


# --- The repeated hour of the fall-back day ----------------------------------
#
# The unit-level equivalent of this lives in ``tests/test_price_zone.py``
# (``test_membership_distinguishes_the_two_passes_of_the_repeated_hour``); the
# planner's binary sensor has its own entity-level version in
# ``tests/test_optimal_period_entities.py``. The two v0.1.6 price-zone binary
# sensors had neither, which is the hole this closes: nothing wired the real
# coordinator, the real zone derivation and the real ``dt_util.now()`` together
# across the fold.


def fall_back_day_split_across_the_folds() -> list[dict[str, Any]]:
    """Return a fall-back day whose two zones sit in the two folds of 02:00.

    On 2026-10-25 the Dutch day is 100 quarters long and 02:00-03:00 happens
    twice. Blocks 8-11 are the first pass (CEST, UTC+2) and blocks 12-15 the
    second (CET, UTC+1) — verified against the generated day, not assumed.

    Pricing the first pass far below and the second far above an otherwise flat
    day places the *entire* cheap zone in the first fold and the *entire*
    expensive zone in the second: two windows that read identically on the wall
    clock and are a real hour apart.
    """
    blocks = build_local_day_blocks(FALL_BACK, 0.15, timezone_name=NL_TZ)
    for index in (8, 9, 10, 11):  # 02:00-03:00 CEST -- the first pass
        blocks[index] = build_block_span(
            blocks[index]["from"], blocks[index]["till"], 0.01
        )
    for index in (12, 13, 14, 15):  # 02:00-03:00 CET -- the second pass
        blocks[index] = build_block_span(
            blocks[index]["from"], blocks[index]["till"], 0.40
        )
    return blocks


def wall_clock_within(zone: dict[str, Any], moment: datetime) -> bool:
    """Return the answer a fold-blind wall-clock comparison would give.

    CPython short-circuits ``<`` between two aware datetimes sharing one
    ``tzinfo`` object to a naive comparison that ignores ``fold``, and
    ``ZoneInfo`` is cached per key — so on an installation running in the market
    timezone a zone boundary and ``dt_util.now()`` always share one object.
    Dropping the tzinfo reproduces that comparison exactly, which lets the test
    below prove it is asserting something the buggy code would get wrong.
    """
    return (
        zone["start"].replace(tzinfo=None)
        <= moment.replace(tzinfo=None)
        < zone["end"].replace(tzinfo=None)
    )


@pytest.mark.parametrize("ha_timezone", HA_TIMEZONES)
async def test_zone_binary_sensors_distinguish_both_fall_back_folds(hass, ha_timezone):
    """02:30 CEST and 02:30 CET are an hour apart and must judge differently.

    Without this the two price-zone binary sensors were only ever exercised on
    an unambiguous day. A fold-blind comparison makes them flap on/off/on across
    the repeated hour, or report the wrong state through one of the two passes —
    for an hour, once a year, with nothing in the data to hint at why.

    Home Assistant's own timezone is varied on top, because that is what decides
    whether the buggy comparison is even reachable: the naive short-circuit only
    fires when HA runs in the market timezone. The sensors must be right on every
    installation, so the answer has to be identical in all of them.
    """
    api = MarketApi(COUNTRY_NL)
    entry = make_entry(COUNTRY_NL)
    api.responses[FALL_BACK] = fall_back_day_split_across_the_folds()

    with patch(_CLIENT_METHOD, AsyncMock(side_effect=api.fetch)):
        # 01:00 market time: before the repeated hour begins, either way round.
        freezer, frozen = await setup_with_ha_timezone(
            hass, entry, market_time(FALL_BACK, 1, 0, 3), ha_timezone
        )
        try:
            assert int(hass.states.get(PRICES_TODAY).state) == 100
            # The zones land where the priced blocks put them, as absolute
            # instants: one fold each, back to back, an hour apart.
            assert hass.states.get(CHEAP_START).state == "2026-10-25T00:00:00+00:00"
            assert hass.states.get(CHEAP_END).state == "2026-10-25T01:00:00+00:00"
            assert hass.states.get(EXPENSIVE_START).state == "2026-10-25T01:00:00+00:00"
            assert hass.states.get(EXPENSIVE_END).state == "2026-10-25T02:00:00+00:00"

            first_pass = market_time(FALL_BACK, 2, 30, 3, fold=0)  # 00:30 UTC
            second_pass = market_time(FALL_BACK, 2, 30, 3, fold=1)  # 01:30 UTC
            assert second_pass.astimezone(ZoneInfo("UTC")) - first_pass.astimezone(
                ZoneInfo("UTC")
            ) == timedelta(hours=1)

            # Not a vacuous pass: on the wall clock alone both probes read
            # 02:30:03, so a fold-blind comparison answers the same thing at
            # both — "cheap off, expensive on" — and therefore contradicts two
            # of the four state assertions that follow.
            cheap = entry.runtime_data.get_cheap_zone()
            expensive = entry.runtime_data.get_expensive_zone()
            for probe in (first_pass, second_pass):
                assert wall_clock_within(cheap, probe) is False
                assert wall_clock_within(expensive, probe) is True

            await tick(hass, frozen, first_pass)
            assert hass.states.get(CHEAP_PERIOD).state == "on"
            assert hass.states.get(EXPENSIVE_PERIOD).state == "off"

            # One real hour later the same wall clock comes round again, and
            # both sensors must have swapped rather than stayed put.
            await tick(hass, frozen, second_pass)
            assert hass.states.get(CHEAP_PERIOD).state == "off"
            assert hass.states.get(EXPENSIVE_PERIOD).state == "on"
        finally:
            freezer.stop()
