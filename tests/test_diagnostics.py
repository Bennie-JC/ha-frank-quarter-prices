"""Tests for the diagnostics payload."""

from __future__ import annotations

import pytest
from homeassistant.util import dt as dt_util

from custom_components.frank_quarter_prices.const import (
    CONF_CHEAP_ZONE_MARGIN_PERCENT,
    CONF_EXPENSIVE_ZONE_MARGIN_PERCENT,
    CONF_OPTIMAL_CHEAP_DURATION_MINUTES,
    CONF_OPTIMAL_CHEAP_ENABLED,
    CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES,
    CONF_OPTIMAL_EXPENSIVE_ENABLED,
)
from custom_components.frank_quarter_prices.diagnostics import (
    async_get_config_entry_diagnostics,
)

pytestmark = pytest.mark.usefixtures("setup_integration")


async def test_diagnostics_include_the_derived_zones(hass, setup_integration):
    """The derived zones travel in the coordinator data, ready for a bug report."""
    entry, _ = setup_integration
    result = await async_get_config_entry_diagnostics(hass, entry)

    data = result["coordinator"]["data"]
    for key in ("cheap_zone", "expensive_zone"):
        zone = data[key]
        assert zone is not None, key
        assert set(zone) == {
            "start",
            "end",
            "threshold_eur_kwh",
            "margin_percent",
            "day_reference_price",
            "day_min_price",
            "day_max_price",
            "quarter_count",
            "duration_minutes",
        }
        assert dt_util.as_local(zone["start"]) < dt_util.as_local(zone["end"])


async def test_diagnostics_report_the_effective_settings(hass, setup_integration):
    """The resolved options show what is actually in force, defaults included."""
    entry, _ = setup_integration
    result = await async_get_config_entry_diagnostics(hass, entry)

    resolved = result["resolved_options"]
    assert resolved["cheap_margin_percent"] == 15.0
    assert resolved["expensive_margin_percent"] == 15.0
    assert resolved["return_price_source"] == "market_price"
    assert resolved["return_price_apply_vat"] is False
    assert resolved["return_price_feed_in_adjustment"] == 0.0


async def test_diagnostics_reflect_configured_margins(hass, setup_integration):
    """A configured margin shows up in the resolved options, not just the default."""
    entry, _ = setup_integration
    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_CHEAP_ZONE_MARGIN_PERCENT: 22.0,
            CONF_EXPENSIVE_ZONE_MARGIN_PERCENT: 8.0,
        },
    )
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["resolved_options"]["cheap_margin_percent"] == 22.0
    assert result["resolved_options"]["expensive_margin_percent"] == 8.0
    assert result["coordinator"]["data"]["cheap_zone"]["margin_percent"] == 22.0


async def test_diagnostics_report_the_optimal_period_settings(hass, setup_integration):
    """Enough to explain an unavailable planner entity, and nothing more."""
    entry, _ = setup_integration
    resolved = (await async_get_config_entry_diagnostics(hass, entry))[
        "resolved_options"
    ]
    assert resolved["optimal_cheap_enabled"] is False
    assert resolved["optimal_expensive_enabled"] is False
    assert resolved["optimal_cheap_duration_minutes"] == 120
    assert resolved["optimal_expensive_duration_minutes"] == 120

    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_OPTIMAL_CHEAP_ENABLED: True,
            CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 180,
            CONF_OPTIMAL_EXPENSIVE_ENABLED: False,
            CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES: 60,
        },
    )
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)
    resolved = result["resolved_options"]
    assert resolved["optimal_cheap_enabled"] is True
    assert resolved["optimal_cheap_duration_minutes"] == 180
    assert resolved["optimal_expensive_enabled"] is False
    assert resolved["optimal_expensive_duration_minutes"] == 60

    # The derived window travels in the coordinator data, once.
    data = result["coordinator"]["data"]
    assert data["optimal_cheap_today"] is not None
    assert data["optimal_expensive_today"] is None
    assert set(data["optimal_cheap_today"]) == {
        "mode",
        "start",
        "end",
        "duration_minutes",
        "average_price_eur_kwh",
        "min_price_eur_kwh",
        "max_price_eur_kwh",
        "block_count",
        "resolution_minutes",
    }


async def test_diagnostics_show_an_invalid_duration_as_null(hass, setup_integration):
    """A corrupt duration is reported as ``null``, and does not raise.

    Diagnostics is exactly where someone looks when a planner entity is
    unavailable, so this is the field that has to explain it. The offending raw
    value is not repeated here because ``entry.options`` in the same payload
    already carries it verbatim.
    """
    entry, _ = setup_integration
    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_OPTIMAL_CHEAP_ENABLED: True,
            CONF_OPTIMAL_CHEAP_DURATION_MINUTES: -500,
        },
    )
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)
    resolved = result["resolved_options"]

    assert resolved["optimal_cheap_enabled"] is True
    assert resolved["optimal_cheap_duration_minutes"] is None
    # The raw value is visible next to it, in the options dump.
    assert result["entry"]["options"][CONF_OPTIMAL_CHEAP_DURATION_MINUTES] == -500
    # And no period was derived from it.
    assert result["coordinator"]["data"]["optimal_cheap_today"] is None


async def test_diagnostics_do_not_duplicate_the_daily_array_for_the_planner(
    hass, setup_integration
):
    """The planner adds settings and a window, not a second copy of the day."""
    entry, _ = setup_integration
    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_OPTIMAL_CHEAP_ENABLED: True,
            CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 120,
        },
    )
    await hass.async_block_till_done()

    data = (await async_get_config_entry_diagnostics(hass, entry))["coordinator"][
        "data"
    ]
    for key in ("optimal_cheap_today", "optimal_cheap_tomorrow"):
        assert "prices" not in data[key]
        assert "blocks" not in data[key]


async def test_diagnostics_contain_no_credentials(hass, setup_integration):
    """The Frank market-price API needs no auth, so nothing secret is exposed."""
    entry, _ = setup_integration
    result = await async_get_config_entry_diagnostics(hass, entry)

    rendered = repr(result).lower()
    for secret in ("password", "token", "api_key", "authorization", "bearer"):
        assert secret not in rendered


async def test_diagnostics_work_while_the_entry_is_not_loaded(hass, setup_integration):
    """Downloading diagnostics for an unloaded entry must not raise.

    ``runtime_data`` is deleted on unload and never set when setup fails, while
    the diagnostics endpoint serves any entry that exists. An unguarded read
    would return HTTP 500 precisely when a user is collecting diagnostics about
    a failing setup.
    """
    entry, _ = setup_integration
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["coordinator"]["loaded"] is False
    assert result["coordinator"]["data"] is None
    assert result["coordinator"]["last_update_success"] is None
    # The settings still come through -- they need no coordinator.
    assert result["resolved_options"]["cheap_margin_percent"] == 15.0
    assert result["entry"]["title"]
    assert "not_loaded" in result["entry"]["state"].lower()


async def test_diagnostics_report_the_entry_state_while_loaded(hass, setup_integration):
    """A loaded entry reports its state and the live coordinator data."""
    entry, _ = setup_integration
    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["coordinator"]["loaded"] is True
    assert result["coordinator"]["last_update_success"] is True
    assert "loaded" in result["entry"]["state"].lower()
