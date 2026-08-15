"""Recorder metadata for the two large daily price arrays.

Home Assistant's Recorder refuses to store a state whose attributes serialize to
more than 16384 bytes, and logs::

    State attributes for sensor.frank_prices_today exceed maximum size of 16384
    bytes. This can cause database performance issues; Attributes will not be
    stored

A day of quarter-hour blocks is roughly 25 kB, so both day-list sensors tripped
this on every single state change — and because the Recorder then stores *no*
attributes for that state at all, the small useful ones next to ``prices`` were
being discarded along with it.

The fix is ``Entity._unrecorded_attributes``, Home Assistant's own mechanism for
exactly this. It changes nothing about the live state: ``prices`` is still an
ordinary state attribute that ``state_attr()``, dashboards, templates and EMS
consumers read unchanged. It only tells the Recorder to drop that one key
*before* the size check.

Everything below is asserted against the real published states and the real
metadata Home Assistant hands the Recorder — never against a mock — because the
whole point is that the live contract did not move.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from freezegun import freeze_time
from homeassistant.components.recorder.db_schema import (
    MAX_STATE_ATTRS_BYTES,
    StateAttributes,
)
from homeassistant.const import MATCH_ALL
from homeassistant.core import Event, EventStateChangedData
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.frank_quarter_prices.const import DOMAIN
from custom_components.frank_quarter_prices.sensor import (
    FrankPricesTodaySensor,
    FrankPricesTomorrowSensor,
)

from .conftest import TEST_TIMEZONE, build_local_day_blocks

TODAY = "sensor.frank_prices_today"
TOMORROW = "sensor.frank_prices_tomorrow"
DAY_SENSORS = (TODAY, TOMORROW)

_CLIENT_METHOD = (
    "custom_components.frank_quarter_prices.frank_client."
    "FrankClient.async_get_prices_for_date"
)

DAY = date(2026, 8, 6)  # 96 quarters
SPRING_FORWARD = date(2026, 3, 29)  # 92 quarters
FALL_BACK = date(2026, 10, 25)  # 100 quarters

# Every attribute the two day-list sensors publish. Only ``prices`` may be
# excluded from the Recorder; the rest is small and worth keeping in history.
_DAY_LIST_ATTRS = {
    "prices",
    "resolution_minutes",
    "cheapest_block",
    "most_expensive_block",
    "average_price",
    "min_price",
    "max_price",
}


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


class FakeApi:
    """Client stand-in serving a complete market day per date."""

    def __init__(self) -> None:
        """Initialize with an empty call log."""
        self.calls: list[date] = []

    async def fetch(self, target_date: date) -> dict[str, Any]:
        """Serve a complete local day."""
        self.calls.append(target_date)
        return {"prices": build_local_day_blocks(target_date, None)}


@pytest.fixture
def api():
    """Patch the client with the counting fake."""
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


async def setup_at(hass, entry, start: datetime):
    """Set up the config entry with the clock frozen at ``start``."""
    await hass.config.async_set_time_zone(TEST_TIMEZONE)
    freezer = freeze_time(start)
    frozen = freezer.start()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return freezer, frozen


def recorded_attributes(hass, entity_id: str) -> dict[str, Any]:
    """Return exactly the attributes the Recorder would persist for a state.

    Runs Home Assistant's own ``StateAttributes.shared_attrs_bytes_from_event``
    — the very function that emits the oversize warning — over a synthetic
    state-changed event carrying the live state. That makes this a test of the
    Recorder's real behaviour rather than of an assumption about it.
    """
    return json.loads(recorded_bytes(hass, entity_id))


def recorded_bytes(hass, entity_id: str) -> bytes:
    """Return the serialized attributes the Recorder would store."""
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    event: Event[EventStateChangedData] = Event(
        "state_changed",
        {"entity_id": entity_id, "old_state": None, "new_state": state},
    )
    return StateAttributes.shared_attrs_bytes_from_event(event, None)


# --- The live attribute is untouched ----------------------------------------


@pytest.mark.parametrize("entity_id", DAY_SENSORS)
async def test_prices_is_still_a_live_state_attribute(hass, entry, api, entity_id):
    """``state_attr(entity, 'prices')`` still returns the complete array."""
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        prices = hass.states.get(entity_id).attributes["prices"]
        assert isinstance(prices, list)
        assert len(prices) == 96
        assert int(hass.states.get(entity_id).state) == len(prices)
    finally:
        freezer.stop()


@pytest.mark.parametrize("entity_id", DAY_SENSORS)
async def test_a_template_still_reads_the_whole_array(hass, entry, api, entity_id):
    """The dashboard/EMS path — a real Jinja template — is unaffected."""
    from homeassistant.helpers.template import Template

    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        rendered = Template(
            f"{{{{ state_attr('{entity_id}', 'prices') | count }}}}", hass
        ).async_render()
        assert int(rendered) == 96

        first = Template(
            f"{{{{ state_attr('{entity_id}', 'prices')[0].total_price_eur_kwh }}}}",
            hass,
        ).async_render()
        assert isinstance(float(first), float)
    finally:
        freezer.stop()


@pytest.mark.parametrize("entity_id", DAY_SENSORS)
async def test_the_block_schema_is_unchanged(hass, entry, api, entity_id):
    """Excluding the attribute from history did not reshape a single block."""
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        for block in hass.states.get(entity_id).attributes["prices"]:
            assert list(block) == [
                "from",
                "till",
                "duration_minutes",
                "market_price",
                "market_price_tax",
                "sourcing_markup_price",
                "energy_tax_price",
                "total_price_eur_kwh",
                "per_unit",
            ]
            assert isinstance(block["from"], str)
            assert datetime.fromisoformat(block["from"]).tzinfo is not None
    finally:
        freezer.stop()


# --- The Recorder metadata ---------------------------------------------------


@pytest.mark.parametrize(
    "sensor_class", [FrankPricesTodaySensor, FrankPricesTomorrowSensor]
)
def test_only_prices_is_declared_unrecorded(sensor_class):
    """The declared mechanism is ``_unrecorded_attributes``, and only for prices.

    Not ``MATCH_ALL``: the small summary attributes next to the array are
    genuinely useful in history and stay recorded.
    """
    assert sensor_class._unrecorded_attributes == frozenset({"prices"})
    assert MATCH_ALL not in sensor_class._unrecorded_attributes


@pytest.mark.parametrize("entity_id", DAY_SENSORS)
async def test_the_published_state_carries_the_exclusion(hass, entry, api, entity_id):
    """Home Assistant really hands the Recorder the exclusion, at runtime.

    ``State.state_info`` is what the Recorder reads. Asserting the class
    attribute alone would not prove the entity actually publishes it.
    """
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        state_info = hass.states.get(entity_id).state_info
        assert state_info is not None
        assert "prices" in state_info["unrecorded_attributes"]
    finally:
        freezer.stop()


@pytest.mark.parametrize("entity_id", DAY_SENSORS)
async def test_the_recorder_would_not_store_prices(hass, entry, api, entity_id):
    """Run the Recorder's own serializer: the array is gone from what it stores."""
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        assert "prices" not in recorded_attributes(hass, entity_id)
    finally:
        freezer.stop()


@pytest.mark.parametrize("entity_id", DAY_SENSORS)
async def test_the_other_attributes_are_still_stored(hass, entry, api, entity_id):
    """Nothing else was excluded by accident.

    This is the regression that a lazy fix would introduce: excluding
    ``MATCH_ALL``, or excluding the wrong key, silently empties the history of
    the summary values too.
    """
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        stored = recorded_attributes(hass, entity_id)
        live = set(hass.states.get(entity_id).attributes)

        for key in _DAY_LIST_ATTRS - {"prices"}:
            assert key in stored, key
        # Everything the entity publishes except ``prices`` survives; the
        # Recorder additionally drops its own always-excluded keys.
        assert (live - set(stored)) == {"prices"}
    finally:
        freezer.stop()


@pytest.mark.parametrize("entity_id", DAY_SENSORS)
async def test_what_the_recorder_stores_is_far_under_the_limit(
    hass, entry, api, entity_id
):
    """The size that triggered the warning is now a few hundred bytes.

    Also asserted the other way round: without the exclusion the very same
    state really would exceed the limit, so the fix is load-bearing and not a
    change that happened to be harmless.
    """
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        stored = recorded_bytes(hass, entity_id)
        assert len(stored) < MAX_STATE_ATTRS_BYTES
        # Comfortably under, not marginally: no risk of creeping back over.
        assert len(stored) < MAX_STATE_ATTRS_BYTES // 4

        unfiltered = len(
            json.dumps(dict(hass.states.get(entity_id).attributes), default=str)
        )
        assert unfiltered > MAX_STATE_ATTRS_BYTES, (
            "the array no longer exceeds the limit, so this test proves nothing"
        )
    finally:
        freezer.stop()


@pytest.mark.parametrize("entity_id", DAY_SENSORS)
async def test_no_oversize_warning_is_logged(hass, entry, api, entity_id, caplog):
    """The exact warning this release set out to remove does not appear."""
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        caplog.clear()
        recorded_bytes(hass, entity_id)
        assert "exceed maximum size" not in caplog.text
    finally:
        freezer.stop()


@pytest.mark.parametrize(
    ("day", "expected_blocks"),
    [(SPRING_FORWARD, 92), (DAY, 96), (FALL_BACK, 100)],
)
async def test_dst_day_arrays_stay_live_and_unrecorded(
    hass, entry, api, day, expected_blocks
):
    """92-, 96- and 100-block days all keep the live array and the exclusion."""
    freezer, _ = await setup_at(hass, entry, at(day, 14, 7))
    try:
        for entity_id in DAY_SENSORS:
            state = hass.states.get(entity_id)
            assert len(state.attributes["prices"]) in (
                expected_blocks,
                # Tomorrow may be a different length across a DST boundary.
                92,
                96,
                100,
            )
            assert "prices" in state.state_info["unrecorded_attributes"]
            assert "prices" not in recorded_attributes(hass, entity_id)
            assert len(recorded_bytes(hass, entity_id)) < MAX_STATE_ATTRS_BYTES
        assert len(hass.states.get(TODAY).attributes["prices"]) == expected_blocks
    finally:
        freezer.stop()


# --- No side effects ---------------------------------------------------------


async def test_the_recorder_fix_costs_no_api_request(hass, entry, api):
    """Excluding an attribute from history is metadata, not behaviour."""
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        assert len(api.calls) == 2  # today + tomorrow, exactly as in v0.1.6

        calls_before = len(api.calls)
        for _ in range(20):
            for entity_id in DAY_SENSORS:
                dict(hass.states.get(entity_id).attributes)
        assert len(api.calls) == calls_before
    finally:
        freezer.stop()


async def test_availability_is_untouched(hass, entry, api):
    """Both sensors are available exactly when they were before.

    Tomorrow in particular: still unavailable before publication, still
    available once the day is cached — unchanged by the Recorder metadata.
    """
    freezer, _ = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        assert hass.states.get(TODAY).state == "96"
        assert hass.states.get(TOMORROW).state == "96"
        assert hass.states.get(TOMORROW).attributes["available"] is True
    finally:
        freezer.stop()


async def test_tomorrow_before_publication_is_still_unavailable(hass, entry):
    """The morning case, where tomorrow does not exist yet."""

    async def morning_only(target_date: date) -> dict[str, Any]:
        if target_date != DAY:
            return {"prices": []}
        return {"prices": build_local_day_blocks(target_date, None)}

    with patch(_CLIENT_METHOD, AsyncMock(side_effect=morning_only)):
        freezer, _ = await setup_at(hass, entry, at(DAY, 8, 7))
        try:
            assert hass.states.get(TOMORROW).state == "unavailable"
            assert hass.states.get(TODAY).state == "96"
            assert (
                "prices" in hass.states.get(TODAY).state_info["unrecorded_attributes"]
            )
        finally:
            freezer.stop()


async def test_the_array_survives_a_quarter_tick(hass, entry, api):
    """The exclusion is re-published on every state write, not just the first."""
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    freezer, frozen = await setup_at(hass, entry, at(DAY, 14, 7))
    try:
        for offset in range(1, 5):
            frozen.move_to(
                at(DAY, 14, 15 * offset % 60, 3) + timedelta(hours=offset // 4)
            )
            async_fire_time_changed(hass)
            await hass.async_block_till_done()

            for entity_id in DAY_SENSORS:
                state = hass.states.get(entity_id)
                assert len(state.attributes["prices"]) == 96
                assert "prices" in state.state_info["unrecorded_attributes"]
    finally:
        freezer.stop()
