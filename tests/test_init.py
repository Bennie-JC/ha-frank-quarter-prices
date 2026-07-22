"""Setup / regression tests for the integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState

from custom_components.frank_quarter_prices.const import CONF_FEED_IN_ADJUSTMENT


async def test_setup_and_unload(hass, setup_integration):
    """The entry loads and unloads cleanly."""
    entry, _ = setup_integration
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_legacy_entry_without_options_loads(hass, mock_client):
    """An existing entry without options loads without migration errors."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain="frank_quarter_prices",
        title="Frank Quarter Prices (NL)",
        data={"country": "NL"},
        # No options key at all — simulates a pre-0.1.3 install.
        unique_id="NL",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert CONF_FEED_IN_ADJUSTMENT not in entry.options
    # Feed-in sensor still works with the default adjustment.
    assert hass.states.get("sensor.frank_current_return_price") is not None
