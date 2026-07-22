"""Tests for the sensor platform, including Energy Dashboard metadata."""

from __future__ import annotations

import pytest

from homeassistant.components.sensor import ATTR_STATE_CLASS, SensorDeviceClass
from homeassistant.const import ATTR_DEVICE_CLASS, ATTR_UNIT_OF_MEASUREMENT
from homeassistant.helpers import entity_registry as er

from custom_components.frank_quarter_prices.const import CONF_APPLY_FEED_IN_VAT

CURRENT_PRICE = "sensor.frank_current_price"
RETURN_PRICE = "sensor.frank_current_return_price"

# All entities the integration is expected to create (regression guard).
EXPECTED_ENTITIES = {
    "sensor.frank_current_price",
    "sensor.frank_current_return_price",
    "sensor.frank_prices_today",
    "sensor.frank_prices_tomorrow",
    "sensor.frank_cheapest_today",
    "sensor.frank_cheapest_time_today",
    "sensor.frank_most_expensive_today",
    "sensor.frank_most_expensive_time_today",
    "sensor.frank_cheapest_tomorrow",
    "sensor.frank_cheapest_time_tomorrow",
    "sensor.frank_most_expensive_tomorrow",
    "sensor.frank_most_expensive_time_tomorrow",
    "binary_sensor.frank_tomorrow_prices_available",
}

pytestmark = pytest.mark.usefixtures("setup_integration")


async def test_current_price_energy_dashboard_metadata(hass):
    """Existing current-price sensor has the Energy Dashboard metadata."""
    state = hass.states.get(CURRENT_PRICE)
    assert state is not None
    assert state.attributes[ATTR_DEVICE_CLASS] == SensorDeviceClass.MONETARY
    assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == "EUR/kWh"
    # No state_class: an instantaneous price is not a cumulative total.
    assert state.attributes.get(ATTR_STATE_CLASS) is None
    # State stays numeric (never a formatted "€ 0.25" string).
    assert float(state.state) == pytest.approx(0.22565)


async def test_current_price_identity_unchanged(hass):
    """The existing entity id and unique id are preserved."""
    registry = er.async_get(hass)
    entry = registry.async_get(CURRENT_PRICE)
    assert entry is not None
    assert entry.unique_id.endswith("_current_price")


async def test_return_price_created_with_metadata(hass):
    """The new feed-in sensor exists with the correct metadata and id."""
    state = hass.states.get(RETURN_PRICE)
    assert state is not None
    assert state.attributes[ATTR_DEVICE_CLASS] == SensorDeviceClass.MONETARY
    assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == "EUR/kWh"
    assert state.attributes.get(ATTR_STATE_CLASS) is None
    assert state.attributes["friendly_name"] == "Frank Current feed-in price"


async def test_return_price_unique_id(hass):
    """The new feed-in sensor has a stable unique id."""
    registry = er.async_get(hass)
    entry = registry.async_get(RETURN_PRICE)
    assert entry is not None
    assert entry.unique_id.endswith("_current_return_price")


async def test_return_price_value_default_adjustment(hass):
    """With the default adjustment (0.0) the value equals the market price."""
    state = hass.states.get(RETURN_PRICE)
    # build_day uses market_price = 0.08.
    assert float(state.state) == pytest.approx(0.08)


async def test_return_price_attributes(hass):
    """The feed-in sensor exposes stable, numeric attributes."""
    state = hass.states.get(RETURN_PRICE)
    assert state.attributes["market_price_source"] == "market_price"
    assert state.attributes["market_price"] == pytest.approx(0.08)
    assert state.attributes["feed_in_adjustment"] == 0.0
    assert state.attributes["apply_vat"] is False
    assert state.attributes["vat_rate"] == pytest.approx(0.21)
    assert state.attributes["calculation_method"] == "market_price_plus_adjustment"


async def test_return_price_vat_enabled(hass, setup_integration):
    """Enabling VAT multiplies the feed-in price by 1.21 and updates attributes."""
    entry, _ = setup_integration
    hass.config_entries.async_update_entry(
        entry, options={CONF_APPLY_FEED_IN_VAT: True}
    )
    await hass.async_block_till_done()

    state = hass.states.get(RETURN_PRICE)
    # market_price (0.08) + adjustment (0.0), including 21% VAT.
    assert float(state.state) == pytest.approx(round(0.08 * 1.21, 6))
    assert state.attributes["apply_vat"] is True
    assert state.attributes["vat_rate"] == pytest.approx(0.21)
    assert (
        state.attributes["calculation_method"]
        == "market_price_plus_adjustment_including_vat"
    )


async def test_return_price_no_extra_api_request(hass, setup_integration):
    """Setting up all entities issues exactly two client requests (today+tomorrow)."""
    _, mock_client = setup_integration
    assert mock_client.call_count == 2
    # Reading the feed-in sensor state must not trigger another request.
    hass.states.get(RETURN_PRICE)
    assert mock_client.call_count == 2


async def test_all_entities_created(hass):
    """All existing entities plus the new one are created (regression)."""
    for entity_id in EXPECTED_ENTITIES:
        assert hass.states.get(entity_id) is not None, entity_id


async def test_no_invalid_state_class_warning(hass, setup_integration, caplog):
    """Reloading emits no 'impossible state class' warning for the price sensors.

    The reload re-creates the entities during the call phase (while ``caplog`` is
    capturing), so a bad ``state_class`` on a monetary sensor would surface here.
    """
    entry, _ = setup_integration
    caplog.clear()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert "impossible considering device class" not in caplog.text
