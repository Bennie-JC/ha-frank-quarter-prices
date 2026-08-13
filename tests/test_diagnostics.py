"""Tests for the diagnostics payload."""

from __future__ import annotations

import pytest
from homeassistant.util import dt as dt_util

from custom_components.frank_quarter_prices.const import (
    CONF_CHEAP_ZONE_MARGIN_PERCENT,
    CONF_EXPENSIVE_ZONE_MARGIN_PERCENT,
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
