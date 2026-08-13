"""Regression tests for the daily price cache (GitHub issue #3).

Issue #3: ``_async_update_data`` fetched today *and* tomorrow on every run.
With the wall-clock scheduling from #2 that is 96 runs a day — ~192 requests
for lists that change at most twice — and, worse, every price entity inherits
``CoordinatorEntity.available`` from ``last_update_success``, so one failed
request took every price sensor to ``unavailable`` at once.

The fix separates *fetching* the published daily lists from *deriving* the
active quarter: days are cached per local calendar date, only a missing day is
requested, and the active block is re-derived locally on every tick.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from freezegun import freeze_time
from homeassistant.config_entries import ConfigEntryState
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.frank_quarter_prices.const import (
    DOMAIN,
    TOMORROW_ERROR_BACKOFF_MINUTES,
    TOMORROW_PUBLISH_HOUR,
)
from custom_components.frank_quarter_prices.coordinator import (
    FrankQuarterPricesCoordinator,
)
from custom_components.frank_quarter_prices.frank_client import FrankClientError

from .conftest import TEST_TIMEZONE, build_block_span, build_local_day_blocks

CURRENT_PRICE = "sensor.frank_current_price"
PRICES_TODAY = "sensor.frank_prices_today"
PRICES_TOMORROW = "sensor.frank_prices_tomorrow"
TOMORROW_AVAILABLE = "binary_sensor.frank_tomorrow_prices_available"

_CLIENT_METHOD = (
    "custom_components.frank_quarter_prices.frank_client."
    "FrankClient.async_get_prices_for_date"
)

# Europe/Amsterdam DST transition dates used for the completeness tests.
SPRING_FORWARD = date(2026, 3, 29)  # 23-hour local day ->  92 quarters
FALL_BACK = date(2026, 10, 25)  # 25-hour local day -> 100 quarters


class FakeApi:
    """Stand-in for the Frank client that records every requested date.

    ``responses`` maps a date to what that date should return: a list of
    blocks, or an exception instance to raise. Anything not listed returns a
    complete local day.
    """

    def __init__(self) -> None:
        """Initialize an API that serves complete days for every date."""
        self.calls: list[date] = []
        self.responses: dict[date, Any] = {}

    def count(self, day: date) -> int:
        """Return how many times ``day`` has been requested."""
        return self.calls.count(day)

    async def fetch(self, target_date: date) -> dict[str, Any]:
        """Serve the configured response for ``target_date``."""
        self.calls.append(target_date)
        response = self.responses.get(target_date)
        if isinstance(response, Exception):
            raise response
        if response is not None:
            return {"prices": list(response)}
        return {"prices": build_local_day_blocks(target_date)}


@pytest.fixture(autouse=True)
async def local_timezone(hass):
    """Put Home Assistant on Europe/Amsterdam before anything else runs.

    ``build_local_day_blocks`` resolves local midnight through the configured
    default timezone, so tests that prepare block lists in their body must have
    the zone set first — otherwise they would build a day for the harness's
    default zone and no list would ever validate as complete.
    """
    await hass.config.async_set_time_zone(TEST_TIMEZONE)


@pytest.fixture
def api():
    """Patch the client with a recording fake and yield it."""
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


def at(year: int, month: int, day: int, hour: int, minute: int = 0, second: int = 0):
    """Return a local Europe/Amsterdam datetime."""
    return datetime(
        year,
        month,
        day,
        hour,
        minute,
        second,
        tzinfo=dt_util.get_time_zone(TEST_TIMEZONE),
    )


async def setup_at(hass, entry, start: datetime):
    """Set up the config entry with the clock frozen at ``start``.

    Returns the started freezegun controller; the caller stops it.
    """
    await hass.config.async_set_time_zone(TEST_TIMEZONE)
    freezer = freeze_time(start)
    frozen = freezer.start()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return freezer, frozen


async def tick(hass, frozen, moment: datetime) -> None:
    """Advance the frozen clock to ``moment`` and fire the scheduled listeners."""
    frozen.move_to(moment)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def tick_quarters(hass, frozen, start: datetime, count: int) -> datetime:
    """Fire ``count`` successive quarter ticks after ``start``; return the last."""
    moment = start.replace(second=3, microsecond=0)
    moment -= timedelta(minutes=moment.minute % 15)
    for _ in range(count):
        moment += timedelta(minutes=15)
        await tick(hass, frozen, moment)
    return moment


# --- A. Complete today cache avoids redundant refetch ----------------------


async def test_complete_today_cache_avoids_refetch(hass, entry, api):
    """A cached complete today is never requested again on a quarter tick."""
    start = at(2026, 8, 6, 14, 7)
    today = start.date()
    freezer, frozen = await setup_at(hass, entry, start)
    try:
        assert api.count(today) == 1

        await tick_quarters(hass, frozen, start, 8)  # 14:15 .. 16:00

        assert api.count(today) == 1
    finally:
        freezer.stop()


# --- B. Current quarter changes from cache ---------------------------------


async def test_current_quarter_derived_locally_without_fetch(hass, entry, api):
    """10:14 -> 10:15 must move the current price with no network request."""
    start = at(2026, 8, 6, 10, 14)
    today = start.date()
    # A distinct price per quarter so the active block is unambiguous.
    api.responses[today] = [
        build_block_span(block["from"], block["till"], round(0.10 + i * 0.001, 6))
        for i, block in enumerate(build_local_day_blocks(today))
    ]
    freezer, frozen = await setup_at(hass, entry, start)
    try:
        calls_before = len(api.calls)
        # 10:00 block -> index 40.
        before = float(hass.states.get(CURRENT_PRICE).state)

        await tick(hass, frozen, at(2026, 8, 6, 10, 15, 3))

        after = float(hass.states.get(CURRENT_PRICE).state)
        assert after != before
        assert hass.states.get(CURRENT_PRICE).attributes["time"] == "10:15"
        # Derived purely from the cache: not a single extra request.
        assert len(api.calls) == calls_before
    finally:
        freezer.stop()


# --- C. Tomorrow not requested before the publication gate -----------------


async def test_tomorrow_not_requested_before_publish_hour(hass, entry, api):
    """No tomorrow request happens all morning, setup included."""
    start = at(2026, 8, 6, 6, 5)
    tomorrow = start.date() + timedelta(days=1)
    freezer, frozen = await setup_at(hass, entry, start)
    try:
        assert api.count(tomorrow) == 0

        # Tick right up to the last quarter before the gate opens.
        await tick_quarters(hass, frozen, start, 23)  # 06:15 .. 11:45
        assert dt_util.now().hour < TOMORROW_PUBLISH_HOUR

        assert api.count(tomorrow) == 0
    finally:
        freezer.stop()


# --- D. Tomorrow requested once the gate opens -----------------------------


async def test_tomorrow_requested_at_publish_hour(hass, entry, api):
    """The first tick at/after the publication hour requests tomorrow."""
    start = at(2026, 8, 6, 11, 45)
    tomorrow = start.date() + timedelta(days=1)
    freezer, frozen = await setup_at(hass, entry, start)
    try:
        assert api.count(tomorrow) == 0

        await tick(hass, frozen, at(2026, 8, 6, 12, 0, 3))

        assert api.count(tomorrow) == 1
        assert hass.states.get(TOMORROW_AVAILABLE).state == "on"
    finally:
        freezer.stop()


# --- E. Complete tomorrow cache stops repeated fetches ---------------------


async def test_complete_tomorrow_cache_stops_refetch(hass, entry, api):
    """Once tomorrow is cached complete it is never requested again."""
    start = at(2026, 8, 6, 14, 7)
    tomorrow = start.date() + timedelta(days=1)
    freezer, frozen = await setup_at(hass, entry, start)
    try:
        assert api.count(tomorrow) == 1

        await tick_quarters(hass, frozen, start, 16)  # 14:15 .. 18:00

        assert api.count(tomorrow) == 1
    finally:
        freezer.stop()


# --- F. Tomorrow request failure is non-fatal ------------------------------


async def test_tomorrow_failure_keeps_every_today_entity_available(hass, entry, api):
    """A failing tomorrow request must not take the price entities down.

    This is the core of issue #3: the coordinator stays successful, so no
    entity inherits an ``unavailable`` state from ``last_update_success``.
    """
    start = at(2026, 8, 6, 14, 7)
    today = start.date()
    api.responses[today + timedelta(days=1)] = FrankClientError("upstream is down")

    freezer, frozen = await setup_at(hass, entry, start)
    try:
        coordinator = entry.runtime_data
        assert coordinator.last_update_success is True

        assert hass.states.get(CURRENT_PRICE).state not in ("unknown", "unavailable")
        today_state = hass.states.get(PRICES_TODAY)
        assert today_state.state != "unavailable"
        assert len(today_state.attributes["prices"]) == 96
        # Only tomorrow itself reports the absence.
        assert hass.states.get(TOMORROW_AVAILABLE).state == "off"
        assert hass.states.get(PRICES_TOMORROW).state == "unavailable"

        # Still true after further ticks, and today is never re-requested.
        await tick_quarters(hass, frozen, start, 4)
        assert coordinator.last_update_success is True
        assert api.count(today) == 1
        assert hass.states.get(CURRENT_PRICE).state not in ("unknown", "unavailable")
    finally:
        freezer.stop()


async def test_tomorrow_error_is_retried_next_tick_then_backs_off(hass, entry, api):
    """One failure retries immediately; sustained failure drops to a backoff."""
    start = at(2026, 8, 6, 12, 0)
    tomorrow = start.date() + timedelta(days=1)
    api.responses[tomorrow] = FrankClientError("upstream is down")

    freezer, frozen = await setup_at(hass, entry, start)
    try:
        assert api.count(tomorrow) == 1  # first attempt, failed

        # A single blip must not delay recovery: retried on the very next tick.
        await tick(hass, frozen, at(2026, 8, 6, 12, 15, 3))
        assert api.count(tomorrow) == 2

        # From the second consecutive failure the backoff engages: the tick
        # inside the window is skipped entirely.
        await tick(hass, frozen, at(2026, 8, 6, 12, 30, 3))
        assert api.count(tomorrow) == 2

        # ...and lifts once the window has passed (12:15 + 30 min).
        after_backoff = at(2026, 8, 6, 12, 15, 3) + timedelta(
            minutes=TOMORROW_ERROR_BACKOFF_MINUTES
        )
        assert after_backoff == at(2026, 8, 6, 12, 45, 3)
        await tick(hass, frozen, after_backoff)
        assert api.count(tomorrow) == 3

        await tick(hass, frozen, at(2026, 8, 6, 13, 0, 3))
        assert api.count(tomorrow) == 3

        # Recovery clears the backoff and the day is cached for good.
        del api.responses[tomorrow]
        await tick(hass, frozen, at(2026, 8, 6, 13, 15, 3))
        assert api.count(tomorrow) == 4
        assert hass.states.get(TOMORROW_AVAILABLE).state == "on"

        await tick(hass, frozen, at(2026, 8, 6, 13, 30, 3))
        assert api.count(tomorrow) == 4
    finally:
        freezer.stop()


async def test_sustained_tomorrow_outage_is_rate_limited(hass, entry, api):
    """A full afternoon of failures costs a bounded number of requests."""
    start = at(2026, 8, 6, 12, 0)
    tomorrow = start.date() + timedelta(days=1)
    api.responses[tomorrow] = FrankClientError("upstream is down")

    freezer, frozen = await setup_at(hass, entry, start)
    try:
        await tick_quarters(hass, frozen, start, 47)  # 12:15 .. 23:45

        # Roughly two attempts an hour rather than four, and far below the 48
        # a per-tick retry would have made.
        assert api.count(tomorrow) <= 26
        assert entry.runtime_data.last_update_success is True
    finally:
        freezer.stop()


# --- G. Today request fails while valid data is cached ---------------------


async def test_today_failure_never_attempted_while_complete_cache_exists(
    hass, entry, api
):
    """A complete today is served from cache, so an outage cannot even reach it."""
    start = at(2026, 8, 6, 14, 7)
    today = start.date()
    freezer, frozen = await setup_at(hass, entry, start)
    try:
        expected = hass.states.get(CURRENT_PRICE).state

        # The whole API goes down after the initial fetch.
        api.responses[today] = FrankClientError("upstream is down")
        api.responses[today + timedelta(days=1)] = FrankClientError("upstream is down")

        await tick_quarters(hass, frozen, start, 4)

        assert entry.runtime_data.last_update_success is True
        assert api.count(today) == 1  # never re-requested
        assert hass.states.get(CURRENT_PRICE).state == expected
        assert len(hass.states.get(PRICES_TODAY).attributes["prices"]) == 96
    finally:
        freezer.stop()


async def test_today_failure_preserves_partial_cache(hass, entry, api):
    """An incomplete today is retried, and a failed retry keeps what is known."""
    start = at(2026, 8, 6, 14, 7)
    today = start.date()
    # Only the first half of the day is published.
    api.responses[today] = build_local_day_blocks(today)[:60]

    freezer, frozen = await setup_at(hass, entry, start)
    try:
        assert len(hass.states.get(PRICES_TODAY).attributes["prices"]) == 60

        api.responses[today] = FrankClientError("upstream is down")
        await tick(hass, frozen, at(2026, 8, 6, 14, 15, 3))

        # Retried (the cache is not complete) but the failure is absorbed.
        assert api.count(today) == 2
        assert entry.runtime_data.last_update_success is True
        assert len(hass.states.get(PRICES_TODAY).attributes["prices"]) == 60
        assert hass.states.get(CURRENT_PRICE).state not in ("unknown", "unavailable")
    finally:
        freezer.stop()


# --- H. Today request fails with no cache at all ---------------------------


async def test_today_failure_without_cache_fails_the_update(hass, entry, api):
    """With nothing cached, an unobtainable today is a legitimate failure."""
    start = at(2026, 8, 6, 14, 7)
    api.responses[start.date()] = FrankClientError("upstream is down")

    freezer, _frozen = await setup_at(hass, entry, start)
    try:
        assert entry.state is ConfigEntryState.SETUP_RETRY
    finally:
        freezer.stop()


async def test_today_failure_after_rollover_without_cache_fails_the_update(
    hass, entry, api
):
    """A day that was never cached and cannot be fetched fails the update."""
    start = at(2026, 8, 6, 6, 5)  # before the gate: tomorrow is never cached
    freezer, frozen = await setup_at(hass, entry, start)
    try:
        assert entry.runtime_data.last_update_success is True

        api.responses[date(2026, 8, 7)] = FrankClientError("upstream is down")
        await tick(hass, frozen, at(2026, 8, 7, 0, 0, 3))

        assert entry.runtime_data.last_update_success is False
        assert hass.states.get(CURRENT_PRICE).state == "unavailable"
    finally:
        freezer.stop()


# --- I. Midnight rollover --------------------------------------------------


async def test_midnight_rollover_uses_cached_tomorrow(hass, entry, api):
    """Cached tomorrow becomes today for free; stale days are cleaned up."""
    start = at(2026, 8, 6, 14, 7)
    day_a = date(2026, 8, 6)
    day_b = date(2026, 8, 7)

    freezer, frozen = await setup_at(hass, entry, start)
    try:
        coordinator = entry.runtime_data
        assert api.count(day_a) == 1
        assert api.count(day_b) == 1
        assert (
            hass.states.get(PRICES_TODAY)
            .attributes["prices"][0]["from"]
            .startswith("2026-08-06")
        )

        calls_before = len(api.calls)
        await tick(hass, frozen, at(2026, 8, 7, 0, 0, 3))

        # Zero requests: day B was already fetched as "tomorrow" yesterday, and
        # day C is behind the publication gate at 00:00.
        assert len(api.calls) == calls_before
        today_state = hass.states.get(PRICES_TODAY)
        assert today_state.attributes["prices"][0]["from"].startswith("2026-08-07")
        assert len(today_state.attributes["prices"]) == 96
        assert hass.states.get(CURRENT_PRICE).attributes["time"] == "00:00"

        # Day A is dropped, day B kept.
        assert day_a not in coordinator._prices_by_day
        assert day_b in coordinator._prices_by_day

        # Day C then follows the normal publication policy.
        await tick(hass, frozen, at(2026, 8, 7, 11, 45, 3))
        assert api.count(date(2026, 8, 8)) == 0
        await tick(hass, frozen, at(2026, 8, 7, 12, 0, 3))
        assert api.count(date(2026, 8, 8)) == 1
    finally:
        freezer.stop()


async def test_rollover_does_not_drop_tomorrow_before_it_becomes_today(
    hass, entry, api
):
    """Cleanup must never evict tomorrow while it is still tomorrow."""
    start = at(2026, 8, 6, 14, 7)
    freezer, frozen = await setup_at(hass, entry, start)
    try:
        coordinator = entry.runtime_data
        for _ in range(4):
            await tick_quarters(hass, frozen, dt_util.now(), 1)
            assert date(2026, 8, 7) in coordinator._complete_days
        assert api.count(date(2026, 8, 7)) == 1
    finally:
        freezer.stop()


# --- J/K. Partial responses ------------------------------------------------


async def test_partial_response_never_replaces_a_complete_cache(hass, entry, api):
    """A short list must not overwrite a known-good complete day."""
    start = at(2026, 8, 6, 14, 7)
    today = start.date()
    freezer, _ = await setup_at(hass, entry, start)
    try:
        coordinator = entry.runtime_data
        assert len(coordinator._prices_by_day[today]) == 96

        coordinator._store_day(today, build_local_day_blocks(today)[:10])

        assert len(coordinator._prices_by_day[today]) == 96
        assert today in coordinator._complete_days
    finally:
        freezer.stop()


async def test_partial_today_is_retried_and_completed(hass, entry, api):
    """Partial data stays usable, is not marked complete, and is refetched."""
    start = at(2026, 8, 6, 14, 7)
    today = start.date()
    api.responses[today] = build_local_day_blocks(today)[:60]

    freezer, frozen = await setup_at(hass, entry, start)
    try:
        coordinator = entry.runtime_data
        assert today not in coordinator._complete_days
        # Still usable for the current cycle.
        assert hass.states.get(CURRENT_PRICE).state not in ("unknown", "unavailable")

        del api.responses[today]  # the rest of the day is published
        await tick(hass, frozen, at(2026, 8, 6, 14, 15, 3))

        assert today in coordinator._complete_days
        assert len(hass.states.get(PRICES_TODAY).attributes["prices"]) == 96

        # And now it stops being requested.
        calls_before = len(api.calls)
        await tick_quarters(hass, frozen, at(2026, 8, 6, 14, 15), 4)
        assert len(api.calls) == calls_before
    finally:
        freezer.stop()


# --- Partial today must never yield a wrong current price ------------------
#
# A partial today may keep the integration running only for as long as it
# actually contains the active quarter. The moment it does not, "no current
# price" is the only honest answer: presenting the nearest block instead would
# hand an automation a price for a quarter that is not the one being billed.


async def test_partial_today_with_current_quarter_survives_fetch_failure(
    hass, entry, api
):
    """Partial data covering the active quarter keeps the coordinator running."""
    start = at(2026, 8, 6, 14, 7)
    today = start.date()
    # 00:00 .. 15:00 — the 14:00 block is present.
    api.responses[today] = build_local_day_blocks(today)[:60]

    freezer, frozen = await setup_at(hass, entry, start)
    try:
        coordinator = entry.runtime_data
        api.responses[today] = FrankClientError("upstream is down")
        await tick(hass, frozen, at(2026, 8, 6, 14, 15, 3))

        # The current price is derived from the partial list, and it is the
        # block that genuinely covers 14:15 — not merely "some" block.
        state = hass.states.get(CURRENT_PRICE)
        assert state.state not in ("unknown", "unavailable")
        assert state.attributes["time"] == "14:15"
        assert coordinator.last_update_success is True
        # Still incomplete, still being retried.
        assert today not in coordinator._complete_days
        assert api.count(today) == 2
        await tick(hass, frozen, at(2026, 8, 6, 14, 30, 3))
        assert api.count(today) == 3
    finally:
        freezer.stop()


async def test_partial_today_without_current_quarter_reports_no_price(hass, entry, api):
    """A partial list that misses the active quarter must not invent one."""
    start = at(2026, 8, 6, 14, 7)
    today = start.date()
    blocks = build_local_day_blocks(today)
    # 00:00 .. 05:00 only — nothing anywhere near 14:07.
    api.responses[today] = blocks[:20]

    freezer, frozen = await setup_at(hass, entry, start)
    try:
        coordinator = entry.runtime_data
        api.responses[today] = FrankClientError("upstream is down")
        await tick(hass, frozen, at(2026, 8, 6, 14, 15, 3))

        # No active block: the price is unknown rather than the last block of
        # the partial list (04:45) or its first (00:00).
        state = hass.states.get(CURRENT_PRICE)
        assert state.state == "unknown"
        assert "time" not in state.attributes
        assert coordinator.data["current_price"] is None
        assert coordinator.data["current_price_block"] is None
        # The feed-in sensor has no block to calculate from either.
        assert hass.states.get("sensor.frank_current_return_price").state == (
            "unavailable"
        )

        # What *is* known stays published, and the retry keeps going.
        assert coordinator.last_update_success is True
        assert len(hass.states.get(PRICES_TODAY).attributes["prices"]) == 20
        assert today not in coordinator._complete_days
        assert api.count(today) == 2
    finally:
        freezer.stop()


async def test_quarter_boundary_into_a_missing_block_drops_the_price(hass, entry, api):
    """The previous quarter must not be presented as the current one.

    The partial list ends exactly at the boundary being crossed, so before the
    tick there is a valid current block and after it there is none. This is the
    case where holding on to the last known block would look most plausible and
    be most wrong.
    """
    start = at(2026, 8, 6, 10, 7)
    today = start.date()
    blocks = build_local_day_blocks(today)
    # 00:00 .. 10:15 — the last block is 10:00-10:15; 10:15-10:30 is missing.
    api.responses[today] = blocks[:41]

    freezer, frozen = await setup_at(hass, entry, start)
    try:
        coordinator = entry.runtime_data
        before = hass.states.get(CURRENT_PRICE)
        assert before.attributes["time"] == "10:00"
        previous_price = before.state

        # The clock crosses into the missing quarter with the API unavailable.
        api.responses[today] = FrankClientError("upstream is down")
        await tick(hass, frozen, at(2026, 8, 6, 10, 15, 3))

        state = hass.states.get(CURRENT_PRICE)
        assert state.state != previous_price
        assert state.state == "unknown"
        assert "time" not in state.attributes
        assert coordinator.data["current_price_block"] is None

        # Recovery restores it on the next tick once the API is back.
        del api.responses[today]
        await tick(hass, frozen, at(2026, 8, 6, 10, 30, 3))
        recovered = hass.states.get(CURRENT_PRICE)
        assert recovered.attributes["time"] == "10:30"
        assert today in coordinator._complete_days
    finally:
        freezer.stop()


async def test_fresh_partial_covering_now_is_not_discarded_for_a_longer_stale_one(
    hass, entry, api
):
    """Merging beats picking: a short fresh list covering now must be kept.

    Choosing the longer of two partial lists would throw away a late response
    that covers the active quarter in favour of an early one that does not,
    leaving the current price unknown while the data to derive it was in hand.
    """
    start = at(2026, 8, 6, 2, 7)
    today = start.date()
    blocks = build_local_day_blocks(today)
    api.responses[today] = blocks[:20]  # 00:00 .. 05:00 (long, covers 02:07)

    freezer, frozen = await setup_at(hass, entry, start)
    try:
        coordinator = entry.runtime_data
        assert len(coordinator._prices_by_day[today]) == 20

        # Later in the day only a short tail is served.
        api.responses[today] = blocks[80:84]  # 20:00 .. 21:00
        await tick(hass, frozen, at(2026, 8, 6, 20, 15, 3))

        state = hass.states.get(CURRENT_PRICE)
        assert state.attributes["time"] == "20:15"
        # Neither list was thrown away.
        assert len(coordinator._prices_by_day[today]) == 24
        assert today not in coordinator._complete_days
    finally:
        freezer.stop()


async def test_merge_can_complete_a_day_delivered_in_two_halves(hass, entry, api):
    """Two partial responses that together span the day validate as complete."""
    start = at(2026, 8, 6, 0, 7)
    today = start.date()
    blocks = build_local_day_blocks(today)
    api.responses[today] = blocks[:48]

    freezer, frozen = await setup_at(hass, entry, start)
    try:
        coordinator = entry.runtime_data
        assert today not in coordinator._complete_days

        api.responses[today] = blocks[48:]
        await tick(hass, frozen, at(2026, 8, 6, 0, 15, 3))

        assert today in coordinator._complete_days
        assert len(hass.states.get(PRICES_TODAY).attributes["prices"]) == 96
    finally:
        freezer.stop()


async def test_partial_tomorrow_is_not_treated_as_complete(hass, entry, api):
    """A truncated tomorrow keeps being retried until the full day arrives."""
    start = at(2026, 8, 6, 14, 7)
    tomorrow = start.date() + timedelta(days=1)
    api.responses[tomorrow] = build_local_day_blocks(tomorrow)[:40]

    freezer, frozen = await setup_at(hass, entry, start)
    try:
        coordinator = entry.runtime_data
        assert tomorrow not in coordinator._complete_days
        assert api.count(tomorrow) == 1

        await tick(hass, frozen, at(2026, 8, 6, 14, 15, 3))
        assert api.count(tomorrow) == 2

        del api.responses[tomorrow]
        await tick(hass, frozen, at(2026, 8, 6, 14, 30, 3))
        assert tomorrow in coordinator._complete_days
        assert int(hass.states.get(PRICES_TOMORROW).state) == 96

        await tick(hass, frozen, at(2026, 8, 6, 14, 45, 3))
        assert api.count(tomorrow) == 3
    finally:
        freezer.stop()


# --- L/M/N. Market-day completeness, including both DST transitions --------
#
# ``_covers_full_market_day`` became an instance method in v0.1.6: completeness
# is measured against the *market's* midnights, so the validator needs to know
# which market it is validating. It still takes no Home Assistant state, so a
# bare instance is enough to exercise it.


def covers_full_day(blocks, day, country: str = "NL") -> bool:
    """Run the coordinator's market-day validator without a full setup."""
    validator = FrankQuarterPricesCoordinator.__new__(FrankQuarterPricesCoordinator)
    validator.country = country
    return validator._covers_full_market_day(blocks, day)


@pytest.mark.parametrize(
    ("day", "expected_blocks"),
    [
        (date(2026, 8, 6), 96),  # L. normal 24-hour day
        (SPRING_FORWARD, 92),  # M. 23-hour day
        (FALL_BACK, 100),  # N. 25-hour day
    ],
)
async def test_complete_market_day_validates(hass, day, expected_blocks):
    """Completeness follows the real market-day span, not a fixed block count."""
    blocks = build_local_day_blocks(day)

    assert len(blocks) == expected_blocks
    assert covers_full_day(blocks, day) is True


@pytest.mark.parametrize("day", [date(2026, 8, 6), SPRING_FORWARD, FALL_BACK])
async def test_incomplete_market_day_is_rejected(hass, day):
    """Missing, gapped and duplicated blocks all fail validation."""
    blocks = build_local_day_blocks(day)

    assert covers_full_day([], day) is False
    # Truncated at the end.
    assert covers_full_day(blocks[:-1], day) is False
    # Missing the start of the day.
    assert covers_full_day(blocks[1:], day) is False
    # A hole in the middle.
    gapped = blocks[:10] + blocks[11:]
    assert covers_full_day(gapped, day) is False
    # Right count, but one block duplicated in place of another.
    duplicated = blocks[:10] + [blocks[9]] + blocks[11:]
    assert len(duplicated) == len(blocks)
    assert covers_full_day(duplicated, day) is False


async def test_hourly_fallback_day_validates(hass):
    """An hourly (60-minute) fallback response still covers the full day."""
    day = date(2026, 8, 6)
    blocks = build_local_day_blocks(day, resolution_minutes=60)

    assert len(blocks) == 24
    assert covers_full_day(blocks, day) is True


async def test_dst_day_is_cached_and_not_refetched(hass, entry, api):
    """End to end: a 25-hour day validates, caches and stops being requested."""
    start = at(2026, 10, 25, 14, 7)
    freezer, frozen = await setup_at(hass, entry, start)
    try:
        coordinator = entry.runtime_data
        assert FALL_BACK in coordinator._complete_days
        assert len(coordinator._prices_by_day[FALL_BACK]) == 100
        assert int(hass.states.get(PRICES_TODAY).state) == 100

        await tick_quarters(hass, frozen, start, 4)
        assert api.count(FALL_BACK) == 1
    finally:
        freezer.stop()


# --- Request volume over a representative day ------------------------------


async def test_daily_request_count_collapses(hass, entry, api):
    """Issue #3's headline number: ~192 requests/day becomes a handful.

    Runs a full 96-tick day starting at midnight with nothing cached, so this
    is the worst case for the new design: today has to be fetched, and
    tomorrow is only reachable from the publication hour onwards.
    """
    start = at(2026, 8, 6, 0, 0)
    freezer, frozen = await setup_at(hass, entry, start)
    try:
        await tick_quarters(hass, frozen, start, 95)  # 00:15 .. 23:45

        # v0.1.4 would have issued 2 requests on each of the 96 runs.
        assert len(api.calls) <= 4
        assert api.count(date(2026, 8, 6)) == 1
        assert api.count(date(2026, 8, 7)) == 1
        # The next day then starts from a warm cache.
        assert entry.runtime_data.last_update_success is True
    finally:
        freezer.stop()


async def test_two_day_run_needs_no_extra_today_fetch(hass, entry, api):
    """Across a midnight boundary each calendar day is fetched exactly once."""
    start = at(2026, 8, 6, 12, 0)
    freezer, frozen = await setup_at(hass, entry, start)
    try:
        moment = start
        for _ in range(96):  # 12:15 on day A .. 12:00 on day B
            moment += timedelta(minutes=15)
            await tick(hass, frozen, moment.replace(second=3))

        assert api.count(date(2026, 8, 6)) == 1
        assert api.count(date(2026, 8, 7)) == 1
        assert api.count(date(2026, 8, 8)) == 1
        assert len(api.calls) == 3
    finally:
        freezer.stop()


# --- Documented block counts, at both resolutions ---------------------------


@pytest.mark.parametrize(
    ("resolution_minutes", "day", "expected_blocks"),
    [
        # Quarter-hour data: the resolution the integration requests.
        (15, SPRING_FORWARD, 92),
        (15, date(2026, 8, 6), 96),
        (15, FALL_BACK, 100),
        # Hourly fallback, for a day Frank has no quarter-hour data for.
        (60, SPRING_FORWARD, 23),
        (60, date(2026, 8, 6), 24),
        (60, FALL_BACK, 25),
    ],
)
async def test_documented_block_counts_are_complete_days(
    hass, resolution_minutes, day, expected_blocks
):
    """Pin the block counts both READMEs quote, at both resolutions.

    "96 blocks a day" is only true on an ordinary day. The documentation states
    92/96/100 for quarter-hour data and 23/24/25 for the hourly fallback, and a
    reader should be able to trust that those are the real numbers rather than a
    plausible-looking guess. Each one is asserted to be exactly what a complete
    market day contains.
    """
    blocks = build_local_day_blocks(day, resolution_minutes=resolution_minutes)

    assert len(blocks) == expected_blocks
    assert covers_full_day(blocks, day) is True


@pytest.mark.parametrize("resolution_minutes", [15, 60])
async def test_one_block_short_is_never_a_complete_day(hass, resolution_minutes):
    """The counts above are exact: one block fewer is not the day."""
    for day in (SPRING_FORWARD, date(2026, 8, 6), FALL_BACK):
        blocks = build_local_day_blocks(day, resolution_minutes=resolution_minutes)
        assert covers_full_day(blocks[:-1], day) is False, (day, resolution_minutes)


# --- The repeated hour of the fall-back day ---------------------------------


async def test_current_block_distinguishes_the_two_passes_of_the_repeated_hour(hass):
    """02:00 CEST and 02:00 CET are different quarters with different prices.

    Comparing the aware datetimes directly is a naive wall-clock comparison
    whenever both share one ``tzinfo`` object -- which they always do, because
    ``ZoneInfo`` is cached per key. Both passes of the repeated hour then look
    identical and the first-pass block is returned for the whole second hour,
    so ``sensor.frank_current_price`` would publish the previous hour's price
    for an hour, once a year.
    """
    market_tz = dt_util.get_time_zone(TEST_TIMEZONE)
    blocks = [
        build_block_span(block["from"], block["till"], round(0.05 + index * 0.001, 6))
        for index, block in enumerate(build_local_day_blocks(FALL_BACK))
    ]
    assert len(blocks) == 100

    def block_at(moment):
        return FrankQuarterPricesCoordinator._determine_current_block(blocks, moment)

    first_pass = datetime(2026, 10, 25, 2, 7, tzinfo=market_tz, fold=0)
    second_pass = datetime(2026, 10, 25, 2, 7, tzinfo=market_tz, fold=1)

    early = block_at(first_pass)
    late = block_at(second_pass)

    assert early is not None and late is not None
    # An hour of real time apart, so a different quarter and a different price.
    assert early is not late
    assert early["total_price_eur_kwh"] != late["total_price_eur_kwh"]
    # And each really does contain its own instant, measured in UTC.
    for block, moment in ((early, first_pass), (late, second_pass)):
        assert (
            dt_util.as_utc(block["from"])
            <= dt_util.as_utc(moment)
            < dt_util.as_utc(block["till"])
        )


async def test_current_block_is_correct_at_every_quarter_of_the_fall_back_day(hass):
    """Walk all 100 quarters: each one selects itself, none is skipped."""
    blocks = build_local_day_blocks(FALL_BACK)

    for block in blocks:
        midpoint = dt_util.as_utc(block["from"]) + timedelta(minutes=7)
        selected = FrankQuarterPricesCoordinator._determine_current_block(
            blocks, midpoint
        )
        assert selected is block, dt_util.as_local(block["from"]).isoformat()
