"""Contract tests for ``sensor.frank_current_return_price``.

v0.1.6 deliberately leaves the feed-in calculation as released in v0.1.3: the
verified raw ``market_price`` plus the configured adjustment, optionally
including 21% VAT. The public Frank API exposes no feed-in field, and
``sourcing_markup_price`` was re-verified against the live API as a component
of the consumer *purchase* price (see the v0.1.6 review notes), so it is not
used here.

These tests pin the surrounding behaviour that the release notes claim: the
value always follows the currently active quarter, survives an outage on cached
data, ignores tomorrow, and goes unavailable rather than stale.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from freezegun import freeze_time
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.frank_quarter_prices.const import (
    CONF_APPLY_FEED_IN_VAT,
    CONF_FEED_IN_ADJUSTMENT,
    DOMAIN,
)

from .conftest import TEST_TIMEZONE, build_block_span, build_local_day_blocks

RETURN_PRICE = "sensor.frank_current_return_price"
CURRENT_PRICE = "sensor.frank_current_price"

_CLIENT_METHOD = (
    "custom_components.frank_quarter_prices.frank_client."
    "FrankClient.async_get_prices_for_date"
)

DAY = date(2026, 8, 6)
FALL_BACK = date(2026, 10, 25)


def stepped_day(day: date, base: float = 0.10) -> list[dict[str, Any]]:
    """Return a day whose every quarter carries a distinct market price."""
    return [
        build_block_span(block["from"], block["till"], round(base + index * 0.001, 6))
        for index, block in enumerate(build_local_day_blocks(day))
    ]


class StepApi:
    """Client stand-in serving a stepped day and recording every request."""

    def __init__(self) -> None:
        """Initialize with an empty call log and no forced failure."""
        self.calls: list[date] = []
        self.responses: dict[date, Any] = {}
        self.failing = False

    async def fetch(self, target_date: date) -> dict[str, Any]:
        """Serve the configured response, or fail while the outage lasts."""
        self.calls.append(target_date)
        if self.failing:
            from custom_components.frank_quarter_prices.frank_client import (
                FrankClientError,
            )

            raise FrankClientError("simulated outage")
        override = self.responses.get(target_date)
        if override is not None:
            return {"prices": list(override)}
        return {"prices": stepped_day(target_date)}


@pytest.fixture(autouse=True)
async def local_timezone(hass):
    """Put Home Assistant on Europe/Amsterdam before anything else runs.

    ``build_local_day_blocks`` resolves local midnight through the configured
    default timezone, so a test that prepares block lists in its body must have
    the zone set first — otherwise it silently builds a UTC day and every block
    index is offset.
    """
    await hass.config.async_set_time_zone(TEST_TIMEZONE)


@pytest.fixture
def api():
    """Patch the client with the stepped, recording fake."""
    fake = StepApi()
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


# --- Source of the value ----------------------------------------------------


async def test_value_comes_from_the_current_quarter_only(hass, entry, api):
    """The value is the active quarter's market price, not any other quarter's."""
    freezer, _ = await setup_at(hass, entry, at(DAY, 10, 7))
    try:
        # 10:07 falls in the 10:00 block -> index 40 -> 0.10 + 40*0.001.
        assert float(hass.states.get(RETURN_PRICE).state) == pytest.approx(0.14)
        assert hass.states.get(RETURN_PRICE).attributes["market_price_source"] == (
            "market_price"
        )
    finally:
        freezer.stop()


async def test_purchase_side_components_never_leak_into_the_value(hass, entry, api):
    """The feed-in value stays the raw market price, well below the all-in price.

    ``market_price_tax``, ``sourcing_markup_price`` and ``energy_tax_price`` are
    purchase-side components; none of them may appear in the feed-in value.
    """
    freezer, _ = await setup_at(hass, entry, at(DAY, 10, 7))
    try:
        block = hass.states.get(CURRENT_PRICE).attributes["full_block"]
        feed_in = float(hass.states.get(RETURN_PRICE).state)

        assert feed_in == pytest.approx(block["market_price"])
        assert feed_in != pytest.approx(block["total_price_eur_kwh"])
        assert feed_in < block["total_price_eur_kwh"]
    finally:
        freezer.stop()


# --- Quarter rollover -------------------------------------------------------


async def test_value_follows_the_quarter_boundary(hass, entry, api):
    """Crossing a boundary moves the value to the new quarter, with no request."""
    freezer, frozen = await setup_at(hass, entry, at(DAY, 10, 7))
    try:
        calls_before = len(api.calls)
        assert float(hass.states.get(RETURN_PRICE).state) == pytest.approx(0.14)

        await tick(hass, frozen, at(DAY, 10, 15, 3))
        assert float(hass.states.get(RETURN_PRICE).state) == pytest.approx(0.141)

        await tick(hass, frozen, at(DAY, 10, 30, 3))
        assert float(hass.states.get(RETURN_PRICE).state) == pytest.approx(0.142)

        assert len(api.calls) == calls_before
    finally:
        freezer.stop()


async def test_value_rolls_over_at_midnight(hass, entry, api):
    """After midnight the value comes from the new day's first quarter."""
    freezer, frozen = await setup_at(hass, entry, at(DAY, 23, 45, 3))
    try:
        assert float(hass.states.get(RETURN_PRICE).state) == pytest.approx(0.195)

        await tick(hass, frozen, at(DAY + timedelta(days=1), 0, 0, 3))

        assert float(hass.states.get(RETURN_PRICE).state) == pytest.approx(0.10)
    finally:
        freezer.stop()


# --- Cached data and outages -------------------------------------------------


async def test_cached_data_keeps_the_value_during_an_outage(hass, entry, api):
    """With today cached, an API outage cannot blank the feed-in price."""
    freezer, frozen = await setup_at(hass, entry, at(DAY, 10, 7))
    try:
        api.failing = True

        await tick(hass, frozen, at(DAY, 10, 15, 3))

        state = hass.states.get(RETURN_PRICE)
        assert state.state != "unavailable"
        assert float(state.state) == pytest.approx(0.141)
    finally:
        freezer.stop()


async def test_tomorrow_does_not_influence_the_current_value(hass, entry, api):
    """Tomorrow's prices are published but never feed the current value."""
    tomorrow = DAY + timedelta(days=1)
    # Tomorrow is an order of magnitude more expensive; the value must ignore it.
    api.responses[tomorrow] = stepped_day(tomorrow, base=9.0)

    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        assert hass.states.get("sensor.frank_prices_tomorrow").state == "96"
        # 14:07 -> the 14:00 block -> index 56.
        assert float(hass.states.get(RETURN_PRICE).state) == pytest.approx(0.156)
    finally:
        freezer.stop()


async def test_unavailable_when_the_active_quarter_is_missing(hass, entry, api):
    """A day without the active quarter yields unavailable, never a stale value.

    A partial list that stops before "now" must not silently hand over the last
    quarter it does contain.
    """
    # Only the morning is published; setup happens in the afternoon.
    api.responses[DAY] = stepped_day(DAY)[:20]  # 00:00 .. 05:00

    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        # The feed-in sensor overrides ``available``, so it reports
        # ``unavailable``; the purchase-price sensor reports ``unknown``. Both
        # are v0.1.5 behaviour and neither publishes a stale number.
        assert hass.states.get(RETURN_PRICE).state == "unavailable"
        assert hass.states.get(CURRENT_PRICE).state == "unknown"
    finally:
        freezer.stop()


async def test_no_stale_value_when_the_next_quarter_is_missing(hass, entry, api):
    """Crossing into a missing quarter drops the value instead of holding it."""
    blocks = stepped_day(DAY)
    del blocks[41]  # 10:15 is missing
    api.responses[DAY] = blocks

    freezer, frozen = await setup_at(hass, entry, at(DAY, 10, 7))
    try:
        assert float(hass.states.get(RETURN_PRICE).state) == pytest.approx(0.14)

        await tick(hass, frozen, at(DAY, 10, 15, 3))

        assert hass.states.get(RETURN_PRICE).state == "unavailable"
    finally:
        freezer.stop()


# --- Negative and zero prices -----------------------------------------------


@pytest.mark.parametrize("market_price", [-0.05, 0.0, 0.08])
async def test_negative_and_zero_market_prices_are_published_unclamped(
    hass, entry, api, market_price
):
    """A negative feed-in price is a real outcome and is never clamped to zero."""
    api.responses[DAY] = [
        build_block_span(block["from"], block["till"], market_price)
        for block in build_local_day_blocks(DAY)
    ]

    freezer, _ = await setup_at(hass, entry, at(DAY, 10, 7))
    try:
        assert float(hass.states.get(RETURN_PRICE).state) == pytest.approx(market_price)
    finally:
        freezer.stop()


# --- VAT option --------------------------------------------------------------


@pytest.mark.parametrize(
    ("apply_vat", "adjustment", "expected"),
    [
        (False, 0.0, 0.14),
        (True, 0.0, round(0.14 * 1.21, 6)),
        (False, 0.018, round(0.158, 6)),
        (True, 0.018, round(0.158 * 1.21, 6)),
        (False, -0.017, round(0.123, 6)),
        (True, -0.017, round(0.123 * 1.21, 6)),
    ],
)
async def test_vat_and_adjustment_combinations(
    hass, api, apply_vat, adjustment, expected
):
    """VAT applies to the market price plus the adjustment, in every combination."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Frank Quarter Prices (NL)",
        data={"country": "NL"},
        options={
            CONF_APPLY_FEED_IN_VAT: apply_vat,
            CONF_FEED_IN_ADJUSTMENT: adjustment,
        },
        unique_id="NL",
    )
    freezer, _ = await setup_at(hass, entry, at(DAY, 10, 7))
    try:
        state = hass.states.get(RETURN_PRICE)
        assert float(state.state) == pytest.approx(expected)
        assert state.attributes["apply_vat"] is apply_vat
        assert state.attributes["feed_in_adjustment"] == adjustment
    finally:
        freezer.stop()


async def test_value_on_a_dst_day(hass, entry, api):
    """The 25-hour fall-back day publishes a value like any other day."""
    freezer, _ = await setup_at(hass, entry, at(FALL_BACK, 14, 7))
    try:
        assert int(hass.states.get("sensor.frank_prices_today").state) == 100
        state = hass.states.get(RETURN_PRICE)
        assert state.state != "unavailable"
        assert float(state.state) > 0
    finally:
        freezer.stop()
