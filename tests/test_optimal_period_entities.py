"""The optimal-period feature as Home Assistant sees it.

The algorithm itself is pinned down in ``test_optimal_period.py``; everything
here drives the real integration end to end — config entry, coordinator,
platforms, entity registry, state machine — because that is where the risks of
an *optional* feature live:

* entities that appear for users who never asked for them, or linger as
  unavailable leftovers after the feature is switched off again;
* a unique id that shifts when the feature is toggled, orphaning the original
  entity and handing the user a ``_2`` duplicate;
* a planner window derived from an incomplete day, which an EMS would act on;
* the same sliding-window search re-run per entity, or worse, a request per
  entity.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from homeassistant.components.recorder.db_schema import MAX_STATE_ATTRS_BYTES
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.frank_quarter_prices import coordinator as coordinator_module
from custom_components.frank_quarter_prices.const import (
    CONF_CHEAP_ZONE_MARGIN_PERCENT,
    CONF_EXPENSIVE_ZONE_MARGIN_PERCENT,
    CONF_OPTIMAL_CHEAP_DURATION_MINUTES,
    CONF_OPTIMAL_CHEAP_ENABLED,
    CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES,
    CONF_OPTIMAL_EXPENSIVE_ENABLED,
    COUNTRY_BE,
    COUNTRY_NL,
    DOMAIN,
    MARKET_TIMEZONES,
)
from custom_components.frank_quarter_prices.frank_client import FrankClientError

from .conftest import TEST_TIMEZONE, build_block_span, build_local_day_blocks

CHEAP_TODAY = "sensor.frank_optimal_cheap_period_today"
CHEAP_TOMORROW = "sensor.frank_optimal_cheap_period_tomorrow"
EXPENSIVE_TODAY = "sensor.frank_optimal_expensive_period_today"
EXPENSIVE_TOMORROW = "sensor.frank_optimal_expensive_period_tomorrow"
CHEAP_NOW = "binary_sensor.frank_optimal_cheap_period"
EXPENSIVE_NOW = "binary_sensor.frank_optimal_expensive_period"

CHEAP_ENTITIES = (CHEAP_TODAY, CHEAP_TOMORROW, CHEAP_NOW)
EXPENSIVE_ENTITIES = (EXPENSIVE_TODAY, EXPENSIVE_TOMORROW, EXPENSIVE_NOW)
ALL_OPTIMAL_ENTITIES = CHEAP_ENTITIES + EXPENSIVE_ENTITIES

# The v0.1.6 entity set, which must survive every scenario here untouched.
BASE_ENTITY_COUNT = 19

_CLIENT_METHOD = (
    "custom_components.frank_quarter_prices.frank_client."
    "FrankClient.async_get_prices_for_date"
)

NL_TZ = ZoneInfo("Europe/Amsterdam")
DAY = date(2026, 8, 6)
SPRING_FORWARD = date(2026, 3, 29)
FALL_BACK = date(2026, 10, 25)

# A day with one unambiguous cheap two-hour window and one unambiguous
# expensive two-hour window, at realistic Dutch magnitudes.
NORMAL_MP = 0.13
LOW_MP = 0.015
HIGH_MP = 0.28
CHEAP_RUN = range(40, 48)  # 10:00 .. 12:00
EXPENSIVE_RUN = range(76, 84)  # 19:00 .. 21:00


# --- Fixtures ----------------------------------------------------------------


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
    """Client stand-in serving the shaped market day, with overrides."""

    def __init__(self, country: str = COUNTRY_NL) -> None:
        """Initialize for a market."""
        self.calls: list[date] = []
        self.country = country
        self.responses: dict[date, Any] = {}

    def count(self, day: date) -> int:
        """Return how many times ``day`` was requested."""
        return self.calls.count(day)

    async def fetch(self, target_date: date) -> dict[str, Any]:
        """Serve the configured response, or the shaped day."""
        self.calls.append(target_date)
        response = self.responses.get(target_date)
        if isinstance(response, Exception):
            raise response
        if response is not None:
            return {"prices": list(response)}
        return {"prices": shaped_day(target_date, self.country)}


@pytest.fixture
def api():
    """Patch the client with the shaped fake."""
    fake = ShapedApi()
    with patch(_CLIENT_METHOD, AsyncMock(side_effect=fake.fetch)):
        yield fake


def make_entry(
    cheap: int | None = None,
    expensive: int | None = None,
    country: str = COUNTRY_NL,
    **extra: Any,
) -> MockConfigEntry:
    """Return a config entry with the planner features optionally enabled.

    ``cheap``/``expensive`` are durations in minutes; ``None`` leaves the
    feature off and stores no key at all, exactly like an entry created before
    the feature existed.
    """
    options: dict[str, Any] = dict(extra)
    if cheap is not None:
        options[CONF_OPTIMAL_CHEAP_ENABLED] = True
        options[CONF_OPTIMAL_CHEAP_DURATION_MINUTES] = cheap
    if expensive is not None:
        options[CONF_OPTIMAL_EXPENSIVE_ENABLED] = True
        options[CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES] = expensive
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


async def setup_at(hass, entry, moment: datetime, ha_timezone: str = TEST_TIMEZONE):
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


def registered(hass) -> list[str]:
    """Return every entity id this integration owns, from the registry."""
    registry = er.async_get(hass)
    return sorted(
        entity.entity_id
        for entity in registry.entities.values()
        if entity.platform == DOMAIN
    )


def hhmm(entity_id: str, hass) -> tuple[str, str]:
    """Return a period sensor's window as local ``HH:MM`` strings."""
    attrs = hass.states.get(entity_id).attributes
    return (attrs["start_time"], attrs["end_time"])


# --- Conditional creation ----------------------------------------------------


async def test_a_disabled_feature_creates_no_entity_at_all(hass, api):
    """The default install is byte-for-byte the v0.1.6 entity set."""
    freezer, _ = await setup_at(hass, make_entry(), market_time(DAY, 14, 7))
    try:
        assert len(registered(hass)) == BASE_ENTITY_COUNT
        for entity_id in ALL_OPTIMAL_ENTITIES:
            assert hass.states.get(entity_id) is None, entity_id
    finally:
        freezer.stop()


async def test_enabling_only_cheap_creates_only_the_cheap_entities(hass, api):
    """The two features are independent, down to the entity set."""
    freezer, _ = await setup_at(hass, make_entry(cheap=120), market_time(DAY, 14, 7))
    try:
        assert len(registered(hass)) == BASE_ENTITY_COUNT + 3
        for entity_id in CHEAP_ENTITIES:
            assert hass.states.get(entity_id) is not None, entity_id
        for entity_id in EXPENSIVE_ENTITIES:
            assert hass.states.get(entity_id) is None, entity_id
    finally:
        freezer.stop()


async def test_enabling_only_expensive_creates_only_those_entities(hass, api):
    """The mirror case."""
    freezer, _ = await setup_at(hass, make_entry(expensive=60), market_time(DAY, 14, 7))
    try:
        assert len(registered(hass)) == BASE_ENTITY_COUNT + 3
        for entity_id in EXPENSIVE_ENTITIES:
            assert hass.states.get(entity_id) is not None, entity_id
        for entity_id in CHEAP_ENTITIES:
            assert hass.states.get(entity_id) is None, entity_id
    finally:
        freezer.stop()


async def test_enabling_both_creates_exactly_six_entities(hass, api):
    """The maximum footprint of the feature is six entities, never more."""
    freezer, _ = await setup_at(
        hass, make_entry(cheap=120, expensive=60), market_time(DAY, 14, 7)
    )
    try:
        ids = registered(hass)
        assert len(ids) == BASE_ENTITY_COUNT + 6
        assert set(ALL_OPTIMAL_ENTITIES) <= set(ids)
    finally:
        freezer.stop()


async def test_the_nineteen_v0_1_6_entities_are_untouched(hass, api):
    """Enabling the planner on an existing entry does not move one entity.

    Deliberately the *same* config entry throughout — that is the real upgrade
    path, and the only one that can prove no existing entity was renamed or
    re-registered.
    """
    entry = make_entry()
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        registry = er.async_get(hass)
        baseline = registered(hass)
        baseline_unique_ids = {
            entity_id: registry.async_get(entity_id).unique_id for entity_id in baseline
        }
        assert len(baseline) == BASE_ENTITY_COUNT

        hass.config_entries.async_update_entry(
            entry,
            options={
                CONF_OPTIMAL_CHEAP_ENABLED: True,
                CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 120,
                CONF_OPTIMAL_EXPENSIVE_ENABLED: True,
                CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES: 120,
            },
        )
        await hass.async_block_till_done()

        after = registered(hass)
        assert set(after) - set(baseline) == set(ALL_OPTIMAL_ENTITIES)
        registry = er.async_get(hass)
        for entity_id, unique_id in baseline_unique_ids.items():
            assert registry.async_get(entity_id).unique_id == unique_id, entity_id
            assert hass.states.get(entity_id).state != "unavailable", entity_id
    finally:
        freezer.stop()


# --- Unique ids and toggling -------------------------------------------------


@pytest.mark.parametrize(
    ("entity_id", "suffix"),
    [
        (CHEAP_TODAY, "optimal_cheap_period_today"),
        (CHEAP_TOMORROW, "optimal_cheap_period_tomorrow"),
        (EXPENSIVE_TODAY, "optimal_expensive_period_today"),
        (EXPENSIVE_TOMORROW, "optimal_expensive_period_tomorrow"),
        (CHEAP_NOW, "optimal_cheap_period"),
        (EXPENSIVE_NOW, "optimal_expensive_period"),
    ],
)
async def test_unique_ids_follow_the_existing_pattern(hass, api, entity_id, suffix):
    """``{entry_id}_{key}``, the same scheme every other entity uses."""
    entry = make_entry(cheap=120, expensive=120)
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        registry_entry = er.async_get(hass).async_get(entity_id)
        assert registry_entry is not None
        assert registry_entry.unique_id == f"{entry.entry_id}_{suffix}"
        assert registry_entry.disabled_by is None
        assert registry_entry.hidden_by is None
    finally:
        freezer.stop()


async def test_off_on_off_on_always_yields_the_identical_entities(hass, api):
    """The toggle sequence from the brief, four times over.

    A shifting unique id would show up here immediately as a ``_2`` entity id.
    The registry entry is deliberately *kept* while the feature is off — see
    ``test_a_disabled_feature_leaves_the_entity_unavailable_not_deleted`` — so
    what is asserted is that the set never grows and the ids never change.
    """
    entry = make_entry()
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        baseline = registered(hass)
        assert len(baseline) == BASE_ENTITY_COUNT

        seen_enabled: list[list[str]] = []
        seen_disabled: list[list[str]] = []
        seen_unique_ids: list[dict[str, str]] = []

        for _ in range(4):
            hass.config_entries.async_update_entry(
                entry,
                options={
                    CONF_OPTIMAL_CHEAP_ENABLED: True,
                    CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 120,
                    CONF_OPTIMAL_EXPENSIVE_ENABLED: True,
                    CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES: 120,
                },
            )
            await hass.async_block_till_done()
            seen_enabled.append(registered(hass))
            registry = er.async_get(hass)
            seen_unique_ids.append(
                {
                    entity_id: registry.async_get(entity_id).unique_id
                    for entity_id in ALL_OPTIMAL_ENTITIES
                }
            )

            hass.config_entries.async_update_entry(entry, options={})
            await hass.async_block_till_done()
            seen_disabled.append(registered(hass))

        # Every enabled pass produced the identical entity ids...
        assert all(ids == seen_enabled[0] for ids in seen_enabled)
        assert len(seen_enabled[0]) == BASE_ENTITY_COUNT + 6
        # ...every disabled pass likewise, with nothing accumulating...
        assert all(ids == seen_disabled[0] for ids in seen_disabled)
        assert seen_disabled[0] == seen_enabled[0]
        # ...on the identical unique ids...
        assert all(ids == seen_unique_ids[0] for ids in seen_unique_ids)
        # ...and no _2 anywhere, ever.
        assert not [
            entity_id for entity_id in seen_enabled[0] if entity_id.endswith("_2")
        ]
        assert len(registered(hass)) == BASE_ENTITY_COUNT + 6
    finally:
        freezer.stop()


# --- Lifecycle: what a disabled feature does to a registry entry -------------
#
# The decisive question for an optional feature is not "is the entity list
# tidy" but "what happens to the user's own configuration when they switch the
# feature off". Removing the registry entry looks cleaner and passes a naive
# no-leftovers test, but it makes ``hass.states.get()`` return ``None`` — so a
# template silently reads ``unknown``, a state trigger silently never fires, and
# every customization depends on Home Assistant's deleted-entity restore pool
# handing it back. Not creating the entity and leaving its registry entry alone
# is what these tests pin down instead.


async def test_a_disabled_feature_leaves_the_entity_unavailable_not_deleted(hass, api):
    """Switching off keeps the registry entry and publishes ``unavailable``.

    ``unavailable`` is the conventional Home Assistant meaning of "this entity
    exists but has no value right now", and — unlike a removed entity — it is a
    state an automation or template can actually see and react to.
    """
    entry = make_entry(cheap=120, expensive=120)
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        registry = er.async_get(hass)
        before = {
            entity_id: registry.async_get(entity_id).unique_id
            for entity_id in ALL_OPTIMAL_ENTITIES
        }

        hass.config_entries.async_update_entry(entry, options={})
        await hass.async_block_till_done()

        for entity_id in ALL_OPTIMAL_ENTITIES:
            registry_entry = registry.async_get(entity_id)
            assert registry_entry is not None, f"{entity_id} was deleted, not disabled"
            assert registry_entry.unique_id == before[entity_id]

            state = hass.states.get(entity_id)
            assert state is not None, (
                f"{entity_id} has no state object at all, so a template reading "
                "it silently gets 'unknown' instead of 'unavailable'"
            )
            assert state.state == "unavailable"
    finally:
        freezer.stop()


async def test_a_never_enabled_feature_leaves_no_trace_at_all(hass, api):
    """The other half of the deal: no entity is created for a feature never used.

    This is why the registry entry may safely be left behind when the feature is
    switched off — the entity only ever exists for a user who asked for it.
    """
    freezer, _ = await setup_at(hass, make_entry(), market_time(DAY, 14, 7))
    try:
        registry = er.async_get(hass)
        for entity_id in ALL_OPTIMAL_ENTITIES:
            assert registry.async_get(entity_id) is None, entity_id
            assert hass.states.get(entity_id) is None, entity_id
        assert len(registered(hass)) == BASE_ENTITY_COUNT
    finally:
        freezer.stop()


async def test_a_custom_entity_id_survives_off_and_on(hass, api):
    """The user renames the entity, disables the feature, re-enables it.

    An automation written against ``sensor.my_ev_cheapest_window`` must still
    work afterwards — which means the very same registry row, the very same
    entity id, and no second entity on the default id.
    """
    entry = make_entry(cheap=120)
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        registry = er.async_get(hass)
        original_row_id = registry.async_get(CHEAP_TODAY).id
        unique_id = registry.async_get(CHEAP_TODAY).unique_id

        registry.async_update_entity(
            CHEAP_TODAY, new_entity_id="sensor.my_ev_cheapest_window"
        )
        await hass.async_block_till_done()
        assert hass.states.get("sensor.my_ev_cheapest_window") is not None

        # OFF: the renamed entity stays, unavailable.
        hass.config_entries.async_update_entry(entry, options={})
        await hass.async_block_till_done()
        assert registry.async_get("sensor.my_ev_cheapest_window") is not None
        assert hass.states.get("sensor.my_ev_cheapest_window").state == "unavailable"

        # ON again: same row, same id, same unique id, and no default-id twin.
        hass.config_entries.async_update_entry(
            entry,
            options={
                CONF_OPTIMAL_CHEAP_ENABLED: True,
                CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 120,
            },
        )
        await hass.async_block_till_done()

        restored = registry.async_get("sensor.my_ev_cheapest_window")
        assert restored is not None, "the user's custom entity id was lost"
        assert restored.id == original_row_id, "a new registry row was created"
        assert restored.unique_id == unique_id
        assert registry.async_get(CHEAP_TODAY) is None, (
            "a duplicate appeared on the default entity id"
        )
        assert hass.states.get("sensor.my_ev_cheapest_window").state != "unavailable"
        assert not [e for e in registered(hass) if e.endswith("_2")]
    finally:
        freezer.stop()


async def test_registry_customizations_survive_off_and_on(hass, api):
    """Name, icon, area, hidden and disabled flags all come back untouched."""
    from homeassistant.helpers import area_registry as ar

    entry = make_entry(cheap=120, expensive=120)
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        registry = er.async_get(hass)
        area = ar.async_get(hass).async_get_or_create("Garage")

        registry.async_update_entity(
            CHEAP_TODAY,
            name="EV charging window",
            icon="mdi:car-electric",
            area_id=area.id,
        )
        # A second entity is hidden by the user rather than renamed.
        registry.async_update_entity(
            CHEAP_TOMORROW, hidden_by=er.RegistryEntryHider.USER
        )
        await hass.async_block_till_done()

        for _ in range(3):
            hass.config_entries.async_update_entry(entry, options={})
            await hass.async_block_till_done()
            hass.config_entries.async_update_entry(
                entry,
                options={
                    CONF_OPTIMAL_CHEAP_ENABLED: True,
                    CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 120,
                    CONF_OPTIMAL_EXPENSIVE_ENABLED: True,
                    CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES: 120,
                },
            )
            await hass.async_block_till_done()

            customized = registry.async_get(CHEAP_TODAY)
            assert customized.name == "EV charging window"
            assert customized.icon == "mdi:car-electric"
            assert customized.area_id == area.id
            assert registry.async_get(CHEAP_TOMORROW).hidden_by is (
                er.RegistryEntryHider.USER
            )
    finally:
        freezer.stop()


async def test_a_disabled_entity_stays_disabled_across_the_toggle(hass, api):
    """A user who disabled one planner entity does not get it back enabled."""
    entry = make_entry(cheap=120)
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        registry = er.async_get(hass)
        registry.async_update_entity(
            CHEAP_TOMORROW, disabled_by=er.RegistryEntryDisabler.USER
        )
        await hass.async_block_till_done()

        hass.config_entries.async_update_entry(entry, options={})
        await hass.async_block_till_done()
        hass.config_entries.async_update_entry(
            entry,
            options={
                CONF_OPTIMAL_CHEAP_ENABLED: True,
                CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 120,
            },
        )
        await hass.async_block_till_done()

        assert registry.async_get(CHEAP_TOMORROW).disabled_by is (
            er.RegistryEntryDisabler.USER
        )
        # The sibling the user did not touch is still enabled and working.
        assert registry.async_get(CHEAP_TODAY).disabled_by is None
        assert hass.states.get(CHEAP_TODAY).state != "unavailable"
    finally:
        freezer.stop()


async def test_deleting_a_leftover_entity_only_sticks_while_the_feature_is_off(
    hass, api
):
    """Pins down the advice the README gives about removing leftovers.

    Deleting the entity while the feature is still **enabled** is futile: the
    integration recreates it on the next reload, which is exactly the kind of
    instruction documentation must not give. Deleting it while the feature is
    **disabled** is permanent, because nothing recreates it.
    """
    entry = make_entry(cheap=120)
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        registry = er.async_get(hass)

        # While enabled: deleting it is undone by the next reload.
        registry.async_remove(CHEAP_TODAY)
        await hass.async_block_till_done()
        assert registry.async_get(CHEAP_TODAY) is None

        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert registry.async_get(CHEAP_TODAY) is not None, (
            "deleting a live entity is temporary; the README must not present "
            "it as a way to get rid of one"
        )

        # While disabled: deleting it is permanent.
        hass.config_entries.async_update_entry(entry, options={})
        await hass.async_block_till_done()
        assert hass.states.get(CHEAP_TODAY).state == "unavailable"

        registry.async_remove(CHEAP_TODAY)
        await hass.async_block_till_done()
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

        assert registry.async_get(CHEAP_TODAY) is None, "the removal did not stick"
        assert hass.states.get(CHEAP_TODAY) is None
    finally:
        freezer.stop()


async def test_a_deleted_entity_returns_when_the_feature_is_enabled_again(hass, api):
    """Deleting a leftover is not a permanent opt-out of the feature."""
    entry = make_entry(cheap=120)
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        registry = er.async_get(hass)

        hass.config_entries.async_update_entry(entry, options={})
        await hass.async_block_till_done()
        registry.async_remove(CHEAP_TODAY)
        await hass.async_block_till_done()
        assert registry.async_get(CHEAP_TODAY) is None

        hass.config_entries.async_update_entry(
            entry,
            options={
                CONF_OPTIMAL_CHEAP_ENABLED: True,
                CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 120,
            },
        )
        await hass.async_block_till_done()

        assert registry.async_get(CHEAP_TODAY) is not None
        assert hass.states.get(CHEAP_TODAY).state != "unavailable"
        assert not [e for e in registered(hass) if e.endswith("_2")]
    finally:
        freezer.stop()


async def test_the_binary_sensor_follows_the_same_lifecycle_as_its_sensors(hass, api):
    """One toggle, one behaviour: the binary sensor is not a special case."""
    entry = make_entry(cheap=120)
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        registry = er.async_get(hass)
        registry.async_update_entity(CHEAP_NOW, name="Cheap window active")
        await hass.async_block_till_done()

        hass.config_entries.async_update_entry(entry, options={})
        await hass.async_block_till_done()
        assert registry.async_get(CHEAP_NOW) is not None
        assert hass.states.get(CHEAP_NOW).state == "unavailable"

        hass.config_entries.async_update_entry(
            entry,
            options={
                CONF_OPTIMAL_CHEAP_ENABLED: True,
                CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 120,
            },
        )
        await hass.async_block_till_done()
        assert registry.async_get(CHEAP_NOW).name == "Cheap window active"
        assert hass.states.get(CHEAP_NOW).state in ("on", "off")
    finally:
        freezer.stop()


async def test_changing_only_the_duration_keeps_the_same_entities(hass, api):
    """Retuning a duration is a value change, not an entity change."""
    entry = make_entry(cheap=120)
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        before = registered(hass)
        for duration in (15, 60, 180, 240, 720, 120):
            hass.config_entries.async_update_entry(
                entry,
                options={
                    CONF_OPTIMAL_CHEAP_ENABLED: True,
                    CONF_OPTIMAL_CHEAP_DURATION_MINUTES: duration,
                },
            )
            await hass.async_block_till_done()
            assert registered(hass) == before
            assert hass.states.get(CHEAP_TODAY).attributes["duration_minutes"] == (
                duration
            )
    finally:
        freezer.stop()


async def test_the_documented_option_sequence_accumulates_nothing(hass, api):
    """disabled -> cheap 120 -> cheap 180 -> expensive 60 -> off -> on again.

    Exactly the sequence a user retuning the feature would work through. The
    entity set, the coordinator count, the client count and the quarter-boundary
    listener count must all be the same at the end as after a single setup.
    """
    listener_registrations: list[dict[str, Any]] = []
    real_track = coordinator_module.async_track_time_change

    def recording(hass_arg, action, **kwargs):
        listener_registrations.append(kwargs)
        return real_track(hass_arg, action, **kwargs)

    # The entry is set up disabled, so the sequence starts at the first real
    # change. Re-submitting identical options is a no-op in Home Assistant and
    # would not reload at all, which would make the listener count below lie.
    sequence = [
        {CONF_OPTIMAL_CHEAP_ENABLED: True, CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 120},
        {CONF_OPTIMAL_CHEAP_ENABLED: True, CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 180},
        {
            CONF_OPTIMAL_CHEAP_ENABLED: True,
            CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 180,
            CONF_OPTIMAL_EXPENSIVE_ENABLED: True,
            CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES: 60,
        },
        {
            CONF_OPTIMAL_CHEAP_ENABLED: False,
            CONF_OPTIMAL_EXPENSIVE_ENABLED: True,
            CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES: 60,
        },
        {
            CONF_OPTIMAL_CHEAP_ENABLED: True,
            CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 180,
            CONF_OPTIMAL_EXPENSIVE_ENABLED: True,
            CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES: 60,
        },
    ]

    entry = make_entry()
    with patch.object(coordinator_module, "async_track_time_change", recording):
        freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
        try:
            per_reload_costs: list[int] = []
            for options in sequence:
                before = len(api.calls)
                hass.config_entries.async_update_entry(entry, options=options)
                await hass.async_block_till_done()
                per_reload_costs.append(len(api.calls) - before)

                # The v0.1.6 entities are present and healthy throughout.
                ids = registered(hass)
                assert len([i for i in ids if i not in ALL_OPTIMAL_ENTITIES]) == (
                    BASE_ENTITY_COUNT
                )
                assert not [i for i in ids if i.endswith("_2")]

            assert set(registered(hass)) - set(ALL_OPTIMAL_ENTITIES) != set()
            assert set(ALL_OPTIMAL_ENTITIES) <= set(registered(hass))

            # One coordinator, one client, one listener per load -- never two
            # for the same load, and never a growing multiplier.
            coordinator = entry.runtime_data
            assert coordinator.update_interval is None
            assert len(listener_registrations) == 1 + len(sequence)
            assert per_reload_costs == [2] * len(sequence), per_reload_costs
        finally:
            freezer.stop()


async def test_twelve_step_option_stress_sequence(hass, api):
    """A long, realistic retuning session leaves exactly a single setup behind.

    Twelve option changes covering every transition that exists: on, off,
    duration-only, one feature at a time, both at once, and back to nothing. The
    footprint after all of it must equal the footprint after one setup.
    """
    listener_registrations: list[dict[str, Any]] = []
    real_track = coordinator_module.async_track_time_change

    def recording(hass_arg, action, **kwargs):
        listener_registrations.append(kwargs)
        return real_track(hass_arg, action, **kwargs)

    cheap_on = {
        CONF_OPTIMAL_CHEAP_ENABLED: True,
        CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 120,
    }
    sequence: list[dict[str, Any]] = [
        {**cheap_on},
        {CONF_OPTIMAL_CHEAP_ENABLED: True, CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 180},
        {
            CONF_OPTIMAL_CHEAP_ENABLED: True,
            CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 180,
            CONF_OPTIMAL_EXPENSIVE_ENABLED: True,
            CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES: 60,
        },
        {
            CONF_OPTIMAL_EXPENSIVE_ENABLED: True,
            CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES: 60,
        },
        {},
        {CONF_OPTIMAL_CHEAP_ENABLED: True, CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 30},
        {
            CONF_OPTIMAL_CHEAP_ENABLED: True,
            CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 30,
            CONF_OPTIMAL_EXPENSIVE_ENABLED: True,
            CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES: 240,
        },
        {
            CONF_OPTIMAL_EXPENSIVE_ENABLED: True,
            CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES: 240,
        },
        {**cheap_on},
        {},
        {
            CONF_OPTIMAL_CHEAP_ENABLED: True,
            CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 120,
            CONF_OPTIMAL_EXPENSIVE_ENABLED: True,
            CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES: 120,
        },
        {},
    ]

    entry = make_entry()
    with patch.object(coordinator_module, "async_track_time_change", recording):
        freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
        try:
            registry = er.async_get(hass)
            unique_ids_seen: list[set[str]] = []
            per_reload_costs: list[int] = []

            for options in sequence:
                before = len(api.calls)
                hass.config_entries.async_update_entry(entry, options=options)
                await hass.async_block_till_done()
                per_reload_costs.append(len(api.calls) - before)

                ids = registered(hass)
                # No duplicates, ever, in any state of the sequence.
                assert not [i for i in ids if i.endswith(("_2", "_3"))], ids
                assert len(ids) == len(set(ids))
                # The 19 v0.1.6 entities are untouched throughout.
                assert len([i for i in ids if i not in ALL_OPTIMAL_ENTITIES]) == (
                    BASE_ENTITY_COUNT
                )
                unique_ids = {registry.async_get(i).unique_id for i in ids}
                assert len(unique_ids) == len(ids), "duplicate unique id"
                unique_ids_seen.append(unique_ids)

            # One coordinator, one client, one listener per load.
            coordinator = entry.runtime_data
            assert coordinator.update_interval is None
            assert len(listener_registrations) == 1 + len(sequence)
            assert all(
                registration["minute"] == [0, 15, 30, 45]
                for registration in listener_registrations
            )
            # Flat per-reload cost: no multiplier creeping in over 12 reloads.
            assert per_reload_costs == [2] * len(sequence), per_reload_costs
            # The final unique-id set is a superset of every earlier one, and
            # never grew beyond the 19 + 6 maximum.
            assert len(unique_ids_seen[-1]) <= BASE_ENTITY_COUNT + 6
        finally:
            freezer.stop()


@pytest.mark.parametrize(
    ("cheap", "expensive", "registered_count", "available_count"),
    [
        (None, None, BASE_ENTITY_COUNT, BASE_ENTITY_COUNT),
        (120, None, BASE_ENTITY_COUNT + 3, BASE_ENTITY_COUNT + 3),
        (None, 120, BASE_ENTITY_COUNT + 3, BASE_ENTITY_COUNT + 3),
        (120, 120, BASE_ENTITY_COUNT + 6, BASE_ENTITY_COUNT + 6),
    ],
)
async def test_entity_counts_per_configuration(
    hass, api, cheap, expensive, registered_count, available_count
):
    """The exact registered and available entity count for each configuration.

    On a fresh entry the two numbers are equal, because an entity is only ever
    registered for a feature that is switched on.
    """
    freezer, _ = await setup_at(
        hass, make_entry(cheap=cheap, expensive=expensive), market_time(DAY, 14, 7)
    )
    try:
        ids = registered(hass)
        assert len(ids) == registered_count
        live = [
            entity_id
            for entity_id in ids
            if (state := hass.states.get(entity_id)) is not None
            and state.state != "unavailable"
        ]
        assert len(live) == available_count
    finally:
        freezer.stop()


async def test_entity_counts_after_a_feature_is_switched_off(hass, api):
    """Once used and switched off, an entity stays registered but unavailable."""
    entry = make_entry(cheap=120, expensive=120)
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        assert len(registered(hass)) == BASE_ENTITY_COUNT + 6

        hass.config_entries.async_update_entry(entry, options={})
        await hass.async_block_till_done()

        ids = registered(hass)
        assert len(ids) == BASE_ENTITY_COUNT + 6, "registered count is unchanged"
        live = [
            entity_id
            for entity_id in ids
            if hass.states.get(entity_id).state != "unavailable"
        ]
        assert len(live) == BASE_ENTITY_COUNT, "only the v0.1.6 entities are live"
    finally:
        freezer.stop()


async def test_one_quarter_tick_still_refreshes_once_after_the_sequence(hass, api):
    """A leaked scheduler from an earlier load would double-refresh here."""
    refreshes: list[datetime] = []
    original = coordinator_module.FrankQuarterPricesCoordinator._async_update_data

    async def counting(self):
        refreshes.append(dt_util.now())
        return await original(self)

    entry = make_entry()
    with patch.object(
        coordinator_module.FrankQuarterPricesCoordinator,
        "_async_update_data",
        counting,
    ):
        freezer, frozen = await setup_at(hass, entry, market_time(DAY, 14, 7))
        try:
            for enabled in (True, False, True, False, True):
                hass.config_entries.async_update_entry(
                    entry,
                    options={
                        CONF_OPTIMAL_CHEAP_ENABLED: enabled,
                        CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 120,
                    },
                )
                await hass.async_block_till_done()

            refreshes.clear()
            await tick(hass, frozen, market_time(DAY, 14, 15, 3))
            assert len(refreshes) == 1
        finally:
            freezer.stop()


async def test_unload_and_setup_again_is_clean(hass, api):
    """A full unload/setup cycle recreates exactly the same entity set."""
    entry = make_entry(cheap=120, expensive=120)
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        before = registered(hass)

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.NOT_LOADED
        for entity_id in ALL_OPTIMAL_ENTITIES:
            assert hass.states.get(entity_id).state == "unavailable"

        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert registered(hass) == before
        assert hass.states.get(CHEAP_TODAY).state != "unavailable"
    finally:
        freezer.stop()


async def test_reload_and_two_unload_setup_cycles_leave_one_of_everything(hass, api):
    """Interleave an options reload with two full unload/setup cycles.

    The single-cycle test above proves one unload/setup round trip is clean.
    What it cannot see is anything that accumulates: a coordinator that is
    replaced but not discarded, a quarter-boundary listener re-registered
    without the previous one being cancelled, a second client quietly created
    on the second setup. Those only become visible once the entry is torn down
    and brought back more than once, with an options reload mixed in so the
    reload path and the unload path are exercised against each other rather
    than in isolation.

    The chain is setup -> options reload -> unload -> setup -> unload -> setup:
    four loads and two unloads. The footprint afterwards must equal the
    footprint after a single setup, and the user's renamed entity must survive
    all of it, because an automation written against it has to keep working
    across a restart.
    """
    listener_registrations: list[dict[str, Any]] = []
    real_track = coordinator_module.async_track_time_change

    def recording(hass_arg, action, **kwargs):
        listener_registrations.append(kwargs)
        return real_track(hass_arg, action, **kwargs)

    def live_ids(attr: str) -> set[int]:
        """Return the distinct coordinator (or client) objects behind the entities."""
        return {
            id(
                getattr(
                    hass.data["entity_components"][entity_id.split(".")[0]]
                    .get_entity(entity_id)
                    .coordinator,
                    attr,
                    None,
                )
                if attr
                else hass.data["entity_components"][entity_id.split(".")[0]]
                .get_entity(entity_id)
                .coordinator
            )
            for entity_id in registered(hass)
        }

    def assert_healthy(step: str) -> None:
        """Every planner entity is present exactly once and actually reporting."""
        ids = registered(hass)
        assert not [i for i in ids if i.endswith(("_2", "_3"))], f"{step}: {ids}"
        assert len(ids) == len(set(ids)), step
        assert len(ids) == BASE_ENTITY_COUNT + 6, step
        # One coordinator and one client serve all 25 entities, every time.
        assert live_ids("") == {id(entry.runtime_data)}, step
        assert len(live_ids("client")) == 1, step

    entry = make_entry(cheap=120, expensive=120)
    custom_id = "sensor.my_ev_cheapest_window"

    with patch.object(coordinator_module, "async_track_time_change", recording):
        freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
        try:
            registry = er.async_get(hass)
            assert len(listener_registrations) == 1

            # The user renames one planner entity before any of the churn.
            original_row_id = registry.async_get(CHEAP_TODAY).id
            original_unique_id = registry.async_get(CHEAP_TODAY).unique_id
            registry.async_update_entity(CHEAP_TODAY, new_entity_id=custom_id)
            await hass.async_block_till_done()

            # Baseline is taken *after* the rename, so the comparison at the end
            # asserts the renamed set survives rather than the default one.
            baseline = registered(hass)
            calls_after_setup = len(api.calls)

            # 1. Options reload: retune the cheap duration in place.
            hass.config_entries.async_update_entry(
                entry,
                options={
                    CONF_OPTIMAL_CHEAP_ENABLED: True,
                    CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 180,
                    CONF_OPTIMAL_EXPENSIVE_ENABLED: True,
                    CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES: 120,
                },
            )
            await hass.async_block_till_done()
            assert_healthy("after options reload")

            # 2/4. Two full unload -> setup cycles.
            for cycle in (1, 2):
                assert await hass.config_entries.async_unload(entry.entry_id)
                await hass.async_block_till_done()
                assert entry.state is ConfigEntryState.NOT_LOADED

                # An unloaded entry reports unavailable, not a stale window and
                # not a vanished entity: an automation can still see it.
                assert hass.states.get(custom_id).state == "unavailable"
                for entity_id in ALL_OPTIMAL_ENTITIES:
                    if entity_id == CHEAP_TODAY:
                        continue
                    assert hass.states.get(entity_id).state == "unavailable", cycle

                assert await hass.config_entries.async_setup(entry.entry_id)
                await hass.async_block_till_done()
                assert_healthy(f"after unload/setup cycle {cycle}")
                assert hass.states.get(custom_id).state != "unavailable", cycle

            # Four loads in total, each registering exactly one quarter-boundary
            # listener on the real boundaries — no leak, no free-running interval.
            assert len(listener_registrations) == 4
            assert all(
                registration["minute"] == [0, 15, 30, 45]
                for registration in listener_registrations
            )
            assert entry.runtime_data.update_interval is None

            # Three further loads at the flat two-requests-per-load rate; the
            # unloads themselves cost nothing.
            assert len(api.calls) - calls_after_setup == 6, api.calls

            # The registry came through the whole chain untouched: same rows,
            # same ids, and no twin on the default entity id.
            assert registered(hass) == baseline
            restored = registry.async_get(custom_id)
            assert restored is not None, "the user's custom entity id was lost"
            assert restored.id == original_row_id, "a new registry row was created"
            assert restored.unique_id == original_unique_id
            assert registry.async_get(CHEAP_TODAY) is None, (
                "a duplicate appeared on the default entity id"
            )
        finally:
            freezer.stop()


# --- The published contract --------------------------------------------------


_PERIOD_SENSOR_ATTRS = {
    "start",
    "end",
    "start_time",
    "end_time",
    "duration_minutes",
    "average_price_eur_kwh",
    "min_price_eur_kwh",
    "max_price_eur_kwh",
    "block_count",
    "resolution_minutes",
}
_PERIOD_BINARY_ATTRS = {"start", "end", "duration_minutes", "average_price_eur_kwh"}
_HA_MANAGED_ATTRS = {
    "friendly_name",
    "device_class",
    "state_class",
    "unit_of_measurement",
    "icon",
}


@pytest.mark.parametrize(
    ("entity_id", "name", "icon"),
    [
        (CHEAP_TODAY, "Frank Optimal cheap period today", "mdi:clock-check"),
        (CHEAP_TOMORROW, "Frank Optimal cheap period tomorrow", "mdi:clock-check"),
        (EXPENSIVE_TODAY, "Frank Optimal expensive period today", "mdi:clock-alert"),
        (
            EXPENSIVE_TOMORROW,
            "Frank Optimal expensive period tomorrow",
            "mdi:clock-alert",
        ),
    ],
)
async def test_period_sensor_contract(hass, api, entity_id, name, icon):
    """State is a timestamp; the attribute key set is fixed and compact."""
    freezer, _ = await setup_at(
        hass, make_entry(cheap=120, expensive=120), market_time(DAY, 14, 7)
    )
    try:
        state = hass.states.get(entity_id)
        assert state.state not in ("unavailable", "unknown")
        assert state.attributes["friendly_name"] == name
        assert state.attributes["device_class"] == "timestamp"
        assert state.attributes["icon"] == icon
        assert state.attributes.get("state_class") is None
        assert state.attributes.get("unit_of_measurement") is None
        assert set(state.attributes) - _HA_MANAGED_ATTRS == _PERIOD_SENSOR_ATTRS

        # The state really parses back to an aware datetime, and it is the
        # window start the attributes describe.
        parsed = datetime.fromisoformat(state.state)
        assert parsed.tzinfo is not None
        assert dt_util.as_utc(parsed) == dt_util.as_utc(
            datetime.fromisoformat(state.attributes["start"])
        )
        # Deliberately NOT the whole daily array.
        assert "prices" not in state.attributes
    finally:
        freezer.stop()


@pytest.mark.parametrize(
    ("entity_id", "name", "icon"),
    [
        (CHEAP_NOW, "Frank Optimal cheap period", "mdi:clock-check"),
        (EXPENSIVE_NOW, "Frank Optimal expensive period", "mdi:clock-alert"),
    ],
)
async def test_period_binary_sensor_contract(hass, api, entity_id, name, icon):
    """The binary sensors stay on/off with a compact attribute set."""
    freezer, _ = await setup_at(
        hass, make_entry(cheap=120, expensive=120), market_time(DAY, 14, 7)
    )
    try:
        state = hass.states.get(entity_id)
        assert state.state in ("on", "off")
        assert state.attributes["friendly_name"] == name
        assert state.attributes["icon"] == icon
        assert set(state.attributes) - _HA_MANAGED_ATTRS == _PERIOD_BINARY_ATTRS
    finally:
        freezer.stop()


async def test_the_planner_entities_stay_far_under_the_recorder_limit(hass, api):
    """The Recorder problem this release fixes must not be reintroduced."""
    freezer, _ = await setup_at(
        hass, make_entry(cheap=720, expensive=720), market_time(DAY, 14, 7)
    )
    try:
        for entity_id in ALL_OPTIMAL_ENTITIES:
            attrs = dict(hass.states.get(entity_id).attributes)
            size = len(json.dumps(attrs, default=str))
            assert size < MAX_STATE_ATTRS_BYTES // 10, f"{entity_id} is {size} bytes"
            # And none of the planner's own attributes was excluded from
            # history -- they are small enough to be worth recording in full.
            # (Home Assistant's sensor component excludes ``options`` itself,
            # for every sensor in every integration; that is not ours.)
            excluded = hass.states.get(entity_id).state_info["unrecorded_attributes"]
            assert not (excluded & set(attrs)), f"{entity_id} excludes {excluded}"
    finally:
        freezer.stop()


async def test_the_window_matches_the_shaped_day(hass, api):
    """End to end: the cheap window is the 10:00-12:00 dip, expensive 19:00-21:00."""
    freezer, _ = await setup_at(
        hass, make_entry(cheap=120, expensive=120), market_time(DAY, 14, 7)
    )
    try:
        assert hhmm(CHEAP_TODAY, hass) == ("10:00", "12:00")
        assert hhmm(EXPENSIVE_TODAY, hass) == ("19:00", "21:00")
        assert hass.states.get(CHEAP_TODAY).attributes["block_count"] == 8
        assert hass.states.get(CHEAP_TODAY).attributes["resolution_minutes"] == 15
        assert (
            hass.states.get(CHEAP_TODAY).attributes["average_price_eur_kwh"]
            < hass.states.get(EXPENSIVE_TODAY).attributes["average_price_eur_kwh"]
        )
    finally:
        freezer.stop()


@pytest.mark.parametrize("duration", [15, 30, 60, 120, 240, 720])
async def test_every_duration_publishes_an_exact_window(hass, api, duration):
    """Whatever the user picks, the published window is exactly that long."""
    freezer, _ = await setup_at(
        hass,
        make_entry(cheap=duration, expensive=duration),
        market_time(DAY, 14, 7),
    )
    try:
        for entity_id in (CHEAP_TODAY, EXPENSIVE_TODAY):
            attrs = hass.states.get(entity_id).attributes
            assert attrs["duration_minutes"] == duration
            start = dt_util.as_utc(datetime.fromisoformat(attrs["start"]))
            end = dt_util.as_utc(datetime.fromisoformat(attrs["end"]))
            assert end - start == timedelta(minutes=duration)
    finally:
        freezer.stop()


# --- Complete-day safety -----------------------------------------------------


def assert_no_period(hass, entity_ids) -> None:
    """Assert the given planner entities are unavailable and leak no window."""
    for entity_id in entity_ids:
        state = hass.states.get(entity_id)
        assert state is not None, f"{entity_id} was not created at all"
        assert state.state == "unavailable", (
            f"{entity_id} published {state.state!r} from an unusable day"
        )
        stale = _PERIOD_SENSOR_ATTRS & set(state.attributes)
        assert not stale, f"{entity_id} still exposes a stale window: {stale}"


@pytest.mark.parametrize("kept", [20, 48, 95])
async def test_an_incomplete_today_publishes_no_period(hass, api, kept):
    """20, 48 or 95 of 96 quarters is not "the cheapest window of today"."""
    api.responses[DAY] = shaped_day(DAY)[:kept]
    freezer, _ = await setup_at(
        hass, make_entry(cheap=120, expensive=120), market_time(DAY, 3, 7)
    )
    try:
        assert_no_period(hass, (CHEAP_TODAY, EXPENSIVE_TODAY))
        for entity_id in (CHEAP_NOW, EXPENSIVE_NOW):
            state = hass.states.get(entity_id)
            assert state.state == "unavailable"
            assert state.state != "off", "cannot-say must differ from not-now"
    finally:
        freezer.stop()


async def test_a_gap_in_a_full_length_day_publishes_no_period(hass, api):
    """96 blocks with a hole is not a complete day."""
    blocks = shaped_day(DAY)
    del blocks[40]
    blocks.append(blocks[39])  # restore the count to 96
    api.responses[DAY] = blocks

    freezer, _ = await setup_at(hass, make_entry(cheap=120), market_time(DAY, 3, 7))
    try:
        assert int(hass.states.get("sensor.frank_prices_today").state) == 96
        assert_no_period(hass, (CHEAP_TODAY,))
    finally:
        freezer.stop()


async def test_an_overlap_in_a_full_length_day_publishes_no_period(hass, api):
    """96 blocks with an overlap is not a complete day either."""
    blocks = shaped_day(DAY)
    blocks[40] = build_block_span(blocks[40]["from"], blocks[41]["till"], NORMAL_MP)
    api.responses[DAY] = blocks

    freezer, _ = await setup_at(hass, make_entry(cheap=120), market_time(DAY, 3, 7))
    try:
        assert_no_period(hass, (CHEAP_TODAY,))
    finally:
        freezer.stop()


@pytest.mark.parametrize(
    ("day", "expected_blocks"),
    [(SPRING_FORWARD, 92), (DAY, 96), (FALL_BACK, 100)],
)
async def test_complete_dst_days_publish_a_period(hass, api, day, expected_blocks):
    """92-, 96- and 100-quarter days are all complete market days."""
    freezer, _ = await setup_at(
        hass, make_entry(cheap=180, expensive=180), market_time(day, 14, 7)
    )
    try:
        assert int(hass.states.get("sensor.frank_prices_today").state) == (
            expected_blocks
        )
        for entity_id in (CHEAP_TODAY, EXPENSIVE_TODAY):
            attrs = hass.states.get(entity_id).attributes
            assert attrs["duration_minutes"] == 180
            start = dt_util.as_utc(datetime.fromisoformat(attrs["start"]))
            end = dt_util.as_utc(datetime.fromisoformat(attrs["end"]))
            # Real elapsed time, even across the transition.
            assert end - start == timedelta(minutes=180)
            assert attrs["block_count"] == 12
    finally:
        freezer.stop()


async def test_the_period_appears_once_the_day_completes(hass, api):
    """A day that fills in later starts publishing at that moment."""
    api.responses[DAY] = shaped_day(DAY)[:48]

    freezer, frozen = await setup_at(
        hass, make_entry(cheap=120), market_time(DAY, 10, 7)
    )
    try:
        assert_no_period(hass, (CHEAP_TODAY,))

        del api.responses[DAY]
        await tick(hass, frozen, market_time(DAY, 10, 15, 3))

        assert hhmm(CHEAP_TODAY, hass) == ("10:00", "12:00")
    finally:
        freezer.stop()


async def test_a_duration_the_day_cannot_compose_is_unavailable(hass, api):
    """Hourly data with a 90-minute request: unavailable, never interpolated."""
    api.responses[DAY] = build_local_day_blocks(DAY, None, resolution_minutes=60)
    api.responses[DAY + timedelta(days=1)] = build_local_day_blocks(
        DAY + timedelta(days=1), None, resolution_minutes=60
    )

    freezer, _ = await setup_at(hass, make_entry(cheap=90), market_time(DAY, 14, 7))
    try:
        assert (
            hass.states.get("sensor.frank_prices_today").attributes[
                "resolution_minutes"
            ]
            == 60
        )
        assert_no_period(hass, (CHEAP_TODAY, CHEAP_TOMORROW))
        assert hass.states.get(CHEAP_NOW).state == "unavailable"
    finally:
        freezer.stop()


async def test_a_compatible_duration_works_on_hourly_data(hass, api):
    """The same hourly day answers a 120-minute request perfectly well."""
    api.responses[DAY] = build_local_day_blocks(DAY, None, resolution_minutes=60)

    freezer, _ = await setup_at(hass, make_entry(cheap=120), market_time(DAY, 14, 7))
    try:
        attrs = hass.states.get(CHEAP_TODAY).attributes
        assert attrs["duration_minutes"] == 120
        assert attrs["block_count"] == 2
        assert attrs["resolution_minutes"] == 60
    finally:
        freezer.stop()


async def test_a_flat_day_still_yields_a_period(hass, api):
    """The deliberate difference from the price zones.

    A flat day makes both zones unavailable — there is no cheap-versus-expensive
    distinction to draw — but the cheapest contiguous two hours is still a
    perfectly well-defined answer, and the tie-break makes it the earliest.
    """
    flat = build_local_day_blocks(DAY, 0.09)
    api.responses[DAY] = flat

    freezer, _ = await setup_at(
        hass, make_entry(cheap=120, expensive=120), market_time(DAY, 14, 7)
    )
    try:
        # The zones are withheld...
        assert hass.states.get("sensor.frank_cheap_zone_start_today").state == (
            "unavailable"
        )
        # ...but the optimal periods are not.
        for entity_id in (CHEAP_TODAY, EXPENSIVE_TODAY):
            assert hhmm(entity_id, hass) == ("00:00", "02:00")
    finally:
        freezer.stop()


# --- Corrupt stored options --------------------------------------------------
#
# None of these can be produced by the options form; they model a hand-edited
# config entry or a corrupted .storage file. The rule is that the planner refuses
# to run rather than silently planning on a substituted duration.


@pytest.mark.parametrize(
    "stored", [0, -15, -500, 10, 17, 22.5, "abc", "120", None, 721, 9999, True]
)
async def test_a_corrupt_duration_makes_the_planner_unavailable(hass, api, stored):
    """An unusable stored duration never becomes a silent 120-minute window."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"country": "NL"},
        options={
            CONF_OPTIMAL_CHEAP_ENABLED: True,
            CONF_OPTIMAL_CHEAP_DURATION_MINUTES: stored,
        },
        unique_id="NL",
    )
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        assert entry.state is ConfigEntryState.LOADED, "a bad option must not crash"
        assert_no_period(hass, (CHEAP_TODAY, CHEAP_TOMORROW))
        assert hass.states.get(CHEAP_NOW).state == "unavailable"
        # And emphatically not the default window it would have picked at 120.
        assert hass.states.get(CHEAP_TODAY).state != "2026-08-06T08:00:00+00:00"
    finally:
        freezer.stop()


async def test_a_corrupt_duration_is_logged_once_not_every_quarter(hass, api, caplog):
    """The cause is visible in the log, without filling it 96 times a day."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"country": "NL"},
        options={
            CONF_OPTIMAL_CHEAP_ENABLED: True,
            CONF_OPTIMAL_CHEAP_DURATION_MINUTES: -500,
        },
        unique_id="NL",
    )
    caplog.set_level("WARNING")
    freezer, frozen = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        moment = market_time(DAY, 14, 15, 3)
        for _ in range(6):
            await tick(hass, frozen, moment)
            moment += timedelta(minutes=15)

        warnings = [
            record
            for record in caplog.records
            if record.levelname == "WARNING"
            and "optimal_cheap_duration_minutes" in record.getMessage()
        ]
        assert len(warnings) == 1, f"logged {len(warnings)} times"
        assert "-500" in warnings[0].getMessage()
        assert "unavailable" in warnings[0].getMessage()
    finally:
        freezer.stop()


async def test_a_corrupt_duration_does_not_disturb_anything_else(hass, api):
    """One broken planner option must not take the integration down with it."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"country": "NL"},
        options={
            CONF_OPTIMAL_CHEAP_ENABLED: True,
            CONF_OPTIMAL_CHEAP_DURATION_MINUTES: "abc",
            CONF_OPTIMAL_EXPENSIVE_ENABLED: True,
            CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES: 120,
        },
        unique_id="NL",
    )
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        # The healthy sibling feature is entirely unaffected.
        assert hhmm(EXPENSIVE_TODAY, hass) == ("19:00", "21:00")
        assert hass.states.get(EXPENSIVE_NOW).state in ("on", "off")
        # As is every v0.1.6 entity.
        assert hass.states.get("sensor.frank_current_price").state != "unavailable"
        assert (
            hass.states.get("sensor.frank_cheap_zone_start_today").state
            != "unavailable"
        )
        assert int(hass.states.get("sensor.frank_prices_today").state) == 96
        # And no extra request was provoked by the bad value.
        assert len(api.calls) == 2
    finally:
        freezer.stop()


async def test_a_corrupt_duration_on_a_disabled_feature_is_ignored(hass, api):
    """A stale bad duration next to a disabled toggle is not a problem."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"country": "NL"},
        options={
            CONF_OPTIMAL_CHEAP_ENABLED: False,
            CONF_OPTIMAL_CHEAP_DURATION_MINUTES: -1,
        },
        unique_id="NL",
    )
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        assert entry.state is ConfigEntryState.LOADED
        assert len(registered(hass)) == BASE_ENTITY_COUNT
    finally:
        freezer.stop()


async def test_correcting_a_corrupt_duration_recovers(hass, api):
    """Fixing the value in the UI brings the planner straight back."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"country": "NL"},
        options={
            CONF_OPTIMAL_CHEAP_ENABLED: True,
            CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 0,
        },
        unique_id="NL",
    )
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        assert_no_period(hass, (CHEAP_TODAY,))

        hass.config_entries.async_update_entry(
            entry,
            options={
                CONF_OPTIMAL_CHEAP_ENABLED: True,
                CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 120,
            },
        )
        await hass.async_block_till_done()

        assert hhmm(CHEAP_TODAY, hass) == ("10:00", "12:00")
    finally:
        freezer.stop()


# --- Today and tomorrow ------------------------------------------------------


async def test_tomorrow_is_unavailable_before_publication(hass, api):
    """No tomorrow data, no tomorrow window; today is unaffected."""
    api.responses[DAY + timedelta(days=1)] = []

    freezer, _ = await setup_at(hass, make_entry(cheap=120), market_time(DAY, 8, 7))
    try:
        assert hass.states.get(CHEAP_TODAY).state != "unavailable"
        assert_no_period(hass, (CHEAP_TOMORROW,))
    finally:
        freezer.stop()


async def test_a_partial_tomorrow_publishes_no_period(hass, api):
    """Half of tomorrow is not tomorrow."""
    tomorrow = DAY + timedelta(days=1)
    api.responses[tomorrow] = shaped_day(tomorrow)[:48]

    freezer, _ = await setup_at(hass, make_entry(cheap=120), market_time(DAY, 14, 7))
    try:
        assert_no_period(hass, (CHEAP_TOMORROW,))
        assert hass.states.get(CHEAP_TODAY).state != "unavailable"
    finally:
        freezer.stop()


async def test_tomorrow_appears_when_the_day_is_published(hass, api):
    """It shows up on the next quarter tick, with no extra request of its own."""
    tomorrow = DAY + timedelta(days=1)
    api.responses[tomorrow] = []

    freezer, frozen = await setup_at(
        hass, make_entry(cheap=120), market_time(DAY, 13, 0, 3)
    )
    try:
        assert_no_period(hass, (CHEAP_TOMORROW,))
        requests_for_tomorrow = api.count(tomorrow)

        del api.responses[tomorrow]
        await tick(hass, frozen, market_time(DAY, 13, 15, 3))

        assert hhmm(CHEAP_TOMORROW, hass) == ("10:00", "12:00")
        # Exactly one more request -- the ordinary tomorrow poll the coordinator
        # already made in v0.1.5, not a planner-specific one.
        assert api.count(tomorrow) == requests_for_tomorrow + 1
    finally:
        freezer.stop()


async def test_tomorrow_is_stable_across_quarter_ticks(hass, api):
    """Ticking through the afternoon does not move the planned window."""
    freezer, frozen = await setup_at(
        hass, make_entry(cheap=120), market_time(DAY, 14, 7)
    )
    try:
        expected = hhmm(CHEAP_TOMORROW, hass)
        calls_before = len(api.calls)

        moment = market_time(DAY, 14, 15, 3)
        for _ in range(8):
            await tick(hass, frozen, moment)
            assert hhmm(CHEAP_TOMORROW, hass) == expected
            moment += timedelta(minutes=15)

        assert len(api.calls) == calls_before
    finally:
        freezer.stop()


async def test_midnight_rollover_turns_tomorrow_into_today(hass, api):
    """Yesterday's tomorrow becomes today's window, free of charge."""
    tomorrow = DAY + timedelta(days=1)
    freezer, frozen = await setup_at(
        hass, make_entry(cheap=120, expensive=120), market_time(DAY, 23, 45, 3)
    )
    try:
        planned = hass.states.get(CHEAP_TOMORROW).state
        assert dt_util.as_local(datetime.fromisoformat(planned)).date() == tomorrow
        calls_before = len(api.calls)

        await tick(hass, frozen, market_time(tomorrow, 0, 0, 3))

        today_now = hass.states.get(CHEAP_TODAY).state
        assert dt_util.as_utc(datetime.fromisoformat(today_now)) == dt_util.as_utc(
            datetime.fromisoformat(planned)
        )
        assert dt_util.as_local(datetime.fromisoformat(today_now)).date() == tomorrow
        assert len(api.calls) == calls_before  # no request for the rollover
    finally:
        freezer.stop()


async def test_no_stale_yesterday_window_survives_the_rollover(hass, api):
    """A new day that is not yet complete goes unavailable, not stale."""
    tomorrow = DAY + timedelta(days=1)
    api.responses[tomorrow] = shaped_day(tomorrow)[:8]

    freezer, frozen = await setup_at(
        hass, make_entry(cheap=120), market_time(DAY, 23, 45, 3)
    )
    try:
        yesterday_window = hass.states.get(CHEAP_TODAY).state

        await tick(hass, frozen, market_time(tomorrow, 0, 0, 3))

        assert_no_period(hass, (CHEAP_TODAY,))
        assert hass.states.get(CHEAP_TODAY).state != yesterday_window
        assert hass.states.get(CHEAP_NOW).state == "unavailable"
    finally:
        freezer.stop()


async def test_the_binary_sensor_follows_the_new_day_after_midnight(hass, api):
    """The now-sensor switches to the new day's window, not yesterday's."""
    tomorrow = DAY + timedelta(days=1)
    freezer, frozen = await setup_at(
        hass, make_entry(cheap=120), market_time(DAY, 23, 45, 3)
    )
    try:
        assert hass.states.get(CHEAP_NOW).state == "off"

        # Straight to 11:00 the next day, inside the new day's 10:00-12:00 dip.
        await tick(hass, frozen, market_time(tomorrow, 11, 0, 3))

        assert hass.states.get(CHEAP_NOW).state == "on"
        window_start = hass.states.get(CHEAP_NOW).attributes["start"]
        assert dt_util.as_local(datetime.fromisoformat(window_start)).date() == (
            tomorrow
        )
    finally:
        freezer.stop()


# --- The binary-sensor boundary ---------------------------------------------


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
async def test_cheap_binary_boundary_contract(
    hass, api, hour, minute, second, expected
):
    """start <= now < end, checked at every boundary instant."""
    freezer, _ = await setup_at(
        hass, make_entry(cheap=120), market_time(DAY, hour, minute, second)
    )
    try:
        assert hass.states.get(CHEAP_NOW).state == expected
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
async def test_expensive_binary_boundary_contract(
    hass, api, hour, minute, second, expected
):
    """The expensive period obeys the identical rule."""
    freezer, _ = await setup_at(
        hass, make_entry(expensive=120), market_time(DAY, hour, minute, second)
    )
    try:
        assert hass.states.get(EXPENSIVE_NOW).state == expected
    finally:
        freezer.stop()


async def test_the_binary_sensor_agrees_with_its_own_today_sensor(hass, api):
    """At every quarter of the day the two entities describe one window."""
    freezer, frozen = await setup_at(
        hass, make_entry(cheap=120, expensive=120), market_time(DAY, 0, 0, 3)
    )
    try:
        for quarter in range(96):
            moment = market_time(DAY, 0, 0, 3) + timedelta(minutes=15 * quarter)
            await tick(hass, frozen, moment)
            for now_id, today_id in (
                (CHEAP_NOW, CHEAP_TODAY),
                (EXPENSIVE_NOW, EXPENSIVE_TODAY),
            ):
                today_attrs = hass.states.get(today_id).attributes
                start = dt_util.as_utc(datetime.fromisoformat(today_attrs["start"]))
                end = dt_util.as_utc(datetime.fromisoformat(today_attrs["end"]))
                expected = "on" if start <= dt_util.as_utc(moment) < end else "off"
                assert hass.states.get(now_id).state == expected, (
                    f"{now_id} disagrees with {today_id} at {moment}"
                )
                # And it reports the same window it was judged against.
                assert (
                    hass.states.get(now_id).attributes["start"]
                    == (today_attrs["start"])
                )
                assert hass.states.get(now_id).attributes["end"] == today_attrs["end"]
    finally:
        freezer.stop()


async def test_the_binary_sensor_distinguishes_both_fall_back_folds(hass, api):
    """02:30 CEST and 02:30 CET are an hour apart and judged separately."""
    # Price the *first* pass of 02:00-03:00 as the only cheap hour of the day.
    blocks = build_local_day_blocks(FALL_BACK, 0.30)
    for index in (8, 9, 10, 11):
        blocks[index] = build_block_span(
            blocks[index]["from"], blocks[index]["till"], 0.01
        )
    api.responses[FALL_BACK] = blocks

    freezer, frozen = await setup_at(
        hass, make_entry(cheap=60), market_time(FALL_BACK, 1, 0, 3)
    )
    try:
        assert int(hass.states.get("sensor.frank_prices_today").state) == 100

        first_fold = market_time(FALL_BACK, 2, 30, 3, fold=0)
        second_fold = market_time(FALL_BACK, 2, 30, 3, fold=1)
        assert second_fold.astimezone(ZoneInfo("UTC")) - first_fold.astimezone(
            ZoneInfo("UTC")
        ) == timedelta(hours=1)

        await tick(hass, frozen, first_fold)
        assert hass.states.get(CHEAP_NOW).state == "on"

        await tick(hass, frozen, second_fold)
        assert hass.states.get(CHEAP_NOW).state == "off"
    finally:
        freezer.stop()


# --- Market timezone ---------------------------------------------------------


@pytest.mark.parametrize(
    "ha_timezone",
    ["Europe/Amsterdam", "UTC", "Europe/London", "America/New_York", "Asia/Tokyo"],
)
async def test_the_window_is_identical_under_any_ha_timezone(hass, api, ha_timezone):
    """The market day decides, not Home Assistant's display timezone."""
    freezer, frozen = await setup_at(
        hass,
        make_entry(cheap=120, expensive=120),
        market_time(DAY, 11, 0, 3),
        ha_timezone,
    )
    try:
        # The window is the same physical instant whatever the display zone.
        start = dt_util.as_utc(
            datetime.fromisoformat(hass.states.get(CHEAP_TODAY).attributes["start"])
        )
        assert start == market_time(DAY, 10, 0).astimezone(ZoneInfo("UTC"))

        assert hass.states.get(CHEAP_NOW).state == "on"
        assert hass.states.get(EXPENSIVE_NOW).state == "off"

        await tick(hass, frozen, market_time(DAY, 20, 0, 3))
        assert hass.states.get(CHEAP_NOW).state == "off"
        assert hass.states.get(EXPENSIVE_NOW).state == "on"
    finally:
        freezer.stop()


async def test_the_belgian_market_day_is_used_for_belgium(hass):
    """Belgium is judged on Europe/Brussels while Home Assistant runs on UTC."""
    fake = ShapedApi(COUNTRY_BE)
    brussels = ZoneInfo(MARKET_TIMEZONES[COUNTRY_BE])
    moment = datetime(2026, 8, 6, 11, 0, 3, tzinfo=brussels)

    with patch(_CLIENT_METHOD, AsyncMock(side_effect=fake.fetch)):
        entry = make_entry(cheap=120, country=COUNTRY_BE)
        freezer, _ = await setup_at(hass, entry, moment, "UTC")
        try:
            assert hass.states.get(CHEAP_NOW).state == "on"
            start = datetime.fromisoformat(
                hass.states.get(CHEAP_TODAY).attributes["start"]
            )
            assert start.astimezone(brussels).hour == 10
        finally:
            freezer.stop()


# --- Independence from the price zones ---------------------------------------


@pytest.mark.parametrize("margin", [0.0, 5.0, 15.0, 25.0, 49.0])
async def test_the_zone_margin_never_moves_the_optimal_window(hass, api, margin):
    """Every documented margin, one and the same planner window."""
    entry = make_entry(
        cheap=120,
        expensive=120,
        **{
            CONF_CHEAP_ZONE_MARGIN_PERCENT: margin,
            CONF_EXPENSIVE_ZONE_MARGIN_PERCENT: margin,
        },
    )
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        assert hhmm(CHEAP_TODAY, hass) == ("10:00", "12:00")
        assert hhmm(EXPENSIVE_TODAY, hass) == ("19:00", "21:00")
        # The margin really did reach the zones, so this is not a no-op setup.
        assert (
            hass.states.get("sensor.frank_cheap_zone_start_today").attributes[
                "margin_percent"
            ]
            == margin
        )
    finally:
        freezer.stop()


async def test_retuning_a_margin_leaves_the_planner_window_where_it_was(hass, api):
    """Live proof across a reload, not just across two separate setups."""
    entry = make_entry(cheap=120, expensive=120)
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        before = hhmm(CHEAP_TODAY, hass)

        for cheap_margin, expensive_margin in ((0.0, 49.0), (49.0, 0.0), (25.0, 5.0)):
            hass.config_entries.async_update_entry(
                entry,
                options={
                    **dict(entry.options),
                    CONF_CHEAP_ZONE_MARGIN_PERCENT: cheap_margin,
                    CONF_EXPENSIVE_ZONE_MARGIN_PERCENT: expensive_margin,
                },
            )
            await hass.async_block_till_done()
            assert hhmm(CHEAP_TODAY, hass) == before
    finally:
        freezer.stop()


async def test_changing_a_duration_leaves_the_zones_where_they_were(hass, api):
    """The independence holds in the other direction too."""
    entry = make_entry(cheap=120, expensive=120)
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        zone_before = {
            entity_id: hass.states.get(entity_id).state
            for entity_id in (
                "sensor.frank_cheap_zone_start_today",
                "sensor.frank_cheap_zone_end_today",
                "sensor.frank_expensive_zone_start_today",
                "sensor.frank_expensive_zone_end_today",
            )
        }

        for duration in (15, 60, 240, 720):
            hass.config_entries.async_update_entry(
                entry,
                options={
                    CONF_OPTIMAL_CHEAP_ENABLED: True,
                    CONF_OPTIMAL_CHEAP_DURATION_MINUTES: duration,
                    CONF_OPTIMAL_EXPENSIVE_ENABLED: True,
                    CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES: duration,
                },
            )
            await hass.async_block_till_done()

            for entity_id, state in zone_before.items():
                assert hass.states.get(entity_id).state == state, entity_id
    finally:
        freezer.stop()


async def test_the_two_features_can_disagree_and_both_be_right(hass, api):
    """A 15-minute cheap period lands inside the zone; a 12-hour one cannot.

    The clearest demonstration that these answer different questions: the same
    day, the same margins, two durations, two genuinely different windows.
    """
    entry = make_entry(cheap=720)
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        long_window = hhmm(CHEAP_TODAY, hass)
        zone = (
            hass.states.get("sensor.frank_cheap_zone_start_today").attributes["time"],
            hass.states.get("sensor.frank_cheap_zone_end_today").attributes["time"],
        )
        assert zone == ("10:00", "12:00")
        # Twelve hours cannot fit inside a two-hour zone, so it necessarily
        # spans far more of the day -- and that is the correct answer to the
        # question that was asked.
        assert long_window != zone
        assert hass.states.get(CHEAP_TODAY).attributes["duration_minutes"] == 720
    finally:
        freezer.stop()


# --- Zero extra API requests -------------------------------------------------


async def test_enabling_the_planner_adds_no_request(hass, api):
    """Measured A/B: the same setup with and without the feature."""
    freezer, _ = await setup_at(hass, make_entry(), market_time(DAY, 14, 7))
    try:
        without = len(api.calls)
    finally:
        freezer.stop()
    await hass.config_entries.async_unload(
        hass.config_entries.async_entries(DOMAIN)[0].entry_id
    )
    await hass.async_block_till_done()

    api.calls.clear()
    freezer, _ = await setup_at(
        hass, make_entry(cheap=120, expensive=240), market_time(DAY, 14, 7)
    )
    try:
        with_planner = len(api.calls)
        for entity_id in ALL_OPTIMAL_ENTITIES:
            assert hass.states.get(entity_id).state != "unavailable"
    finally:
        freezer.stop()

    assert without == 2  # today + tomorrow, unchanged from v0.1.6
    assert with_planner == without


async def test_reading_the_planner_entities_costs_nothing(hass, api):
    """Fifty reads of six entities, zero requests."""
    freezer, _ = await setup_at(
        hass, make_entry(cheap=120, expensive=120), market_time(DAY, 14, 7)
    )
    try:
        calls_before = len(api.calls)
        for _ in range(50):
            for entity_id in ALL_OPTIMAL_ENTITIES:
                assert dict(hass.states.get(entity_id).attributes) is not None
        assert len(api.calls) == calls_before
    finally:
        freezer.stop()


async def test_quarter_ticks_add_no_planner_request(hass, api):
    """Crossing eight boundaries keeps the v0.1.6 request behaviour exactly."""
    freezer, frozen = await setup_at(
        hass, make_entry(cheap=120, expensive=120), market_time(DAY, 14, 7)
    )
    try:
        calls_before = len(api.calls)
        moment = market_time(DAY, 14, 15, 3)
        for _ in range(8):
            await tick(hass, frozen, moment)
            moment += timedelta(minutes=15)
        assert len(api.calls) == calls_before
    finally:
        freezer.stop()


async def test_an_outage_keeps_the_planner_alive_without_a_request(hass, api):
    """With today cached complete, the window survives a Frank outage."""
    freezer, frozen = await setup_at(
        hass, make_entry(cheap=120), market_time(DAY, 14, 7)
    )
    try:
        before = hass.states.get(CHEAP_TODAY).state
        calls_before = len(api.calls)

        api.responses[DAY] = FrankClientError("outage")
        api.responses[DAY + timedelta(days=1)] = FrankClientError("outage")
        for offset in range(1, 5):
            await tick(hass, frozen, market_time(DAY, 14 + offset, 30, 3))

        assert hass.states.get(CHEAP_TODAY).state == before
        # Today stays cached complete, so it is never re-requested; only the
        # ordinary tomorrow retries can move the counter, never the planner.
        assert api.count(DAY) == api.calls[: calls_before + 1].count(DAY)
    finally:
        freezer.stop()


async def test_each_period_is_derived_once_per_update(hass, api):
    """Three entities read one shared result; they never each re-run the search."""
    from custom_components.frank_quarter_prices import optimal_period

    real = optimal_period.calculate_optimal_period
    derivations: list[tuple[int, str]] = []

    def counting(prices, duration, mode):
        derivations.append((duration, mode))
        return real(prices, duration, mode)

    with patch.object(coordinator_module, "calculate_optimal_period", counting):
        freezer, frozen = await setup_at(
            hass, make_entry(cheap=120, expensive=60), market_time(DAY, 14, 7)
        )
        try:
            # One cheap and one expensive derivation per day, per update.
            assert derivations == [
                (120, "cheap"),
                (120, "cheap"),
                (60, "expensive"),
                (60, "expensive"),
            ]

            derivations.clear()
            await tick(hass, frozen, market_time(DAY, 14, 15, 3))
            assert len(derivations) == 4

            # Reading every entity repeatedly adds no further derivation.
            derivations.clear()
            for _ in range(10):
                for entity_id in ALL_OPTIMAL_ENTITIES:
                    dict(hass.states.get(entity_id).attributes)
            assert derivations == []
        finally:
            freezer.stop()


async def test_a_disabled_feature_is_not_calculated_at_all(hass, api):
    """Off means off: no derivation, not merely no entity."""
    derivations: list[Any] = []
    real = coordinator_module.calculate_optimal_period

    def counting(prices, duration, mode):
        derivations.append(mode)
        return real(prices, duration, mode)

    with patch.object(coordinator_module, "calculate_optimal_period", counting):
        freezer, _ = await setup_at(
            hass, make_entry(cheap=120), market_time(DAY, 14, 7)
        )
        try:
            assert set(derivations) == {"cheap"}
            assert "expensive" not in derivations
        finally:
            freezer.stop()


async def test_one_coordinator_and_one_client_serve_the_planner_too(hass, api):
    """The planner hangs off the existing coordinator, not a second one."""
    freezer, _ = await setup_at(
        hass, make_entry(cheap=120, expensive=120), market_time(DAY, 14, 7)
    )
    try:
        entity_ids = registered(hass)
        assert len(entity_ids) == BASE_ENTITY_COUNT + 6

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


# --- Upgrading an existing installation --------------------------------------


async def test_a_real_v0_1_6_entry_upgrades_without_intervention(hass, api):
    """A v0.1.6 entry gains nothing it did not ask for, and loses nothing."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Frank Quarter Prices (NL)",
        data={"country": "NL"},
        # Exactly what v0.1.6 could have stored, and nothing else.
        options={
            "feed_in_adjustment": -0.017,
            "apply_feed_in_vat": True,
            CONF_CHEAP_ZONE_MARGIN_PERCENT: 20.0,
            CONF_EXPENSIVE_ZONE_MARGIN_PERCENT: 10.0,
        },
        unique_id="NL",
        version=1,
    )
    freezer, _ = await setup_at(hass, entry, market_time(DAY, 14, 7))
    try:
        assert entry.state is ConfigEntryState.LOADED
        assert entry.version == 1  # no migration was triggered
        assert CONF_OPTIMAL_CHEAP_ENABLED not in entry.options
        assert len(registered(hass)) == BASE_ENTITY_COUNT

        # The pre-existing settings are untouched and still applied.
        assert (
            hass.states.get("sensor.frank_cheap_zone_start_today").attributes[
                "margin_percent"
            ]
            == 20.0
        )
        assert float(
            hass.states.get("sensor.frank_current_return_price").state
        ) == pytest.approx(round((NORMAL_MP - 0.017) * 1.21, 6))
        # And the large daily array is still live, now simply unrecorded.
        assert len(
            hass.states.get("sensor.frank_prices_today").attributes["prices"]
        ) == (96)
    finally:
        freezer.stop()
