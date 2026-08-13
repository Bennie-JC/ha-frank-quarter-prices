"""Lifecycle tests: repeated option changes, reloads and unload/setup cycles.

Users retune the zone margins more than once, and every change reloads the
config entry. The risk is accumulation: a leaked quarter-boundary listener, a
second coordinator left running, duplicate entity ids with a ``_2`` suffix, or a
creeping API-request multiplier. Nothing here checks a single happy path; it all
checks that doing the same thing five times leaves exactly the same footprint as
doing it once.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from freezegun import freeze_time
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.frank_quarter_prices import coordinator as coordinator_module
from custom_components.frank_quarter_prices.const import (
    CONF_APPLY_FEED_IN_VAT,
    CONF_CHEAP_ZONE_MARGIN_PERCENT,
    CONF_EXPENSIVE_ZONE_MARGIN_PERCENT,
    CONF_FEED_IN_ADJUSTMENT,
    DOMAIN,
)

from .conftest import TEST_TIMEZONE, build_local_day_blocks

CHEAP_START = "sensor.frank_cheap_zone_start_today"
EXPENSIVE_START = "sensor.frank_expensive_zone_start_today"
CHEAP_PERIOD = "binary_sensor.frank_cheap_period"
EXPENSIVE_PERIOD = "binary_sensor.frank_expensive_period"

_CLIENT_METHOD = (
    "custom_components.frank_quarter_prices.frank_client."
    "FrankClient.async_get_prices_for_date"
)

DAY = date(2026, 8, 6)

# The margin sequence a real user might work through while tuning.
MARGIN_SEQUENCE = [(15.0, 15.0), (20.0, 15.0), (20.0, 10.0), (5.0, 25.0), (15.0, 15.0)]


class CountingApi:
    """Client stand-in that records every requested date."""

    def __init__(self) -> None:
        """Initialize with an empty call log."""
        self.calls: list[date] = []

    async def fetch(self, target_date: date) -> dict[str, Any]:
        """Serve a complete local day."""
        self.calls.append(target_date)
        return {"prices": build_local_day_blocks(target_date, None)}


@pytest.fixture(autouse=True)
async def local_timezone(hass):
    """Put Home Assistant on Europe/Amsterdam first."""
    await hass.config.async_set_time_zone(TEST_TIMEZONE)


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
    freezer = freeze_time(start)
    frozen = freezer.start()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return freezer, frozen


def zone_entity_ids(hass) -> list[str]:
    """Return every entity id this integration owns, from the registry."""
    registry = er.async_get(hass)
    return sorted(
        registered.entity_id
        for registered in registry.entities.values()
        if registered.platform == DOMAIN
    )


# --- Repeated option changes ------------------------------------------------


async def test_five_margin_changes_leave_no_duplicates(hass, entry, api):
    """15/15 -> 20/15 -> 20/10 -> 5/25 -> 15/15 accumulates nothing.

    After every reload the stored options, the published margins and the entity
    set must be exactly right, and the per-reload API cost must stay flat rather
    than multiplying with the number of previous reloads.
    """
    listener_registrations: list[dict[str, Any]] = []
    real_track = coordinator_module.async_track_time_change

    def recording(hass_arg, action, **kwargs):
        listener_registrations.append(kwargs)
        return real_track(hass_arg, action, **kwargs)

    with patch.object(coordinator_module, "async_track_time_change", recording):
        freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
        try:
            baseline_entities = zone_entity_ids(hass)
            assert len(baseline_entities) == 19
            setup_calls = len(api.calls)
            assert setup_calls == 2  # today + tomorrow
            per_reload_costs: list[int] = []

            for cheap, expensive in MARGIN_SEQUENCE:
                before = len(api.calls)
                hass.config_entries.async_update_entry(
                    entry,
                    options={
                        CONF_CHEAP_ZONE_MARGIN_PERCENT: cheap,
                        CONF_EXPENSIVE_ZONE_MARGIN_PERCENT: expensive,
                    },
                )
                await hass.async_block_till_done()
                per_reload_costs.append(len(api.calls) - before)

                # Stored options are exactly what was asked for.
                assert entry.options[CONF_CHEAP_ZONE_MARGIN_PERCENT] == cheap
                assert entry.options[CONF_EXPENSIVE_ZONE_MARGIN_PERCENT] == expensive
                # And they reach the entities.
                assert hass.states.get(CHEAP_START).attributes["margin_percent"] == (
                    cheap
                )
                assert (
                    hass.states.get(EXPENSIVE_START).attributes["margin_percent"]
                    == expensive
                )
                # No duplicate / suffixed entity ids appeared.
                assert zone_entity_ids(hass) == baseline_entities

            # Exactly one live coordinator, and it is the entry's own.
            coordinator = entry.runtime_data
            assert coordinator.update_interval is None
            assert coordinator.data["cheap_zone"] is not None

            # One quarter-boundary listener per coordinator instance: the
            # initial setup plus one per reload, never two for the same load.
            assert len(listener_registrations) == 1 + len(MARGIN_SEQUENCE)
            assert all(
                registration["minute"] == [0, 15, 30, 45]
                for registration in listener_registrations
            )

            # Flat cost per reload -- no multiplier creeping in.
            assert per_reload_costs == [2] * len(MARGIN_SEQUENCE), per_reload_costs
        finally:
            freezer.stop()


async def test_only_one_scheduler_fires_after_repeated_reloads(hass, entry, api):
    """A quarter tick refreshes once, not once per past reload.

    A leaked ``async_track_time_change`` listener from an earlier load would
    show up here as extra refreshes on a single boundary.
    """
    refreshes: list[datetime] = []
    original = coordinator_module.FrankQuarterPricesCoordinator._async_update_data

    async def counting(self):
        refreshes.append(dt_util.now())
        return await original(self)

    with patch.object(
        coordinator_module.FrankQuarterPricesCoordinator,
        "_async_update_data",
        counting,
    ):
        freezer, frozen = await setup_at(hass, entry, at(DAY, 14, 7))
        try:
            for cheap, expensive in MARGIN_SEQUENCE:
                hass.config_entries.async_update_entry(
                    entry,
                    options={
                        CONF_CHEAP_ZONE_MARGIN_PERCENT: cheap,
                        CONF_EXPENSIVE_ZONE_MARGIN_PERCENT: expensive,
                    },
                )
                await hass.async_block_till_done()

            refreshes.clear()
            frozen.move_to(at(DAY, 14, 15, 3))
            async_fire_time_changed(hass)
            await hass.async_block_till_done()

            assert len(refreshes) == 1, (
                f"{len(refreshes)} refreshes on one boundary -- leaked listener"
            )
        finally:
            freezer.stop()


async def test_unload_then_setup_again_is_clean(hass, entry, api):
    """A full unload/setup cycle recreates exactly the same entity set."""
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        before = zone_entity_ids(hass)
        assert len(before) == 19

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.NOT_LOADED
        for entity_id in (CHEAP_START, CHEAP_PERIOD):
            assert hass.states.get(entity_id).state == "unavailable"

        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED

        assert zone_entity_ids(hass) == before
        assert hass.states.get(CHEAP_START).state != "unavailable"
    finally:
        freezer.stop()


async def test_other_options_survive_a_margin_change(hass, api):
    """Changing margins through the options flow keeps the feed-in settings."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Frank Quarter Prices (NL)",
        data={"country": "NL"},
        options={
            CONF_FEED_IN_ADJUSTMENT: 0.018,
            CONF_APPLY_FEED_IN_VAT: True,
        },
        unique_id="NL",
    )
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        # The form pre-fills the stored feed-in values, so submitting only the
        # margins must not silently reset them.
        submitted = {
            str(marker.schema): marker.default()
            for marker in result["data_schema"].schema
            if marker.default is not None
        }
        submitted[CONF_CHEAP_ZONE_MARGIN_PERCENT] = 25.0
        await hass.config_entries.options.async_configure(result["flow_id"], submitted)
        await hass.async_block_till_done()

        assert entry.options[CONF_FEED_IN_ADJUSTMENT] == 0.018
        assert entry.options[CONF_APPLY_FEED_IN_VAT] is True
        assert entry.options[CONF_CHEAP_ZONE_MARGIN_PERCENT] == 25.0
        # market_price 0.08 + 0.018, including 21% VAT.
        assert float(
            hass.states.get("sensor.frank_current_return_price").state
        ) == pytest.approx(round((0.08 + 0.018) * 1.21, 6))
    finally:
        freezer.stop()


# --- Every documented margin boundary ---------------------------------------


@pytest.mark.parametrize("margin", [0.0, 1.0, 5.0, 15.0, 25.0, 49.0])
async def test_every_documented_margin_produces_a_usable_zone(hass, api, margin):
    """Every value the selector allows yields a valid, published zone."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Frank Quarter Prices (NL)",
        data={"country": "NL"},
        options={
            CONF_CHEAP_ZONE_MARGIN_PERCENT: margin,
            CONF_EXPENSIVE_ZONE_MARGIN_PERCENT: margin,
        },
        unique_id="NL",
    )
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        for entity_id in (CHEAP_START, EXPENSIVE_START):
            state = hass.states.get(entity_id)
            assert state.state not in ("unavailable", "unknown"), entity_id
            attrs = state.attributes
            assert attrs["margin_percent"] == margin
            assert attrs["quarter_count"] >= 1
            assert attrs["zone_duration_minutes"] >= 15
            assert isinstance(attrs["threshold_eur_kwh"], float)
        # The binary sensors stay consistent with their boundaries throughout.
        for period_id, start_id in (
            (CHEAP_PERIOD, CHEAP_START),
            (EXPENSIVE_PERIOD, EXPENSIVE_START),
        ):
            period = hass.states.get(period_id)
            assert period.state in ("on", "off")
            assert (
                period.attributes["margin_percent"]
                == (hass.states.get(start_id).attributes["margin_percent"])
            )
    finally:
        freezer.stop()


async def test_margins_may_differ_from_each_other(hass, api):
    """The two margins are independent, not a single shared setting."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Frank Quarter Prices (NL)",
        data={"country": "NL"},
        options={
            CONF_CHEAP_ZONE_MARGIN_PERCENT: 5.0,
            CONF_EXPENSIVE_ZONE_MARGIN_PERCENT: 25.0,
        },
        unique_id="NL",
    )
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        assert hass.states.get(CHEAP_START).attributes["margin_percent"] == 5.0
        assert hass.states.get(EXPENSIVE_START).attributes["margin_percent"] == 25.0
    finally:
        freezer.stop()


# --- Upgrading a real v0.1.5 entry ------------------------------------------


async def test_realistic_v0_1_5_entry_upgrades_without_intervention(hass, api):
    """A v0.1.5 entry (feed-in options only, no margins) just works.

    No migration, no re-add, no KeyError, no None margin -- the two new options
    resolve to their 15% defaults and every entity comes up.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Frank Quarter Prices (NL)",
        data={"country": "NL"},
        # Exactly what v0.1.5 could have stored, and nothing else.
        options={CONF_FEED_IN_ADJUSTMENT: -0.017, CONF_APPLY_FEED_IN_VAT: False},
        unique_id="NL",
        version=1,
    )
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        assert entry.state is ConfigEntryState.LOADED
        assert CONF_CHEAP_ZONE_MARGIN_PERCENT not in entry.options
        assert CONF_EXPENSIVE_ZONE_MARGIN_PERCENT not in entry.options
        assert entry.version == 1  # no migration was triggered

        assert len(zone_entity_ids(hass)) == 19
        for entity_id in (CHEAP_START, EXPENSIVE_START):
            attrs = hass.states.get(entity_id).attributes
            assert attrs["margin_percent"] == 15.0
        assert hass.states.get(CHEAP_PERIOD).state in ("on", "off")
        # The pre-existing feed-in setting is untouched and still applied.
        assert float(
            hass.states.get("sensor.frank_current_return_price").state
        ) == pytest.approx(0.063)
    finally:
        freezer.stop()
