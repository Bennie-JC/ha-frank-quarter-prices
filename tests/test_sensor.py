"""Tests for the sensor platform, including Energy Dashboard metadata."""

from __future__ import annotations

import pytest
from homeassistant.components.sensor import ATTR_STATE_CLASS, SensorDeviceClass
from homeassistant.const import ATTR_DEVICE_CLASS, ATTR_UNIT_OF_MEASUREMENT
from homeassistant.helpers import entity_registry as er

from custom_components.frank_quarter_prices.const import CONF_APPLY_FEED_IN_VAT

CURRENT_PRICE = "sensor.frank_current_price"
RETURN_PRICE = "sensor.frank_current_return_price"
CHEAPEST_TODAY = "sensor.frank_cheapest_today"
MOST_EXPENSIVE_TODAY = "sensor.frank_most_expensive_today"
PRICES_TODAY = "sensor.frank_prices_today"
CHEAP_ZONE_START = "sensor.frank_cheap_zone_start_today"
EXPENSIVE_ZONE_START = "sensor.frank_expensive_zone_start_today"

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
    # State stays numeric (never a formatted "€ 0.25" string). It now holds the
    # marktprijs+ dynamic basis (market 0.08 + its VAT 0.0168 + sourcing markup
    # 0.018), not the all-in total (which stays on full_block.total_price_eur_kwh
    # and additionally carries the 0.11085 energy tax).
    assert float(state.state) == pytest.approx(0.1148)


async def test_current_price_identity_unchanged(hass):
    """The existing entity id and unique id are preserved."""
    registry = er.async_get(hass)
    entry = registry.async_get(CURRENT_PRICE)
    assert entry is not None
    assert entry.unique_id.endswith("_current_price")


async def test_current_price_isolated_from_other_entities(hass):
    """Changing the current-price derivation must move exactly one entity.

    ``sensor.frank_current_price`` now holds the marktprijs+ dynamic basis, while
    every other price entity stays on the all-in ``total_price_eur_kwh`` basis.
    """
    # The current price moved to the dynamic basis:
    # market 0.08 + its VAT 0.0168 + markup 0.018.
    current = hass.states.get(CURRENT_PRICE)
    assert current is not None
    assert float(current.state) == pytest.approx(0.1148)
    # The all-in price is preserved on the same entity's block attribute, and it
    # is exactly the dynamic basis plus the energy tax.
    full_block = current.attributes["full_block"]
    assert full_block["total_price_eur_kwh"] == pytest.approx(0.22565)
    assert full_block["market_price"] == pytest.approx(0.08)
    assert float(current.state) == pytest.approx(
        full_block["total_price_eur_kwh"] - full_block["energy_tax_price"]
    )

    # The all-in daily arrays: min/max are still computed from total_price_eur_kwh.
    prices_today = hass.states.get(PRICES_TODAY)
    totals = [
        block["total_price_eur_kwh"]
        for block in prices_today.attributes["prices"]
        if block.get("total_price_eur_kwh") is not None
    ]
    assert prices_today.attributes["min_price"] == pytest.approx(min(totals))
    assert prices_today.attributes["max_price"] == pytest.approx(max(totals))

    # The cheapest / most expensive block sensors stay on the all-in basis.
    cheapest = hass.states.get(CHEAPEST_TODAY)
    expensive = hass.states.get(MOST_EXPENSIVE_TODAY)
    assert float(cheapest.state) == pytest.approx(min(totals))
    assert float(expensive.state) == pytest.approx(max(totals))

    # The feed-in sensor is unchanged: it still equals the raw market price.
    return_price = hass.states.get(RETURN_PRICE)
    assert float(return_price.state) == pytest.approx(full_block["market_price"])

    # The four price-zone boundary sensors still report the all-in day min/max and
    # thresholds (derived from total_price_eur_kwh).
    cheap_zone = hass.states.get(CHEAP_ZONE_START).attributes
    exp_zone = hass.states.get(EXPENSIVE_ZONE_START).attributes
    assert cheap_zone["day_min_price"] == pytest.approx(min(totals))
    assert cheap_zone["day_max_price"] == pytest.approx(max(totals))
    assert exp_zone["day_min_price"] == pytest.approx(min(totals))
    assert exp_zone["day_max_price"] == pytest.approx(max(totals))


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
