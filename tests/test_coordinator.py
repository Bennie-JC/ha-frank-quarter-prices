"""Regression tests for coordinator refresh scheduling (GitHub issue #2).

Issue #2: the coordinator refreshed on a free-running ``timedelta(minutes=15)``
interval anchored to whenever the config entry happened to be set up, instead
of to the wall-clock quarter-hour boundaries. Whatever offset existed at
startup persisted, so ``current_price`` (and the today/tomorrow rollover)
could lag up to ~14 minutes behind the real quarter change. The fix drives
refreshes from ``async_track_time_change`` on :00/:15/:30/:45 instead.

Since issue #3 a refresh no longer implies an API request — most ticks derive
the active block from the daily cache — so these tests count *refreshes* via
``refresh_spy`` rather than client calls. The request behaviour itself is
covered in ``test_coordinator_cache.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
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
from custom_components.frank_quarter_prices.coordinator import (
    FrankQuarterPricesCoordinator,
)

from .conftest import build_block

CURRENT_PRICE = "sensor.frank_current_price"
PRICES_TODAY = "sensor.frank_prices_today"
PRICES_TOMORROW = "sensor.frank_prices_tomorrow"

_CLIENT_METHOD = (
    "custom_components.frank_quarter_prices.frank_client."
    "FrankClient.async_get_prices_for_date"
)

_TZ = "Europe/Amsterdam"


def _stepped_day(day: Any, base_price: float = 0.10) -> dict[str, Any]:
    """Build a full local day where each quarter has a distinct, rising price.

    Lets tests assert exactly which block is "current", instead of the flat
    per-day price used by the shared ``build_day`` fixture helper.
    """
    midnight = dt_util.start_of_local_day(day)
    blocks = [
        build_block(
            midnight + timedelta(minutes=15 * i), round(base_price + i * 0.001, 6)
        )
        for i in range(96)
    ]
    return {"prices": blocks}


def _expected_total(index: int, base_price: float = 0.10) -> float:
    """Return the ``total_price_eur_kwh`` for the quarter at ``index`` in ``_stepped_day``."""
    price = round(base_price + index * 0.001, 6)
    return build_block(datetime(2000, 1, 1, tzinfo=dt_util.UTC), price)[
        "total_price_eur_kwh"
    ]


def _expected_dynamic(index: int, base_price: float = 0.10) -> float:
    """Return the marktprijs+ value for the quarter at ``index`` in ``_stepped_day``.

    ``market_price`` excludes VAT and ``sourcing_markup_price`` includes it, so
    the market price's own VAT component belongs in the sum.
    """
    price = round(base_price + index * 0.001, 6)
    block = build_block(datetime(2000, 1, 1, tzinfo=dt_util.UTC), price)
    return round(
        block["market_price"]
        + block["market_price_tax"]
        + block["sourcing_markup_price"],
        6,
    )


@pytest.fixture
def stepped_client():
    """Client mock returning a distinct price per quarter for any requested day."""
    mock = AsyncMock(side_effect=lambda target_date: _stepped_day(target_date))
    with patch(_CLIENT_METHOD, mock):
        yield mock


@pytest.fixture
def refresh_spy():
    """Record the local time of every coordinator refresh.

    Scheduling is what these tests are about, and a refresh is no longer
    observable through the client mock: a tick that finds both days cached
    performs zero requests. Counting the coordinator's own update instead
    keeps the issue #2 assertions exact, and additionally pins down *when*
    each refresh landed.
    """
    original = FrankQuarterPricesCoordinator._async_update_data
    refreshes: list[datetime] = []

    async def counting(self):
        refreshes.append(dt_util.now())
        return await original(self)

    with patch.object(FrankQuarterPricesCoordinator, "_async_update_data", counting):
        yield refreshes


@pytest.fixture
def mock_config_entry():
    """Return a mock config entry for the NL integration."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Frank Quarter Prices (NL)",
        data={"country": "NL"},
        options={},
        unique_id="NL",
    )


async def _setup_at(hass, entry, start: datetime) -> None:
    """Set up the config entry with the clock frozen at ``start``."""
    await hass.config.async_set_time_zone(_TZ)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_refresh_is_aligned_to_wallclock_not_setup_time(
    hass, mock_config_entry, stepped_client, refresh_spy
):
    """Issue #2 reproduction: setup at a non-boundary time must not offset polling.

    Setting up at 10:07 (a time chosen to be nowhere near a quarter boundary)
    must not cause the next refresh at 10:22 (setup + 15 min). It must land on
    the next real boundary, 10:15.
    """
    tz = dt_util.get_time_zone(_TZ)
    start = datetime(2026, 8, 6, 10, 7, 0, tzinfo=tz)
    freezer = freeze_time(start)
    frozen_time = freezer.start()
    try:
        await _setup_at(hass, mock_config_entry, start)
        assert refresh_spy == [start]  # the initial refresh

        # Old behaviour would refresh at setup+15min = 10:22. Confirm no
        # refresh has happened yet just before the *real* boundary at 10:15.
        frozen_time.move_to(start + timedelta(minutes=7, seconds=59))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        assert refresh_spy == [start]

        # The real quarter boundary (plus the small offset) must refresh.
        boundary = start.replace(minute=15, second=3, microsecond=0)
        frozen_time.move_to(boundary)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        assert refresh_spy == [start, boundary]
    finally:
        freezer.stop()


async def test_current_price_updates_within_seconds_of_boundary(
    hass, mock_config_entry, stepped_client
):
    """current_price must reflect the new block right after a boundary, not ~14min later."""
    tz = dt_util.get_time_zone(_TZ)
    start = datetime(2026, 8, 6, 10, 7, 0, tzinfo=tz)
    freezer = freeze_time(start)
    frozen_time = freezer.start()
    try:
        await _setup_at(hass, mock_config_entry, start)
        state = hass.states.get(CURRENT_PRICE)
        # 10:07 falls in the 10:00 block -> index 40.
        assert float(state.state) == pytest.approx(_expected_dynamic(40))

        frozen_time.move_to(start.replace(minute=15, second=3, microsecond=0))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        state = hass.states.get(CURRENT_PRICE)
        # 10:15 block -> index 41.
        assert float(state.state) == pytest.approx(_expected_dynamic(41))
    finally:
        freezer.stop()


async def test_midnight_rollover_happens_promptly(
    hass, mock_config_entry, stepped_client
):
    """Today/tomorrow must swap right after midnight, not up to ~14min later.

    This is the day-boundary scenario from the issue report: at 23:59 the
    stale "today" list must not survive into the new day once the coordinator
    has refreshed at 00:00.
    """
    tz = dt_util.get_time_zone(_TZ)
    start = datetime(2026, 8, 6, 23, 59, 0, tzinfo=tz)
    freezer = freeze_time(start)
    frozen_time = freezer.start()
    try:
        await _setup_at(hass, mock_config_entry, start)

        today_state = hass.states.get(PRICES_TODAY)
        old_today_first = today_state.attributes["prices"][0]["from"]
        assert old_today_first.startswith("2026-08-06")

        frozen_time.move_to(
            start.replace(day=7, hour=0, minute=0, second=3, microsecond=0)
        )
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        today_state = hass.states.get(PRICES_TODAY)
        new_today_first = today_state.attributes["prices"][0]["from"]
        assert new_today_first.startswith("2026-08-07")
        # A full 96-quarter day is still exposed after the rollover.
        assert len(today_state.attributes["prices"]) == 96

        current_price_state = hass.states.get(CURRENT_PRICE)
        # 00:00 block of the new day -> index 0.
        assert float(current_price_state.state) == pytest.approx(_expected_dynamic(0))
    finally:
        freezer.stop()


async def test_tomorrow_unavailable_then_available_after_quarter_tick(
    hass, mock_config_entry
):
    """Tomorrow prices missing early must not break today; a later refresh must publish them.

    Simulates the real-world pattern: tomorrow is only published by Frank in
    the afternoon. Before publication the request fails; today must stay
    intact. Once publication happens, the very next quarter-tick refresh must
    surface it automatically.
    """
    from custom_components.frank_quarter_prices.frank_client import FrankClientError

    tz = dt_util.get_time_zone(_TZ)
    start = datetime(2026, 8, 6, 12, 59, 0, tzinfo=tz)

    call_state = {"tomorrow_published": False}

    async def fake_fetch(target_date):
        today = dt_util.now().date()
        if target_date != today and not call_state["tomorrow_published"]:
            raise FrankClientError("tomorrow not published yet")
        return _stepped_day(target_date)

    mock = AsyncMock(side_effect=fake_fetch)

    freezer = freeze_time(start)
    frozen_time = freezer.start()
    try:
        with patch(_CLIENT_METHOD, mock):
            await _setup_at(hass, mock_config_entry, start)

            today_state = hass.states.get(PRICES_TODAY)
            assert len(today_state.attributes["prices"]) == 96
            # Unavailable entities don't expose extra_state_attributes; the
            # unavailable state itself is what EMS/HA consumers must see.
            tomorrow_state = hass.states.get(PRICES_TOMORROW)
            assert tomorrow_state.state == "unavailable"

            # Frank publishes tomorrow's prices; simulate the afternoon at the
            # next quarter boundary (13:00), one minute after setup (12:59).
            call_state["tomorrow_published"] = True
            frozen_time.move_to(start + timedelta(minutes=1, seconds=3))
            async_fire_time_changed(hass)
            await hass.async_block_till_done()

            today_state = hass.states.get(PRICES_TODAY)
            assert len(today_state.attributes["prices"]) == 96
            tomorrow_state = hass.states.get(PRICES_TOMORROW)
            assert tomorrow_state.attributes["available"] is True
            assert int(tomorrow_state.state) == 96
    finally:
        freezer.stop()


async def test_no_refresh_scheduled_off_boundary_after_reload(
    hass, mock_config_entry, stepped_client, refresh_spy
):
    """Reloading the entry must re-anchor to the wall clock, not accumulate listeners.

    A stale duplicate listener (e.g. left over from before a reload) would
    cause more than one extra refresh per boundary.
    """
    tz = dt_util.get_time_zone(_TZ)
    start = datetime(2026, 8, 6, 9, 0, 0, tzinfo=tz)
    freezer = freeze_time(start)
    frozen_time = freezer.start()
    try:
        await _setup_at(hass, mock_config_entry, start)
        assert len(refresh_spy) == 1

        await hass.config_entries.async_reload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        # First refresh, then the reload's first refresh.
        assert len(refresh_spy) == 2

        frozen_time.move_to(start.replace(minute=15, second=3, microsecond=0))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        # Exactly one more refresh, not a doubled-up one from a leaked listener.
        assert len(refresh_spy) == 3
    finally:
        freezer.stop()


async def test_quarter_tick_survives_dst_spring_forward(
    hass, mock_config_entry, stepped_client, refresh_spy
):
    """The wall-clock scheduler must keep firing correctly across a DST change.

    2026-03-29 is the Europe/Amsterdam spring-forward date (02:00 CET jumps to
    03:00 CEST). The fix relies entirely on Home Assistant's timezone-aware
    ``async_track_time_change`` (no manual hour/minute arithmetic), so this
    guards against a regression reintroducing naive offset math.
    """
    tz = dt_util.get_time_zone(_TZ)
    start = datetime(2026, 3, 29, 1, 45, 0, tzinfo=tz)
    freezer = freeze_time(start)
    frozen_time = freezer.start()
    try:
        await _setup_at(hass, mock_config_entry, start)
        assert len(refresh_spy) == 1

        # Local wall clock jumps from 01:59:59 CET straight to 03:00:00 CEST.
        after_jump = datetime(2026, 3, 29, 3, 0, 3, tzinfo=tz)
        frozen_time.move_to(after_jump)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        assert refresh_spy[-1] == after_jump
        state = hass.states.get(CURRENT_PRICE)
        assert state is not None
        assert state.state not in ("unknown", "unavailable")
    finally:
        freezer.stop()
