"""Proof that the six v0.1.6 price-zone entities cost zero extra API requests.

The architectural rule for v0.1.6 is::

    FETCH ONCE -> CACHE ONCE -> DERIVE LOCALLY -> EXPOSE MANY TIMES

never "one sensor = one request". Every test here measures real Frank client
calls around the zone entities, and the last group pins down the structural
side of the same claim: one coordinator, one client, one quarter-boundary
listener, and exactly one cheap plus one expensive derivation per update no
matter how many entities or consumers read the result.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from freezegun import freeze_time
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.frank_quarter_prices import coordinator as coordinator_module
from custom_components.frank_quarter_prices.const import (
    CONF_CHEAP_ZONE_MARGIN_PERCENT,
    CONF_EXPENSIVE_ZONE_MARGIN_PERCENT,
    DOMAIN,
    ZONE_MODE_CHEAP,
    ZONE_MODE_EXPENSIVE,
)
from custom_components.frank_quarter_prices.frank_client import FrankClientError
from custom_components.frank_quarter_prices.price_zone import (
    calculate_price_zone,
    calculate_price_zones,
)

from .conftest import TEST_TIMEZONE, build_local_day_blocks

CHEAP_START = "sensor.frank_cheap_zone_start_today"
CHEAP_END = "sensor.frank_cheap_zone_end_today"
EXPENSIVE_START = "sensor.frank_expensive_zone_start_today"
EXPENSIVE_END = "sensor.frank_expensive_zone_end_today"
CHEAP_PERIOD = "binary_sensor.frank_cheap_period"
EXPENSIVE_PERIOD = "binary_sensor.frank_expensive_period"

# The six entities added in v0.1.6.
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


class CountingApi:
    """Client stand-in that records every requested date."""

    def __init__(self) -> None:
        """Initialize with an empty call log and no forced failures."""
        self.calls: list[date] = []
        self.fail_from: datetime | None = None

    async def fetch(self, target_date: date) -> dict[str, Any]:
        """Serve a complete local day, or fail once the outage has started."""
        self.calls.append(target_date)
        if self.fail_from is not None and dt_util.now() >= self.fail_from:
            raise FrankClientError("simulated Frank outage")
        return {"prices": build_local_day_blocks(target_date, None)}


@pytest.fixture
def api():
    """Patch the client with the counting fake."""
    fake = CountingApi()
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


def assert_all_zone_entities_healthy(hass) -> None:
    """Assert every zone entity has a usable state."""
    for entity_id in ZONE_ENTITIES:
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.state not in ("unavailable", "unknown"), entity_id


# --- A. Baseline coordinator update ----------------------------------------


async def test_zone_entities_add_no_request_to_a_normal_update(hass, entry, api):
    """The six new entities do not change the request count of a normal setup.

    Measured A/B: the same setup is performed with the zone platforms' entity
    definitions emptied, then with them in place. The Frank call counts must be
    identical.
    """
    baseline_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Frank Quarter Prices (NL)",
        data={"country": "NL"},
        options={},
        unique_id="NL-baseline",
    )
    start = at(DAY, 14, 7)

    with (
        patch("custom_components.frank_quarter_prices.sensor._ZONE_DEFINITIONS", ()),
        patch(
            "custom_components.frank_quarter_prices.binary_sensor._PERIOD_DEFINITIONS",
            (),
        ),
    ):
        freezer, _ = await setup_at(hass, baseline_entry, start)
        try:
            without_zones = len(api.calls)
            assert hass.states.get(CHEAP_START) is None
        finally:
            freezer.stop()
        await hass.config_entries.async_unload(baseline_entry.entry_id)
        await hass.async_block_till_done()

    api.calls.clear()
    freezer, _ = await setup_at(hass, entry, start)
    try:
        with_zones = len(api.calls)
        assert_all_zone_entities_healthy(hass)
    finally:
        freezer.stop()

    assert without_zones == 2  # today + tomorrow, unchanged from v0.1.5
    assert with_zones == without_zones


# --- B. Repeated entity reads ----------------------------------------------


async def test_repeated_entity_reads_cost_nothing(hass, entry, api):
    """Reading the six entities over and over performs no request at all."""
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        calls_before = len(api.calls)

        for _ in range(50):
            for entity_id in ZONE_ENTITIES:
                state = hass.states.get(entity_id)
                # Touch the attributes too: they are computed on access.
                assert dict(state.attributes) is not None

        assert len(api.calls) == calls_before
    finally:
        freezer.stop()


# --- C. Repeated state writes ----------------------------------------------


async def test_repeated_state_writes_cost_nothing(hass, entry, api):
    """Re-rendering the entity states without a new fetch performs no request."""
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        coordinator = entry.runtime_data
        calls_before = len(api.calls)

        for _ in range(10):
            coordinator.async_set_updated_data(coordinator.data)
            await hass.async_block_till_done()

        assert len(api.calls) == calls_before
        assert_all_zone_entities_healthy(hass)
    finally:
        freezer.stop()


# --- D. Quarter-boundary updates -------------------------------------------


async def test_quarter_boundaries_add_no_zone_request(hass, entry, api):
    """Crossing :00/:15/:30/:45 keeps the v0.1.5 request behaviour exactly."""
    start = at(DAY, 14, 7)
    freezer, frozen = await setup_at(hass, entry, start)
    try:
        calls_before = len(api.calls)

        # Eight boundaries: 14:15 through 16:00.
        moment = at(DAY, 14, 15, 3)
        for _ in range(8):
            await tick(hass, frozen, moment)
            moment += timedelta(minutes=15)

        # Both days are cached complete, so a tick is pure local arithmetic.
        assert len(api.calls) == calls_before
        assert_all_zone_entities_healthy(hass)
    finally:
        freezer.stop()


# --- E. Complete cached today ----------------------------------------------


async def test_complete_cached_today_serves_every_zone_entity_for_free(
    hass, entry, api
):
    """With today cached, deriving and reading all six costs zero requests."""
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        coordinator = entry.runtime_data
        calls_before = len(api.calls)

        # Derive both zones again straight off the cached day.
        today = coordinator.data["today"]
        assert calculate_price_zone(today, ZONE_MODE_CHEAP, 15.0) is not None
        assert calculate_price_zone(today, ZONE_MODE_EXPENSIVE, 15.0) is not None
        for entity_id in ZONE_ENTITIES:
            assert hass.states.get(entity_id) is not None

        assert len(api.calls) == calls_before
    finally:
        freezer.stop()


# --- F. Temporary Frank outage ---------------------------------------------


async def test_outage_keeps_the_zones_alive_with_no_zone_request(hass, entry, api):
    """A Frank outage cannot blank the zones nor provoke a zone-specific request.

    This is the issue #3 availability coupling: with a complete today already
    cached, the entities must keep deriving from it.
    """
    start = at(DAY, 14, 7)
    freezer, frozen = await setup_at(hass, entry, start)
    try:
        before = hass.states.get(CHEAP_START).state
        calls_before = len(api.calls)

        api.fail_from = start  # every further request now fails
        for offset in range(1, 5):
            await tick(hass, frozen, at(DAY, 14, 15 * offset % 60, 3))

        assert_all_zone_entities_healthy(hass)
        assert hass.states.get(CHEAP_START).state == before
        # Today is cached complete, so it is never re-requested; the zone
        # entities themselves never request anything.
        assert len(api.calls) == calls_before
    finally:
        freezer.stop()


# --- G. Margin change ------------------------------------------------------


async def test_recalculating_for_a_new_margin_is_purely_local(hass, entry, api):
    """Re-deriving both zones at every margin from 0-100% costs zero requests."""
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        coordinator = entry.runtime_data
        today = coordinator.data["today"]
        calls_before = len(api.calls)

        for margin in range(0, 101, 5):
            assert (
                calculate_price_zone(today, ZONE_MODE_CHEAP, float(margin)) is not None
            )
            assert (
                calculate_price_zone(today, ZONE_MODE_EXPENSIVE, float(margin))
                is not None
            )

        assert len(api.calls) == calls_before
    finally:
        freezer.stop()


async def test_margin_change_reload_refetches_only_the_normal_days(hass, entry, api):
    """Saving a margin triggers Home Assistant's ordinary options reload.

    Documented behaviour rather than an aspiration: an options change reloads
    the config entry — as it already did in v0.1.5 for the feed-in options — so
    the fresh coordinator fetches today and tomorrow once, exactly like any
    other setup. There is no zone-specific request path: the count after the
    reload is the same two-day setup cost, not one request per zone entity.
    """
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        setup_calls = len(api.calls)
        assert setup_calls == 2

        result = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_CHEAP_ZONE_MARGIN_PERCENT: 20.0,
                CONF_EXPENSIVE_ZONE_MARGIN_PERCENT: 10.0,
            },
        )
        await hass.async_block_till_done()

        assert hass.states.get(CHEAP_START).attributes["margin_percent"] == 20.0
        assert hass.states.get(EXPENSIVE_START).attributes["margin_percent"] == 10.0
        # One ordinary reload: today + tomorrow again, and nothing per entity.
        assert len(api.calls) - setup_calls == 2
    finally:
        freezer.stop()


# --- H. Multiple subscribers -----------------------------------------------


async def test_many_consumers_do_not_multiply_requests(hass, entry, api):
    """Dashboards, automations and EMS consumers all share the one derivation.

    Twenty independent subscribers are attached to all six entities and then a
    midnight rollover is crossed, so every one of them really is served a state
    change. The request count must not move with the number of consumers.
    """
    freezer, frozen = await setup_at(hass, entry, at(DAY, 23, 45, 3))
    try:
        calls_before = len(api.calls)
        seen: list[str] = []

        @callback
        def _record(event) -> None:
            seen.append(event.data["entity_id"])

        for _ in range(20):
            async_track_state_change_event(hass, list(ZONE_ENTITIES), _record)

        await tick(hass, frozen, at(DAY + timedelta(days=1), 0, 0, 3))

        # Every subscriber was served the new day's zone boundaries.
        assert len(seen) >= 20 * len(ZONE_ENTITIES)
        assert set(seen) == set(ZONE_ENTITIES)
        assert_all_zone_entities_healthy(hass)
        # Yesterday's "tomorrow" simply became today: no request, however many
        # consumers were listening.
        assert len(api.calls) == calls_before
    finally:
        freezer.stop()


# --- Architecture proof (point 42.17) --------------------------------------


async def test_exactly_one_cheap_and_one_expensive_derivation_per_update(
    hass, entry, api
):
    """Each coordinator update derives each zone once, never once per entity.

    Six entities reading a shared result is the point of the design; six
    entities each re-running the algorithm would be the regression.
    """
    real = calculate_price_zones
    derivations: list[tuple[float, float]] = []

    def counting(prices, cheap_margin, expensive_margin):
        derivations.append((cheap_margin, expensive_margin))
        return real(prices, cheap_margin, expensive_margin)

    with patch.object(coordinator_module, "calculate_price_zones", counting):
        freezer, frozen = await setup_at(hass, entry, at(DAY, 14, 7))
        try:
            # One paired derivation -- one cheap zone and one expensive zone.
            assert derivations == [(15.0, 15.0)]

            derivations.clear()
            await tick(hass, frozen, at(DAY, 14, 15, 3))
            assert derivations == [(15.0, 15.0)]

            # Reading and re-reading every entity adds no further derivation.
            derivations.clear()
            for _ in range(10):
                for entity_id in ZONE_ENTITIES:
                    dict(hass.states.get(entity_id).attributes)
            assert derivations == []
        finally:
            freezer.stop()


async def test_only_one_quarter_boundary_listener_is_registered(hass, entry, api):
    """The zone entities add no timer, no polling interval and no listener."""
    registrations: list[dict[str, Any]] = []
    real = coordinator_module.async_track_time_change

    def recording(hass_arg, action, **kwargs):
        registrations.append(kwargs)
        return real(hass_arg, action, **kwargs)

    with patch.object(coordinator_module, "async_track_time_change", recording):
        freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
        try:
            assert len(registrations) == 1
            assert registrations[0]["minute"] == [0, 15, 30, 45]
            assert_all_zone_entities_healthy(hass)
        finally:
            freezer.stop()


async def test_one_coordinator_and_one_client_serve_every_entity(hass, entry, api):
    """All entities — old and new — hang off the single coordinator and client."""
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        from homeassistant.helpers import entity_registry as er

        coordinator = entry.runtime_data
        assert coordinator.update_interval is None  # no polling interval

        registry = er.async_get(hass)
        entity_ids = [
            registered.entity_id
            for registered in registry.entities.values()
            if registered.platform == DOMAIN
        ]
        assert len(entity_ids) == 19  # 13 pre-existing + 6 new

        coordinators = {
            id(
                hass.data["entity_components"][entity_id.split(".")[0]]
                .get_entity(entity_id)
                .coordinator
            )
            for entity_id in entity_ids
        }
        assert len(coordinators) == 1

        clients = {
            id(
                hass.data["entity_components"][entity_id.split(".")[0]]
                .get_entity(entity_id)
                .coordinator.client
            )
            for entity_id in entity_ids
        }
        assert len(clients) == 1
    finally:
        freezer.stop()
