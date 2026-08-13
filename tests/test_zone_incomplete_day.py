"""Safety tests: an incomplete day must never publish a daily price zone.

A zone answers "when is the cheapest stretch of *today*". Derived from a partial
list it would silently answer a different question — the cheapest stretch of
whatever happened to arrive — and an EMS acting on it could charge at what is
really an expensive hour. So the coordinator gates the derivation on its own
authoritative completeness set (``_complete_days``, validated by
``_covers_full_market_day`` against the real market-midnight-to-market-
midnight span), never on a block count and never on a second, weaker notion of "enough
data".

Everything here therefore drives the *coordinator*, not the pure algorithm: the
algorithm in ``price_zone.py`` will happily derive a zone from any list it is
handed, and that is correct — the completeness decision belongs in exactly one
place.
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

from custom_components.frank_quarter_prices.const import DOMAIN
from custom_components.frank_quarter_prices.frank_client import FrankClientError

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

PRICES_TODAY = "sensor.frank_prices_today"

_CLIENT_METHOD = (
    "custom_components.frank_quarter_prices.frank_client."
    "FrankClient.async_get_prices_for_date"
)

DAY = date(2026, 8, 6)  # 96 quarters
SPRING_FORWARD = date(2026, 3, 29)  # 23-hour local day ->  92 quarters
FALL_BACK = date(2026, 10, 25)  # 25-hour local day -> 100 quarters


class FakeApi:
    """Client stand-in serving a configured response per date."""

    def __init__(self) -> None:
        """Initialize serving complete days for every date."""
        self.calls: list[date] = []
        self.responses: dict[date, Any] = {}

    def count(self, day: date) -> int:
        """Return how many times ``day`` was requested."""
        return self.calls.count(day)

    async def fetch(self, target_date: date) -> dict[str, Any]:
        """Serve the configured response, or a complete local day."""
        self.calls.append(target_date)
        response = self.responses.get(target_date)
        if isinstance(response, Exception):
            raise response
        if response is not None:
            return {"prices": list(response)}
        return {"prices": build_local_day_blocks(target_date, None)}


@pytest.fixture(autouse=True)
async def local_timezone(hass):
    """Put Home Assistant on Europe/Amsterdam before any list is built."""
    await hass.config.async_set_time_zone(TEST_TIMEZONE)


@pytest.fixture
def api():
    """Patch the client with the configurable fake."""
    fake = FakeApi()
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
    freezer = freeze_time(start)
    frozen = freezer.start()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return freezer, frozen


async def tick(hass, frozen, moment: datetime) -> None:
    """Advance the frozen clock and fire the scheduled listeners."""
    frozen.move_to(moment)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def assert_no_zone(hass) -> None:
    """Assert all six zone entities are unavailable and leak nothing.

    Being unavailable is only half the guarantee: a leftover ``zone_start`` or
    ``threshold_eur_kwh`` attribute would still be readable from a template and
    would still be wrong, so the attributes must be gone too.
    """
    leaking = {
        "time",
        "zone_start",
        "zone_end",
        "margin_percent",
        "threshold_eur_kwh",
        "day_min_price",
        "day_max_price",
        "zone_duration_minutes",
        "quarter_count",
    }
    for entity_id in ZONE_ENTITIES:
        state = hass.states.get(entity_id)
        assert state is not None, f"{entity_id} was not created at all"
        assert state.state == "unavailable", (
            f"{entity_id} published {state.state!r} from an incomplete day"
        )
        stale = leaking & set(state.attributes)
        assert not stale, f"{entity_id} still exposes stale zone attributes: {stale}"


def assert_zone_published(hass) -> None:
    """Assert all six zone entities carry a usable value."""
    for entity_id in ZONE_ENTITIES:
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.state not in ("unavailable", "unknown"), entity_id


# --- A. Cold start with partial data, no complete cache ---------------------


async def test_cold_start_with_partial_today_publishes_no_zone(hass, entry, api):
    """20 of 96 quarters must not become "today's cheapest stretch"."""
    api.responses[DAY] = build_local_day_blocks(DAY, None)[:20]  # 00:00 .. 05:00

    freezer, _ = await setup_at(hass, entry, at(DAY, 3, 7))
    try:
        # The partial data is still published as prices_today (v0.1.5 policy).
        assert int(hass.states.get(PRICES_TODAY).state) == 20
        # But it must not masquerade as a whole-day zone.
        assert_no_zone(hass)
    finally:
        freezer.stop()


async def test_morning_only_data_publishes_no_zone(hass, entry, api):
    """Only the morning published: the afternoon peak is simply unknown."""
    api.responses[DAY] = build_local_day_blocks(DAY, None)[:48]  # 00:00 .. 12:00

    freezer, _ = await setup_at(hass, entry, at(DAY, 10, 7))
    try:
        assert int(hass.states.get(PRICES_TODAY).state) == 48
        assert_no_zone(hass)
    finally:
        freezer.stop()


async def test_partial_today_still_serves_the_current_price(hass, entry, api):
    """Gating the zones must not take the rest of the integration down."""
    api.responses[DAY] = build_local_day_blocks(DAY, None)[:48]

    freezer, _ = await setup_at(hass, entry, at(DAY, 10, 7))
    try:
        assert hass.states.get("sensor.frank_current_price").state != "unavailable"
        assert hass.states.get("sensor.frank_cheapest_today").state != "unavailable"
        assert_no_zone(hass)
    finally:
        freezer.stop()


async def test_zone_appears_once_the_day_completes(hass, entry, api):
    """A day that fills in later starts publishing zones at that moment."""
    api.responses[DAY] = build_local_day_blocks(DAY, None)[:48]

    freezer, frozen = await setup_at(hass, entry, at(DAY, 10, 7))
    try:
        assert_no_zone(hass)

        # The next tick gets the complete day.
        del api.responses[DAY]
        await tick(hass, frozen, at(DAY, 10, 15, 3))

        assert int(hass.states.get(PRICES_TODAY).state) == 96
        assert_zone_published(hass)
    finally:
        freezer.stop()


# --- B. Complete cache survives a network outage ----------------------------


async def test_complete_cache_keeps_zones_through_an_outage(hass, entry, api):
    """A known-good complete day keeps producing zones while the API is down."""
    freezer, frozen = await setup_at(hass, entry, at(DAY, 10, 7))
    try:
        assert_zone_published(hass)
        before = hass.states.get(CHEAP_START).state

        api.responses[DAY] = FrankClientError("outage")
        api.responses[DAY + timedelta(days=1)] = FrankClientError("outage")
        for hour in (10, 11, 12):
            await tick(hass, frozen, at(DAY, hour, 30, 3))

        assert_zone_published(hass)
        assert hass.states.get(CHEAP_START).state == before
    finally:
        freezer.stop()


# --- C. A later partial response must not displace a complete day -----------


async def test_partial_response_cannot_replace_a_complete_day(hass, entry, api):
    """The complete cached day stays authoritative; the zone does not move."""
    freezer, frozen = await setup_at(hass, entry, at(DAY, 10, 7))
    try:
        assert_zone_published(hass)
        before_start = hass.states.get(CHEAP_START).state
        before_attrs = dict(hass.states.get(CHEAP_START).attributes)
        calls_before = api.count(DAY)

        # Even if the API would now answer with a stub, a complete day is never
        # re-requested — and if it somehow were, the stub must not win.
        api.responses[DAY] = build_local_day_blocks(DAY, None)[:4]
        for hour in (11, 12, 13):
            await tick(hass, frozen, at(DAY, hour, 0, 3))

        assert api.count(DAY) == calls_before  # never re-fetched
        assert int(hass.states.get(PRICES_TODAY).state) == 96
        assert hass.states.get(CHEAP_START).state == before_start
        assert (
            hass.states.get(CHEAP_START).attributes["quarter_count"]
            == (before_attrs["quarter_count"])
        )
        assert_zone_published(hass)
    finally:
        freezer.stop()


# --- D/E/H. Not-quite-complete days -----------------------------------------


async def test_ninety_five_of_ninety_six_quarters_publishes_no_zone(hass, entry, api):
    """One quarter short of the day is still not the day."""
    api.responses[DAY] = build_local_day_blocks(DAY, None)[:-1]  # 95 blocks

    freezer, _ = await setup_at(hass, entry, at(DAY, 10, 7))
    try:
        assert int(hass.states.get(PRICES_TODAY).state) == 95
        assert_no_zone(hass)
    finally:
        freezer.stop()


async def test_missing_first_quarter_publishes_no_zone(hass, entry, api):
    """A day that starts at 00:15 does not cover the local day."""
    api.responses[DAY] = build_local_day_blocks(DAY, None)[1:]

    freezer, _ = await setup_at(hass, entry, at(DAY, 10, 7))
    try:
        assert_no_zone(hass)
    finally:
        freezer.stop()


async def test_missing_middle_quarter_publishes_no_zone(hass, entry, api):
    """A hole at 10:00 breaks the day even though 95 blocks arrived."""
    blocks = build_local_day_blocks(DAY, None)
    del blocks[40]
    api.responses[DAY] = blocks

    freezer, _ = await setup_at(hass, entry, at(DAY, 3, 7))
    try:
        assert int(hass.states.get(PRICES_TODAY).state) == 95
        assert_no_zone(hass)
    finally:
        freezer.stop()


async def test_gap_with_the_right_block_count_publishes_no_zone(hass, entry, api):
    """96 blocks with a hole is not a complete day.

    Completeness is coverage, never ``len(prices) == 96``: this list has the
    canonical block count and would sail through a count-based check.
    """
    blocks = build_local_day_blocks(DAY, None)
    del blocks[40]  # 10:00 disappears
    blocks.append(blocks[39])  # duplicate 09:45 restores the count to 96
    api.responses[DAY] = blocks

    freezer, _ = await setup_at(hass, entry, at(DAY, 3, 7))
    try:
        assert int(hass.states.get(PRICES_TODAY).state) == 96
        assert_no_zone(hass)
    finally:
        freezer.stop()


async def test_overlap_with_the_right_block_count_publishes_no_zone(hass, entry, api):
    """96 blocks with an overlap is not a complete day either."""
    blocks = build_local_day_blocks(DAY, None)
    # Stretch 10:00 to run until 10:30, overlapping the 10:15 block.
    blocks[40] = build_block_span(blocks[40]["from"], blocks[41]["till"], 0.08)
    api.responses[DAY] = blocks

    freezer, _ = await setup_at(hass, entry, at(DAY, 3, 7))
    try:
        assert int(hass.states.get(PRICES_TODAY).state) == 96
        assert_no_zone(hass)
    finally:
        freezer.stop()


# --- F/G. DST days are complete at 92 and 100 quarters ----------------------


@pytest.mark.parametrize(
    ("day", "expected_blocks"),
    [(SPRING_FORWARD, 92), (DAY, 96), (FALL_BACK, 100)],
)
async def test_complete_dst_days_publish_zones(hass, entry, api, day, expected_blocks):
    """92-, 96- and 100-quarter days are all complete market days."""
    freezer, _ = await setup_at(hass, entry, at(day, 14, 7))
    try:
        assert int(hass.states.get(PRICES_TODAY).state) == expected_blocks
        assert_zone_published(hass)
        # Both zones are real windows inside the day, never the whole day.
        cheap = hass.states.get(CHEAP_START).attributes
        expensive = hass.states.get(EXPENSIVE_START).attributes
        assert 0 < cheap["quarter_count"] < expected_blocks
        assert 0 < expensive["quarter_count"] < expected_blocks
        assert cheap["threshold_eur_kwh"] < expensive["threshold_eur_kwh"]
    finally:
        freezer.stop()


@pytest.mark.parametrize("day", [SPRING_FORWARD, FALL_BACK])
async def test_dst_day_short_by_one_quarter_publishes_no_zone(hass, entry, api, day):
    """A DST day is judged on coverage too, not on 92/100 as magic numbers."""
    api.responses[day] = build_local_day_blocks(day, None)[:-1]

    freezer, _ = await setup_at(hass, entry, at(day, 14, 7))
    try:
        assert_no_zone(hass)
    finally:
        freezer.stop()


async def test_ninety_six_blocks_on_a_dst_day_is_not_complete(hass, entry, api):
    """96 blocks on the 100-quarter fall-back day must be rejected.

    The clearest possible refutation of a count-based completeness check: on
    this day 96 blocks is *not* the day.
    """
    api.responses[FALL_BACK] = build_local_day_blocks(FALL_BACK, None)[:96]

    freezer, _ = await setup_at(hass, entry, at(FALL_BACK, 14, 7))
    try:
        assert int(hass.states.get(PRICES_TODAY).state) == 96
        assert_no_zone(hass)
    finally:
        freezer.stop()


# --- Midnight rollover ------------------------------------------------------


async def test_rollover_into_a_complete_day_republishes_zones(hass, entry, api):
    """Yesterday's cached tomorrow becomes today's zone, free of charge."""
    freezer, frozen = await setup_at(hass, entry, at(DAY, 23, 45, 3))
    try:
        assert_zone_published(hass)
        before = datetime.fromisoformat(hass.states.get(CHEAP_START).state)
        assert dt_util.as_local(before).date() == DAY
        calls_before = len(api.calls)

        await tick(hass, frozen, at(DAY + timedelta(days=1), 0, 0, 3))

        after = datetime.fromisoformat(hass.states.get(CHEAP_START).state)
        assert dt_util.as_local(after).date() == DAY + timedelta(days=1)
        assert len(api.calls) == calls_before
    finally:
        freezer.stop()


async def test_rollover_into_an_incomplete_day_drops_the_zone(hass, entry, api):
    """Yesterday's zone must never survive into a day that is not yet known.

    The new day is only partially published at 00:00, so the honest answer is
    "unknown" — not yesterday's 12:30-15:15.
    """
    tomorrow = DAY + timedelta(days=1)
    # Tomorrow is never published complete: not in the afternoon, not after
    # midnight either.
    api.responses[tomorrow] = build_local_day_blocks(tomorrow, None)[:8]

    freezer, frozen = await setup_at(hass, entry, at(DAY, 23, 45, 3))
    try:
        assert_zone_published(hass)
        yesterday_zone = hass.states.get(CHEAP_START).state

        await tick(hass, frozen, at(tomorrow, 0, 0, 3))

        assert_no_zone(hass)
        # And emphatically not yesterday's window under a new date.
        assert hass.states.get(CHEAP_START).state != yesterday_zone
    finally:
        freezer.stop()


async def test_rollover_into_an_incomplete_day_then_completing_it(hass, entry, api):
    """Once the new day completes, the zone returns for the new day."""
    tomorrow = DAY + timedelta(days=1)
    api.responses[tomorrow] = build_local_day_blocks(tomorrow, None)[:8]

    freezer, frozen = await setup_at(hass, entry, at(DAY, 23, 45, 3))
    try:
        await tick(hass, frozen, at(tomorrow, 0, 0, 3))
        assert_no_zone(hass)

        del api.responses[tomorrow]
        await tick(hass, frozen, at(tomorrow, 0, 15, 3))

        assert_zone_published(hass)
        published = datetime.fromisoformat(hass.states.get(CHEAP_START).state)
        assert dt_util.as_local(published).date() == tomorrow
    finally:
        freezer.stop()


# --- The completeness source of truth is shared, not duplicated -------------


async def test_zone_gating_uses_the_coordinator_completeness_set(hass, entry, api):
    """The gate is the v0.1.5 ``_complete_days`` set, not a second definition."""
    api.responses[DAY] = build_local_day_blocks(DAY, None)[:48]

    freezer, frozen = await setup_at(hass, entry, at(DAY, 10, 7))
    try:
        coordinator = entry.runtime_data
        assert DAY not in coordinator._complete_days
        assert coordinator.data["cheap_zone"] is None
        assert coordinator.data["expensive_zone"] is None
        assert coordinator.get_cheap_zone() is None
        assert coordinator.get_expensive_zone() is None

        del api.responses[DAY]
        await tick(hass, frozen, at(DAY, 10, 15, 3))

        assert DAY in coordinator._complete_days
        assert coordinator.data["cheap_zone"] is not None
        assert coordinator.data["expensive_zone"] is not None
    finally:
        freezer.stop()
