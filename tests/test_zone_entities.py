"""Behaviour tests for the six v0.1.6 price-zone entities.

The pure algorithm is covered in ``test_price_zone.py``; these tests are about
what Home Assistant actually publishes: the state contract of the four boundary
sensors, the ON/OFF boundary semantics of the two period binary sensors, and —
most importantly — that all six describe *one* shared window and can never
disagree with each other.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from freezegun import freeze_time
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import ATTR_DEVICE_CLASS
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.frank_quarter_prices.const import (
    CONF_CHEAP_ZONE_MARGIN_PERCENT,
    CONF_EXPENSIVE_ZONE_MARGIN_PERCENT,
    DOMAIN,
)

from .conftest import TEST_TIMEZONE, build_block_span, build_local_day_blocks

CHEAP_START = "sensor.frank_cheap_zone_start_today"
CHEAP_END = "sensor.frank_cheap_zone_end_today"
EXPENSIVE_START = "sensor.frank_expensive_zone_start_today"
EXPENSIVE_END = "sensor.frank_expensive_zone_end_today"
CHEAP_PERIOD = "binary_sensor.frank_cheap_period"
EXPENSIVE_PERIOD = "binary_sensor.frank_expensive_period"

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

DAY = date(2026, 8, 6)
FALL_BACK = date(2026, 10, 25)  # 25-hour local day -> 100 quarters

# Market prices shaping the test day. ``build_block_span`` turns a market price
# into a realistic all-in total, so ordering is preserved and the block shape
# stays identical to what the client produces.
# Market prices at realistic Dutch magnitudes. The all-in totals they produce
# span 0.147-0.468 EUR/kWh, a spread of 0.321 -- an ordinary summer day, not the
# ~10x-too-wide spread the first version of this fixture used. Zone thresholds
# are a percentage of that spread, so an unrealistic spread would hide exactly
# the behaviour these tests exist to pin down.
NORMAL_MP = 0.13  # all-in total 0.28615
LOW_MP = 0.015  # all-in total 0.14700  (the day minimum)
MID_MP = 0.06  # all-in total 0.20145  (outside 15%, inside 40%)
SHOULDER_MP = 0.22  # all-in total 0.39505  (outside 15%, inside 30%)
HIGH_MP = 0.28  # all-in total 0.46765  (the day maximum)

# Indices of the shaped quarters within a 96-block day.
CHEAP_RUN = range(50, 61)  # 12:30 .. 15:15
CHEAP_TAIL = range(61, 63)  # 15:15 .. 15:45, joins only at a wider margin
CHEAP_STRAY = 12  # 03:00, isolated
EXPENSIVE_RUN = range(79, 82)  # 19:45 .. 20:30
EXPENSIVE_SHOULDER = range(82, 84)  # 20:30 .. 21:00, joins at a wider margin
EXPENSIVE_STRAY = 20  # 05:00, isolated


def shaped_day(day: date) -> list[dict[str, Any]]:
    """Return a day with one clear cheap window and one clear expensive window.

    Both windows have an isolated decoy quarter elsewhere in the day, so a
    "first qualifying to last qualifying" implementation would visibly produce
    the wrong zone here rather than accidentally passing.
    """
    plain = build_local_day_blocks(day, NORMAL_MP)
    if len(plain) != 96:
        # A daylight-saving day: use the shared realistic curve, which is keyed
        # on time of day and therefore shapes 92- and 100-quarter days too.
        return build_local_day_blocks(day, None)

    market_prices = [NORMAL_MP] * 96
    market_prices[CHEAP_STRAY] = LOW_MP
    for index in CHEAP_RUN:
        market_prices[index] = LOW_MP
    for index in CHEAP_TAIL:
        market_prices[index] = MID_MP
    market_prices[EXPENSIVE_STRAY] = HIGH_MP
    for index in EXPENSIVE_RUN:
        market_prices[index] = HIGH_MP
    for index in EXPENSIVE_SHOULDER:
        market_prices[index] = SHOULDER_MP

    return [
        build_block_span(block["from"], block["till"], market_prices[index])
        for index, block in enumerate(plain)
    ]


class ShapedApi:
    """Client stand-in serving the shaped day and counting every request."""

    def __init__(self) -> None:
        """Initialize with an empty call log."""
        self.calls: list[date] = []

    async def fetch(self, target_date: date) -> dict[str, Any]:
        """Serve the shaped day for any requested date."""
        self.calls.append(target_date)
        return {"prices": shaped_day(target_date)}


@pytest.fixture
def api():
    """Patch the client with the shaped, recording fake."""
    fake = ShapedApi()
    with patch(_CLIENT_METHOD, AsyncMock(side_effect=fake.fetch)):
        yield fake


@pytest.fixture
def entry():
    """Return a mock config entry for the NL integration."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Frank Quarter Prices (NL)",
        data={"country": "NL"},
        options={},
        unique_id="NL",
    )


def at(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    """Return a local Europe/Amsterdam datetime on ``day``."""
    return datetime(
        day.year,
        day.month,
        day.day,
        hour,
        minute,
        second,
        tzinfo=dt_util.get_time_zone(TEST_TIMEZONE),
    )


async def setup_at(hass, entry, start: datetime):
    """Set up the config entry with the clock frozen at ``start``."""
    await hass.config.async_set_time_zone(TEST_TIMEZONE)
    freezer = freeze_time(start)
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


def hhmm(hass, entity_id: str) -> str:
    """Return a boundary sensor's state rendered as local ``HH:MM``."""
    return dt_util.as_local(
        datetime.fromisoformat(hass.states.get(entity_id).state)
    ).strftime("%H:%M")


# --- State contract ---------------------------------------------------------


async def test_zone_sensors_publish_the_expected_window(hass, entry, api):
    """The four boundary sensors describe the shaped cheap/expensive windows."""
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        assert hhmm(hass, CHEAP_START) == "12:30"
        assert hhmm(hass, CHEAP_END) == "15:15"
        assert hhmm(hass, EXPENSIVE_START) == "19:45"
        assert hhmm(hass, EXPENSIVE_END) == "20:30"
    finally:
        freezer.stop()


async def test_zone_sensor_state_is_an_aware_timestamp(hass, entry, api):
    """The state is a timezone-aware ISO datetime with the timestamp class.

    That is what makes the entity usable directly in an automation trigger,
    without parsing an ``HH:MM`` string or guessing which day it belongs to.
    """
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        for entity_id in (CHEAP_START, CHEAP_END, EXPENSIVE_START, EXPENSIVE_END):
            state = hass.states.get(entity_id)
            assert state.attributes[ATTR_DEVICE_CLASS] == SensorDeviceClass.TIMESTAMP
            parsed = datetime.fromisoformat(state.state)
            assert parsed.tzinfo is not None
            assert dt_util.as_local(parsed).date() == DAY
    finally:
        freezer.stop()


async def test_zone_sensor_keeps_the_hhmm_convenience_attribute(hass, entry, api):
    """The familiar ``HH:MM`` rendering stays available as an attribute."""
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        assert hass.states.get(CHEAP_START).attributes["time"] == "12:30"
        assert hass.states.get(CHEAP_END).attributes["time"] == "15:15"
        assert hass.states.get(EXPENSIVE_START).attributes["time"] == "19:45"
        assert hass.states.get(EXPENSIVE_END).attributes["time"] == "20:30"
    finally:
        freezer.stop()


async def test_zone_sensor_attributes(hass, entry, api):
    """Threshold, margin, day extremes, duration and quarter count are published."""
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        attrs = hass.states.get(CHEAP_START).attributes
        assert attrs["margin_percent"] == 15.0
        assert attrs["zone_duration_minutes"] == 165
        assert attrs["quarter_count"] == 11
        assert attrs["day_min_price"] < attrs["threshold_eur_kwh"]
        assert attrs["threshold_eur_kwh"] < attrs["day_max_price"]
        assert (
            dt_util.as_local(datetime.fromisoformat(attrs["zone_start"])).strftime(
                "%H:%M"
            )
            == "12:30"
        )
        assert (
            dt_util.as_local(datetime.fromisoformat(attrs["zone_end"])).strftime(
                "%H:%M"
            )
            == "15:15"
        )

        expensive = hass.states.get(EXPENSIVE_START).attributes
        assert expensive["zone_duration_minutes"] == 45
        assert expensive["quarter_count"] == 3
    finally:
        freezer.stop()


# --- One shared calculation -------------------------------------------------


@pytest.mark.parametrize(
    ("start_id", "end_id", "period_id"),
    [
        (CHEAP_START, CHEAP_END, CHEAP_PERIOD),
        (EXPENSIVE_START, EXPENSIVE_END, EXPENSIVE_PERIOD),
    ],
)
async def test_all_three_entities_share_one_zone(
    hass, entry, api, start_id, end_id, period_id
):
    """Start sensor, end sensor and binary sensor describe the same window.

    A second, independently calculated window inside the binary sensor is
    exactly the failure mode this guards against.
    """
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        start = hass.states.get(start_id).attributes
        end = hass.states.get(end_id).attributes
        period = hass.states.get(period_id).attributes

        # The two boundary sensors agree on the whole shared contract.
        assert start["zone_start"] == end["zone_start"] == period["zone_start"]
        assert start["zone_end"] == end["zone_end"] == period["zone_end"]
        assert (
            start["threshold_eur_kwh"]
            == end["threshold_eur_kwh"]
            == period["threshold_eur_kwh"]
        )
        assert (
            start["margin_percent"] == end["margin_percent"] == period["margin_percent"]
        )
        # And the boundary states are exactly the shared window's edges. Home
        # Assistant normalises a ``timestamp`` state to UTC while the attributes
        # stay local ISO, so the comparison is between instants, not strings.
        assert datetime.fromisoformat(
            hass.states.get(start_id).state
        ) == datetime.fromisoformat(start["zone_start"])
        assert datetime.fromisoformat(
            hass.states.get(end_id).state
        ) == datetime.fromisoformat(end["zone_end"])
    finally:
        freezer.stop()


async def test_binary_sensor_agrees_with_its_boundary_sensors(hass, entry, api):
    """The binary state is implied by the published start/end, at every tick."""
    freezer, frozen = await setup_at(hass, entry, at(DAY, 12, 0))
    try:
        for hour in range(24):
            await tick(hass, frozen, at(DAY, hour, 0, 3))
            now = dt_util.now()
            start = datetime.fromisoformat(hass.states.get(CHEAP_START).state)
            end = datetime.fromisoformat(hass.states.get(CHEAP_END).state)
            expected = "on" if start <= now < end else "off"
            assert hass.states.get(CHEAP_PERIOD).state == expected, hour
    finally:
        freezer.stop()


# --- Binary sensor boundary semantics ---------------------------------------


@pytest.mark.parametrize(
    ("hour", "minute", "second", "expected"),
    [
        (12, 29, 59, "off"),  # just before the zone
        (12, 30, 0, "on"),  # exactly at the start -> inside
        (13, 0, 0, "on"),  # inside
        (15, 14, 59, "on"),  # last instant inside
        (15, 15, 0, "off"),  # exactly at the end -> outside
        (18, 0, 0, "off"),  # after the zone
    ],
)
async def test_cheap_period_boundaries(
    hass, entry, api, hour, minute, second, expected
):
    """ON from the start boundary inclusive, OFF from the end boundary exclusive."""
    freezer, _ = await setup_at(hass, entry, at(DAY, hour, minute, second))
    try:
        assert hass.states.get(CHEAP_PERIOD).state == expected
    finally:
        freezer.stop()


@pytest.mark.parametrize(
    ("hour", "minute", "second", "expected"),
    [
        (19, 44, 59, "off"),
        (19, 45, 0, "on"),
        (20, 0, 0, "on"),
        (20, 29, 59, "on"),
        (20, 30, 0, "off"),
        (22, 0, 0, "off"),
    ],
)
async def test_expensive_period_boundaries(
    hass, entry, api, hour, minute, second, expected
):
    """The expensive period uses the same start <= now < end rule."""
    freezer, _ = await setup_at(hass, entry, at(DAY, hour, minute, second))
    try:
        assert hass.states.get(EXPENSIVE_PERIOD).state == expected
    finally:
        freezer.stop()


async def test_period_flips_on_the_quarter_tick_without_a_request(hass, entry, api):
    """Crossing into the zone flips the sensor on the existing quarter tick."""
    freezer, frozen = await setup_at(hass, entry, at(DAY, 12, 15, 3))
    try:
        assert hass.states.get(CHEAP_PERIOD).state == "off"
        calls_before = len(api.calls)

        await tick(hass, frozen, at(DAY, 12, 30, 3))
        assert hass.states.get(CHEAP_PERIOD).state == "on"

        await tick(hass, frozen, at(DAY, 15, 15, 3))
        assert hass.states.get(CHEAP_PERIOD).state == "off"

        # The flips came from cached data; no extra listener, no extra request.
        assert len(api.calls) == calls_before
    finally:
        freezer.stop()


# --- Unavailability ---------------------------------------------------------


async def test_zone_entities_unavailable_without_a_zone(hass, entry, api):
    """Without a derivable zone all six entities go unavailable, not stale.

    Publishing the previous window would be worse than publishing nothing: an
    automation cannot tell a stale boundary from a current one.
    """
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        coordinator = entry.runtime_data
        stripped = dict(coordinator.data)
        stripped["cheap_zone"] = None
        stripped["expensive_zone"] = None
        coordinator.async_set_updated_data(stripped)
        await hass.async_block_till_done()

        for entity_id in ZONE_ENTITIES:
            assert hass.states.get(entity_id).state == "unavailable", entity_id
        # The rest of the integration is untouched by a missing zone.
        assert hass.states.get("sensor.frank_current_price").state != "unavailable"
    finally:
        freezer.stop()


async def test_zone_entities_recover_when_the_zone_returns(hass, entry, api):
    """A later update with a zone brings the entities straight back."""
    freezer, frozen = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        coordinator = entry.runtime_data
        stripped = dict(coordinator.data)
        stripped["cheap_zone"] = None
        coordinator.async_set_updated_data(stripped)
        await hass.async_block_till_done()
        assert hass.states.get(CHEAP_START).state == "unavailable"

        await tick(hass, frozen, at(DAY, 14, 15, 3))

        assert hhmm(hass, CHEAP_START) == "12:30"
    finally:
        freezer.stop()


# --- Rollover and DST -------------------------------------------------------


async def test_midnight_rollover_replaces_yesterdays_zone(hass, entry, api):
    """After midnight the zone belongs to the new day, at no request cost."""
    start = at(DAY, 23, 59)
    freezer, frozen = await setup_at(hass, entry, start)
    try:
        before = datetime.fromisoformat(hass.states.get(CHEAP_START).state)
        assert dt_util.as_local(before).date() == DAY
        calls_before = len(api.calls)

        await tick(hass, frozen, at(DAY + timedelta(days=1), 0, 0, 3))

        after = datetime.fromisoformat(hass.states.get(CHEAP_START).state)
        assert dt_util.as_local(after).date() == DAY + timedelta(days=1)
        assert hhmm(hass, CHEAP_START) == "12:30"
        # Tomorrow was already cached that afternoon: the new day's zone costs
        # nothing extra.
        assert len(api.calls) == calls_before
    finally:
        freezer.stop()


async def test_zone_on_the_fall_back_day(hass, entry, api):
    """The 25-hour, 100-quarter day still yields well-formed, disjoint zones."""
    freezer, _ = await setup_at(hass, entry, at(FALL_BACK, 14, 7))
    try:
        assert int(hass.states.get("sensor.frank_prices_today").state) == 100

        cheap = hass.states.get(CHEAP_START).attributes
        expensive = hass.states.get(EXPENSIVE_START).attributes
        # Real windows inside the day, never the whole 25 hours.
        assert 0 < cheap["quarter_count"] < 100
        assert 0 < expensive["quarter_count"] < 100
        assert cheap["threshold_eur_kwh"] < expensive["threshold_eur_kwh"]
        # Duration is measured on absolute instants, so it is a whole number of
        # quarters even across the repeated hour.
        assert cheap["zone_duration_minutes"] == cheap["quarter_count"] * 15
        assert expensive["zone_duration_minutes"] == expensive["quarter_count"] * 15
        # And the two period sensors cannot both be on.
        states = {
            hass.states.get(CHEAP_PERIOD).state,
            hass.states.get(EXPENSIVE_PERIOD).state,
        }
        assert states != {"on"}
    finally:
        freezer.stop()


# --- Configured margins -----------------------------------------------------


def _entry_with_margins(cheap: float, expensive: float) -> MockConfigEntry:
    """Return an entry configured with explicit zone margins."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Frank Quarter Prices (NL)",
        data={"country": "NL"},
        options={
            CONF_CHEAP_ZONE_MARGIN_PERCENT: cheap,
            CONF_EXPENSIVE_ZONE_MARGIN_PERCENT: expensive,
        },
        unique_id="NL",
    )


async def test_wider_cheap_margin_extends_the_published_zone(hass, api):
    """At 40% the 15:15-15:45 tail joins the run; at the default 15% it does not.

    Day minimum 0.18935: the 15% threshold is 0.217753 (tail excluded) and the
    40% threshold is 0.265090 (tail included).
    """
    freezer, _ = await setup_at(hass, _entry_with_margins(40.0, 15.0), at(DAY, 14, 7))
    try:
        attrs = hass.states.get(CHEAP_START).attributes
        assert attrs["margin_percent"] == 40.0
        assert attrs["quarter_count"] == 13
        assert hhmm(hass, CHEAP_START) == "12:30"
        assert hhmm(hass, CHEAP_END) == "15:45"
        # The expensive zone is untouched by the cheap margin.
        assert hass.states.get(EXPENSIVE_START).attributes["quarter_count"] == 3
    finally:
        freezer.stop()


async def test_wider_expensive_margin_extends_the_published_zone(hass, api):
    """At 30% the 20:30-21:00 shoulder joins the peak; at 15% it does not.

    Day range 0.14700-0.46765, spread 0.32065. The 15% threshold is 0.419553
    (shoulder at 0.39505 excluded) and the 30% threshold is 0.371455 (included).
    """
    freezer, _ = await setup_at(hass, _entry_with_margins(15.0, 30.0), at(DAY, 14, 7))
    try:
        attrs = hass.states.get(EXPENSIVE_START).attributes
        assert attrs["margin_percent"] == 30.0
        assert attrs["threshold_eur_kwh"] == pytest.approx(0.371455)
        assert attrs["quarter_count"] == 5
        assert hhmm(hass, EXPENSIVE_START) == "19:45"
        assert hhmm(hass, EXPENSIVE_END) == "21:00"
        # The cheap zone is untouched by the expensive margin.
        assert hass.states.get(CHEAP_START).attributes["quarter_count"] == 11
    finally:
        freezer.stop()


async def test_zero_margin_keeps_only_the_day_extreme(hass, api):
    """0% selects just the quarters priced exactly at the day's own extreme."""
    freezer, _ = await setup_at(hass, _entry_with_margins(0.0, 0.0), at(DAY, 14, 7))
    try:
        cheap_attrs = hass.states.get(CHEAP_START).attributes
        assert cheap_attrs["margin_percent"] == 0.0
        assert cheap_attrs["threshold_eur_kwh"] == cheap_attrs["day_min_price"]
        assert cheap_attrs["quarter_count"] == 11

        expensive_attrs = hass.states.get(EXPENSIVE_START).attributes
        assert expensive_attrs["threshold_eur_kwh"] == expensive_attrs["day_max_price"]
        assert expensive_attrs["quarter_count"] == 3
        assert hhmm(hass, EXPENSIVE_START) == "19:45"
    finally:
        freezer.stop()


async def test_margin_change_moves_every_derived_value_including_the_binary_state(
    hass, api
):
    """A margin change must move threshold, start, end, duration AND the ON/OFF state.

    At 15:20 the default 15% cheap zone (12:30-15:15) has just ended, so the
    cheap period sensor is OFF. Widening the cheap margin to 40% pulls the
    15:15-15:45 tail into the run, and the very same sensor must read ON. This
    is the end-to-end proof that the configured percentage really drives all six
    entities and not just a displayed attribute.
    """
    config_entry = _entry_with_margins(15.0, 15.0)
    freezer, _ = await setup_at(hass, config_entry, at(DAY, 15, 20, 3))
    try:
        default = hass.states.get(CHEAP_START).attributes
        assert default["margin_percent"] == 15.0
        assert default["zone_duration_minutes"] == 165
        assert hhmm(hass, CHEAP_START) == "12:30"
        assert hhmm(hass, CHEAP_END) == "15:15"
        assert hass.states.get(CHEAP_PERIOD).state == "off"
        default_threshold = default["threshold_eur_kwh"]

        # Change the option on the live entry, exactly as saving the options
        # form does, and let the normal reload run.
        hass.config_entries.async_update_entry(
            config_entry,
            options={
                CONF_CHEAP_ZONE_MARGIN_PERCENT: 40.0,
                CONF_EXPENSIVE_ZONE_MARGIN_PERCENT: 15.0,
            },
        )
        await hass.async_block_till_done()

        widened = hass.states.get(CHEAP_START).attributes
        assert widened["margin_percent"] == 40.0
        assert widened["threshold_eur_kwh"] > default_threshold
        assert widened["zone_duration_minutes"] == 195
        assert hhmm(hass, CHEAP_START) == "12:30"
        assert hhmm(hass, CHEAP_END) == "15:45"
        # The whole point: the binary sensor followed the configuration.
        assert hass.states.get(CHEAP_PERIOD).state == "on"
        # And it still agrees with its own boundary sensors.
        period = hass.states.get(CHEAP_PERIOD).attributes
        assert period["zone_start"] == widened["zone_start"]
        assert period["zone_end"] == widened["zone_end"]
        assert period["threshold_eur_kwh"] == widened["threshold_eur_kwh"]
        assert period["margin_percent"] == 40.0
        # The two bands still cannot meet.
        assert (
            widened["threshold_eur_kwh"]
            < hass.states.get(EXPENSIVE_START).attributes["threshold_eur_kwh"]
        )
    finally:
        freezer.stop()
