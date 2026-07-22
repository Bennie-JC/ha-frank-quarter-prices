"""Tests for the config flow and the feed-in-adjustment options flow."""

from __future__ import annotations

import pytest

from homeassistant.data_entry_flow import FlowResultType, InvalidData

from custom_components.frank_quarter_prices.const import (
    CONF_APPLY_FEED_IN_VAT,
    CONF_FEED_IN_ADJUSTMENT,
    DOMAIN,
)

RETURN_PRICE = "sensor.frank_current_return_price"


async def _open_options(hass, entry):
    """Open the options flow and return the initial form result."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    return result


async def test_config_flow_creates_entry(hass):
    """The initial user flow stays simple and creates an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"country": "NL"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    # Feed-in adjustment is NOT required during initial setup.
    assert CONF_FEED_IN_ADJUSTMENT not in result["data"]


async def test_options_flow_positive(hass, setup_integration):
    """A positive adjustment is stored and the sensor updates on reload."""
    entry, _ = setup_integration
    result = await _open_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_FEED_IN_ADJUSTMENT: 0.02}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_FEED_IN_ADJUSTMENT] == 0.02
    await hass.async_block_till_done()
    # market_price (0.08) + adjustment (0.02).
    assert float(hass.states.get(RETURN_PRICE).state) == pytest.approx(0.10)


async def test_options_flow_negative(hass, setup_integration):
    """A negative adjustment is accepted and applied."""
    entry, _ = setup_integration
    result = await _open_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_FEED_IN_ADJUSTMENT: -0.017}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_FEED_IN_ADJUSTMENT] == -0.017
    await hass.async_block_till_done()
    assert float(hass.states.get(RETURN_PRICE).state) == pytest.approx(0.063)


async def test_options_flow_zero(hass, setup_integration):
    """Zero is accepted."""
    entry, _ = setup_integration
    result = await _open_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_FEED_IN_ADJUSTMENT: 0.0}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_FEED_IN_ADJUSTMENT] == 0.0


async def test_options_flow_out_of_range_rejected(hass, setup_integration):
    """Values outside the configured limits are rejected by the selector."""
    entry, _ = setup_integration
    result = await _open_options(hass, entry)
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_FEED_IN_ADJUSTMENT: 5.0}
        )
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_FEED_IN_ADJUSTMENT: -5.0}
        )


async def test_options_default_when_absent(hass, setup_integration):
    """An entry without the option uses the default 0.0 (sensor == market price)."""
    entry, _ = setup_integration
    assert CONF_FEED_IN_ADJUSTMENT not in entry.options
    assert float(hass.states.get(RETURN_PRICE).state) == pytest.approx(0.08)


async def test_options_flow_shows_vat_checkbox(hass, setup_integration):
    """The VAT checkbox appears directly below the feed-in adjustment field."""
    entry, _ = setup_integration
    result = await _open_options(hass, entry)
    ordered_keys = [str(marker.schema) for marker in result["data_schema"].schema]
    assert ordered_keys == [CONF_FEED_IN_ADJUSTMENT, CONF_APPLY_FEED_IN_VAT]


async def test_options_flow_vat_defaults_disabled(hass, setup_integration):
    """Omitting the VAT key resolves to disabled (default False)."""
    entry, _ = setup_integration
    result = await _open_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_FEED_IN_ADJUSTMENT: 0.0}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options.get(CONF_APPLY_FEED_IN_VAT, False) is False
    await hass.async_block_till_done()
    # No VAT applied: sensor equals the market price.
    assert float(hass.states.get(RETURN_PRICE).state) == pytest.approx(0.08)


async def test_options_flow_vat_save_true(hass, setup_integration):
    """Saving True stores the option and the sensor recalculates with VAT."""
    entry, _ = setup_integration
    result = await _open_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_FEED_IN_ADJUSTMENT: 0.0, CONF_APPLY_FEED_IN_VAT: True},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_APPLY_FEED_IN_VAT] is True
    await hass.async_block_till_done()
    assert float(hass.states.get(RETURN_PRICE).state) == pytest.approx(
        round(0.08 * 1.21, 6)
    )


async def test_options_flow_vat_save_false(hass, setup_integration):
    """Saving False stores the option as disabled."""
    entry, _ = setup_integration
    result = await _open_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_FEED_IN_ADJUSTMENT: 0.0, CONF_APPLY_FEED_IN_VAT: False},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_APPLY_FEED_IN_VAT] is False
