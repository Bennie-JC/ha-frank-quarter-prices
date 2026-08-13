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

from .conftest import build_local_day_blocks

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


def market_time(day: date, hour: int, minute: int = 0, second: int = 0, tz=NL_TZ):
    """Return a market-local datetime."""
    return datetime(
        day.year, day.month, day.day, hour, minute, second, tzinfo=ZoneInfo(tz)
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


@pytest.mark.parametrize("ha_timezone", ["Europe/Brussels", "UTC", "America/New_York"])
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


@pytest.mark.parametrize("ha_timezone", ["UTC", "Asia/Tokyo", "America/New_York"])
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
