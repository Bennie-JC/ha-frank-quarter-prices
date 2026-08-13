"""The full public contract of the two price-period binary sensors.

These are the entities an EMS or a charger automation binds to, so they get a
suite of their own rather than being covered incidentally. Three properties
matter and each is checked end to end through Home Assistant, not against the
helper function:

* the boundary rule is ``start <= now < end`` on **absolute instants**, so it
  survives the repeated hour of the fall-back day and any Home Assistant
  timezone;
* the state is derived from the *same* shared zone the boundary sensors
  publish, so the three entities can never disagree;
* cheap and expensive can never both be on, because the two price bands cannot
  overlap for any valid margin pair.

"Zone unknown" is deliberately ``unavailable`` rather than ``off``: an
automation must be able to tell "not cheap right now" apart from "the
integration cannot say".
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
    CONF_CHEAP_ZONE_MARGIN_PERCENT,
    CONF_EXPENSIVE_ZONE_MARGIN_PERCENT,
    COUNTRY_BE,
    COUNTRY_NL,
    DOMAIN,
    MARKET_TIMEZONES,
)

from .conftest import build_block_span, build_local_day_blocks

CHEAP_START = "sensor.frank_cheap_zone_start_today"
CHEAP_END = "sensor.frank_cheap_zone_end_today"
EXPENSIVE_START = "sensor.frank_expensive_zone_start_today"
EXPENSIVE_END = "sensor.frank_expensive_zone_end_today"
CHEAP_PERIOD = "binary_sensor.frank_cheap_period"
EXPENSIVE_PERIOD = "binary_sensor.frank_expensive_period"

_CLIENT_METHOD = (
    "custom_components.frank_quarter_prices.frank_client."
    "FrankClient.async_get_prices_for_date"
)

NL_TZ = ZoneInfo("Europe/Amsterdam")
DAY = date(2026, 8, 6)
SPRING_FORWARD = date(2026, 3, 29)
FALL_BACK = date(2026, 10, 25)

# A day with one unambiguous cheap window and one unambiguous expensive window,
# at realistic Dutch magnitudes.
NORMAL_MP = 0.13
LOW_MP = 0.015
HIGH_MP = 0.28
CHEAP_RUN = range(40, 48)  # 10:00 .. 12:00
EXPENSIVE_RUN = range(76, 84)  # 19:00 .. 21:00


def shaped_day(day: date, country: str = COUNTRY_NL) -> list[dict[str, Any]]:
    """Return a shaped market day, or the realistic curve on a DST day."""
    tz_name = MARKET_TIMEZONES[country]
    plain = build_local_day_blocks(day, NORMAL_MP, timezone_name=tz_name)
    if len(plain) != 96:
        return build_local_day_blocks(day, None, timezone_name=tz_name)

    prices = [NORMAL_MP] * 96
    for index in CHEAP_RUN:
        prices[index] = LOW_MP
    for index in EXPENSIVE_RUN:
        prices[index] = HIGH_MP
    return [
        build_block_span(block["from"], block["till"], prices[index])
        for index, block in enumerate(plain)
    ]


class ShapedApi:
    """Client stand-in serving the shaped market day."""

    def __init__(self, country: str = COUNTRY_NL) -> None:
        """Initialize for a market."""
        self.calls: list[date] = []
        self.country = country

    async def fetch(self, target_date: date) -> dict[str, Any]:
        """Serve the shaped day."""
        self.calls.append(target_date)
        return {"prices": shaped_day(target_date, self.country)}


def make_entry(
    country: str = COUNTRY_NL,
    cheap: float | None = None,
    expensive: float | None = None,
) -> MockConfigEntry:
    """Return a config entry, optionally with explicit margins."""
    options: dict[str, Any] = {}
    if cheap is not None:
        options[CONF_CHEAP_ZONE_MARGIN_PERCENT] = cheap
    if expensive is not None:
        options[CONF_EXPENSIVE_ZONE_MARGIN_PERCENT] = expensive
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Frank Quarter Prices ({country})",
        data={"country": country},
        options=options,
        unique_id=country,
    )


def market_time(day: date, hour: int, minute: int = 0, second: int = 0, fold: int = 0):
    """Return a market-local instant, with explicit fold control."""
    return datetime(
        day.year, day.month, day.day, hour, minute, second, tzinfo=NL_TZ, fold=fold
    )


async def setup_at(
    hass, entry, moment: datetime, ha_timezone: str = "Europe/Amsterdam"
):
    """Set up the entry at ``moment`` with Home Assistant on ``ha_timezone``."""
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


# --- Boundary contract -------------------------------------------------------


@pytest.mark.parametrize(
    ("hour", "minute", "second", "expected"),
    [
        (9, 59, 59, "off"),  # one second before
        (10, 0, 0, "on"),  # exactly at the start -> inside
        (11, 0, 0, "on"),  # inside
        (11, 59, 59, "on"),  # last second inside
        (12, 0, 0, "off"),  # exactly at the end -> outside
        (13, 0, 0, "off"),  # after
    ],
)
async def test_cheap_period_boundary_contract(hass, hour, minute, second, expected):
    """start <= now < end, checked at every boundary instant."""
    api = ShapedApi()
    with patch(_CLIENT_METHOD, AsyncMock(side_effect=api.fetch)):
        freezer, _ = await setup_at(
            hass, make_entry(), market_time(DAY, hour, minute, second)
        )
        try:
            assert hass.states.get(CHEAP_PERIOD).state == expected
        finally:
            freezer.stop()


@pytest.mark.parametrize(
    ("hour", "minute", "second", "expected"),
    [
        (18, 59, 59, "off"),
        (19, 0, 0, "on"),
        (20, 0, 0, "on"),
        (20, 59, 59, "on"),
        (21, 0, 0, "off"),
        (22, 0, 0, "off"),
    ],
)
async def test_expensive_period_boundary_contract(hass, hour, minute, second, expected):
    """The expensive period obeys the identical rule."""
    api = ShapedApi()
    with patch(_CLIENT_METHOD, AsyncMock(side_effect=api.fetch)):
        freezer, _ = await setup_at(
            hass, make_entry(), market_time(DAY, hour, minute, second)
        )
        try:
            assert hass.states.get(EXPENSIVE_PERIOD).state == expected
        finally:
            freezer.stop()


# --- Never both on -----------------------------------------------------------


@pytest.mark.parametrize(
    ("cheap_margin", "expensive_margin"),
    [
        (0.0, 0.0),
        (5.0, 5.0),
        (15.0, 15.0),
        (25.0, 25.0),
        (49.0, 49.0),
        (49.0, 0.0),
        (0.0, 49.0),
        (5.0, 25.0),
        (25.0, 5.0),
    ],
)
async def test_the_two_periods_are_never_both_on(hass, cheap_margin, expensive_margin):
    """Walk the whole day at every margin pair; the two never coincide."""
    api = ShapedApi()
    entry = make_entry(cheap=cheap_margin, expensive=expensive_margin)
    with patch(_CLIENT_METHOD, AsyncMock(side_effect=api.fetch)):
        freezer, frozen = await setup_at(hass, entry, market_time(DAY, 0, 0, 3))
        try:
            for quarter in range(96):
                moment = market_time(DAY, 0, 0, 3) + timedelta(minutes=15 * quarter)
                await tick(hass, frozen, moment)
                states = {
                    hass.states.get(CHEAP_PERIOD).state,
                    hass.states.get(EXPENSIVE_PERIOD).state,
                }
                assert states != {"on"}, (
                    f"both on at {moment:%H:%M} with {cheap_margin}/{expensive_margin}"
                )
        finally:
            freezer.stop()


async def test_thresholds_stay_ordered_on_a_very_flat_but_non_zero_day(hass):
    """A day with a tiny but real spread still separates the two bands."""
    # Two prices one ten-thousandth of a euro apart.
    day_blocks = build_local_day_blocks(DAY, 0.09)
    day_blocks[40] = build_block_span(
        day_blocks[40]["from"], day_blocks[40]["till"], 0.0899
    )
    with patch(_CLIENT_METHOD, AsyncMock(side_effect=lambda d: {"prices": day_blocks})):
        freezer, _ = await setup_at(
            hass, make_entry(cheap=49.0, expensive=49.0), market_time(DAY, 10, 7)
        )
        try:
            cheap = hass.states.get(CHEAP_START).attributes
            expensive = hass.states.get(EXPENSIVE_START).attributes
            assert cheap["threshold_eur_kwh"] < expensive["threshold_eur_kwh"]
            assert {
                hass.states.get(CHEAP_PERIOD).state,
                hass.states.get(EXPENSIVE_PERIOD).state,
            } != {"on"}
        finally:
            freezer.stop()


# --- Shared zone, never a second calculation --------------------------------


async def test_period_state_is_implied_by_its_own_boundary_sensors(hass):
    """At every quarter the binary state follows from the published boundaries."""
    api = ShapedApi()
    with patch(_CLIENT_METHOD, AsyncMock(side_effect=api.fetch)):
        freezer, frozen = await setup_at(hass, make_entry(), market_time(DAY, 0, 0, 3))
        try:
            for quarter in range(96):
                moment = market_time(DAY, 0, 0, 3) + timedelta(minutes=15 * quarter)
                await tick(hass, frozen, moment)
                for period_id, start_id, end_id in (
                    (CHEAP_PERIOD, CHEAP_START, CHEAP_END),
                    (EXPENSIVE_PERIOD, EXPENSIVE_START, EXPENSIVE_END),
                ):
                    start = datetime.fromisoformat(hass.states.get(start_id).state)
                    end = datetime.fromisoformat(hass.states.get(end_id).state)
                    expected = "on" if start <= moment < end else "off"
                    assert hass.states.get(period_id).state == expected, (
                        f"{period_id} disagrees with its boundaries at {moment}"
                    )
                    # And it reports the same window it was judged against.
                    attrs = hass.states.get(period_id).attributes
                    assert (
                        attrs["zone_start"]
                        == (hass.states.get(start_id).attributes["zone_start"])
                    )
                    assert (
                        attrs["zone_end"]
                        == (hass.states.get(start_id).attributes["zone_end"])
                    )
        finally:
            freezer.stop()


# --- Unknown zone is unavailable, never a false OFF --------------------------


async def test_incomplete_day_makes_the_periods_unavailable_not_off(hass):
    """ "Cannot say" must be distinguishable from "not right now"."""
    partial = build_local_day_blocks(DAY, None)[:48]
    with patch(_CLIENT_METHOD, AsyncMock(side_effect=lambda d: {"prices": partial})):
        freezer, _ = await setup_at(hass, make_entry(), market_time(DAY, 10, 7))
        try:
            for entity_id in (CHEAP_PERIOD, EXPENSIVE_PERIOD):
                state = hass.states.get(entity_id)
                assert state.state == "unavailable", entity_id
                assert state.state != "off"
        finally:
            freezer.stop()


async def test_flat_day_makes_the_periods_unavailable_not_off(hass):
    """A perfectly flat day has no cheap-versus-expensive distinction."""
    flat = build_local_day_blocks(DAY, 0.09)
    with patch(_CLIENT_METHOD, AsyncMock(side_effect=lambda d: {"prices": flat})):
        freezer, _ = await setup_at(hass, make_entry(), market_time(DAY, 10, 7))
        try:
            for entity_id in (CHEAP_PERIOD, EXPENSIVE_PERIOD):
                assert hass.states.get(entity_id).state == "unavailable", entity_id
        finally:
            freezer.stop()


# --- Daylight saving ---------------------------------------------------------


async def test_periods_work_on_the_spring_forward_day(hass):
    """The 92-quarter day publishes usable, non-contradictory period states."""
    api = ShapedApi()
    with patch(_CLIENT_METHOD, AsyncMock(side_effect=api.fetch)):
        freezer, frozen = await setup_at(
            hass, make_entry(), market_time(SPRING_FORWARD, 14, 7)
        )
        try:
            assert int(hass.states.get("sensor.frank_prices_today").state) == 92
            for hour in (0, 1, 3, 12, 20, 23):
                await tick(hass, frozen, market_time(SPRING_FORWARD, hour, 0, 3))
                states = {
                    hass.states.get(CHEAP_PERIOD).state,
                    hass.states.get(EXPENSIVE_PERIOD).state,
                }
                assert states <= {"on", "off"}
                assert states != {"on"}
        finally:
            freezer.stop()


async def test_periods_distinguish_both_folds_of_the_fall_back_hour(hass):
    """02:30 CEST and 02:30 CET are an hour apart and must be judged separately.

    The realistic curve prices 00:00-11:00 at the same night rate, so the zone
    boundaries do not sit inside the repeated hour here; what this pins down is
    that evaluating at the two folds does not produce a contradictory or
    unavailable state, and that the sensor tracks real elapsed time rather than
    the wall clock.
    """
    api = ShapedApi()
    with patch(_CLIENT_METHOD, AsyncMock(side_effect=api.fetch)):
        freezer, frozen = await setup_at(
            hass, make_entry(), market_time(FALL_BACK, 1, 0, 3)
        )
        try:
            assert int(hass.states.get("sensor.frank_prices_today").state) == 100

            first_fold = market_time(FALL_BACK, 2, 30, 3, fold=0)
            second_fold = market_time(FALL_BACK, 2, 30, 3, fold=1)
            # A real hour apart, not the same instant.
            assert (
                second_fold.astimezone(ZoneInfo("UTC"))
                - first_fold.astimezone(ZoneInfo("UTC"))
            ) == timedelta(hours=1)

            for moment in (first_fold, second_fold):
                await tick(hass, frozen, moment)
                cheap = hass.states.get(CHEAP_PERIOD)
                expensive = hass.states.get(EXPENSIVE_PERIOD)
                assert cheap.state in ("on", "off"), moment
                assert expensive.state in ("on", "off"), moment
                assert {cheap.state, expensive.state} != {"on"}
        finally:
            freezer.stop()


# --- Home Assistant timezone -------------------------------------------------


@pytest.mark.parametrize(
    "ha_timezone",
    ["Europe/Amsterdam", "UTC", "Europe/London", "America/New_York", "Asia/Tokyo"],
)
async def test_periods_are_identical_under_any_ha_timezone(hass, ha_timezone):
    """The market instant decides, not Home Assistant's clock."""
    api = ShapedApi()
    with patch(_CLIENT_METHOD, AsyncMock(side_effect=api.fetch)):
        # 11:00 market time is inside the 10:00-12:00 cheap window.
        freezer, frozen = await setup_at(
            hass, make_entry(), market_time(DAY, 11, 0, 3), ha_timezone
        )
        try:
            assert hass.states.get(CHEAP_PERIOD).state == "on"
            assert hass.states.get(EXPENSIVE_PERIOD).state == "off"

            # 20:00 market time is inside the 19:00-21:00 expensive window.
            await tick(hass, frozen, market_time(DAY, 20, 0, 3))
            assert hass.states.get(CHEAP_PERIOD).state == "off"
            assert hass.states.get(EXPENSIVE_PERIOD).state == "on"
        finally:
            freezer.stop()


async def test_periods_follow_the_belgian_market(hass):
    """Belgium is judged on Europe/Brussels while Home Assistant runs on UTC."""
    api = ShapedApi(COUNTRY_BE)
    entry = make_entry(COUNTRY_BE)
    brussels = ZoneInfo(MARKET_TIMEZONES[COUNTRY_BE])
    moment = datetime(2026, 8, 6, 11, 0, 3, tzinfo=brussels)

    with patch(_CLIENT_METHOD, AsyncMock(side_effect=api.fetch)):
        freezer, _ = await setup_at(hass, entry, moment, "UTC")
        try:
            assert hass.states.get(CHEAP_PERIOD).state == "on"
            assert hass.states.get(EXPENSIVE_PERIOD).state == "off"
        finally:
            freezer.stop()
