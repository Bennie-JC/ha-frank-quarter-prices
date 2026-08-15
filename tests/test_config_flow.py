"""Tests for the config flow and the feed-in / price-zone options flow."""

from __future__ import annotations

import pytest
from homeassistant.data_entry_flow import FlowResultType, InvalidData

from custom_components.frank_quarter_prices.const import (
    CONF_APPLY_FEED_IN_VAT,
    CONF_CHEAP_ZONE_MARGIN_PERCENT,
    CONF_EXPENSIVE_ZONE_MARGIN_PERCENT,
    CONF_FEED_IN_ADJUSTMENT,
    CONF_OPTIMAL_CHEAP_DURATION_MINUTES,
    CONF_OPTIMAL_CHEAP_ENABLED,
    CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES,
    CONF_OPTIMAL_EXPENSIVE_ENABLED,
    DEFAULT_OPTIMAL_DURATION_MINUTES,
    DEFAULT_ZONE_MARGIN_PERCENT,
    DOMAIN,
)

RETURN_PRICE = "sensor.frank_current_return_price"
CHEAP_START = "sensor.frank_cheap_zone_start_today"
EXPENSIVE_START = "sensor.frank_expensive_zone_start_today"

# Legacy option key that never existed; stands in for any stale key an older
# install may still carry in ``.storage``.
LEGACY_KEY = "return_price_correction"


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


async def test_options_flow_field_order(hass, setup_integration):
    """The options form shows exactly the supported settings, in order.

    The form is flat but reads as three groups, top to bottom: the feed-in
    settings, the two price-zone margins, then the two optional optimal
    periods, each toggle immediately followed by its own duration. v0.1.6's
    four fields keep their original positions — the VAT checkbox still sits
    directly below the feed-in adjustment — and nothing was dropped.
    """
    entry, _ = setup_integration
    result = await _open_options(hass, entry)
    ordered_keys = [str(marker.schema) for marker in result["data_schema"].schema]
    assert ordered_keys == [
        CONF_FEED_IN_ADJUSTMENT,
        CONF_APPLY_FEED_IN_VAT,
        CONF_CHEAP_ZONE_MARGIN_PERCENT,
        CONF_EXPENSIVE_ZONE_MARGIN_PERCENT,
        CONF_OPTIMAL_CHEAP_ENABLED,
        CONF_OPTIMAL_CHEAP_DURATION_MINUTES,
        CONF_OPTIMAL_EXPENSIVE_ENABLED,
        CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES,
    ]


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


# --- Price-zone margin options (v0.1.6) ------------------------------------


async def test_config_flow_does_not_ask_for_zone_margins(hass):
    """Initial setup stays a single country question; margins use defaults."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"country": "BE"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert CONF_CHEAP_ZONE_MARGIN_PERCENT not in result["data"]
    assert CONF_EXPENSIVE_ZONE_MARGIN_PERCENT not in result["data"]


async def test_fresh_setup_gets_default_margins(hass, setup_integration):
    """A fresh entry without stored margins publishes 15% on both zones."""
    entry, _ = setup_integration
    assert CONF_CHEAP_ZONE_MARGIN_PERCENT not in entry.options
    assert CONF_EXPENSIVE_ZONE_MARGIN_PERCENT not in entry.options

    for entity_id in (CHEAP_START, EXPENSIVE_START):
        assert hass.states.get(entity_id).attributes["margin_percent"] == (
            DEFAULT_ZONE_MARGIN_PERCENT
        )


async def test_options_form_prefills_margin_defaults(hass, setup_integration):
    """An entry with no margins stored offers 15% as the form default."""
    entry, _ = setup_integration
    result = await _open_options(hass, entry)
    defaults = {
        str(marker.schema): marker.default()
        for marker in result["data_schema"].schema
        if marker.default is not None
    }
    assert defaults[CONF_CHEAP_ZONE_MARGIN_PERCENT] == DEFAULT_ZONE_MARGIN_PERCENT
    assert defaults[CONF_EXPENSIVE_ZONE_MARGIN_PERCENT] == DEFAULT_ZONE_MARGIN_PERCENT


async def test_options_flow_changes_cheap_margin_only(hass, setup_integration):
    """Changing only the cheap margin leaves the expensive one at its default."""
    entry, _ = setup_integration
    result = await _open_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CHEAP_ZONE_MARGIN_PERCENT: 25.0}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_CHEAP_ZONE_MARGIN_PERCENT] == 25.0
    await hass.async_block_till_done()

    assert hass.states.get(CHEAP_START).attributes["margin_percent"] == 25.0
    assert hass.states.get(EXPENSIVE_START).attributes["margin_percent"] == (
        DEFAULT_ZONE_MARGIN_PERCENT
    )


async def test_options_flow_changes_expensive_margin_only(hass, setup_integration):
    """Changing only the expensive margin leaves the cheap one at its default."""
    entry, _ = setup_integration
    result = await _open_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_EXPENSIVE_ZONE_MARGIN_PERCENT: 5.0}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert hass.states.get(EXPENSIVE_START).attributes["margin_percent"] == 5.0
    assert hass.states.get(CHEAP_START).attributes["margin_percent"] == (
        DEFAULT_ZONE_MARGIN_PERCENT
    )


async def test_options_flow_changes_both_margins(hass, setup_integration):
    """Both margins can be set independently in one save."""
    entry, _ = setup_integration
    result = await _open_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_CHEAP_ZONE_MARGIN_PERCENT: 20.0,
            CONF_EXPENSIVE_ZONE_MARGIN_PERCENT: 10.0,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert hass.states.get(CHEAP_START).attributes["margin_percent"] == 20.0
    assert hass.states.get(EXPENSIVE_START).attributes["margin_percent"] == 10.0


@pytest.mark.parametrize("value", [0.0, 1.0, 5.0, 15.0, 25.0, 49.0])
async def test_options_flow_boundary_margins_accepted(hass, setup_integration, value):
    """The documented range boundaries and the default are all accepted."""
    entry, _ = setup_integration
    result = await _open_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_CHEAP_ZONE_MARGIN_PERCENT: value,
            CONF_EXPENSIVE_ZONE_MARGIN_PERCENT: value,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_CHEAP_ZONE_MARGIN_PERCENT] == value
    assert entry.options[CONF_EXPENSIVE_ZONE_MARGIN_PERCENT] == value


@pytest.mark.parametrize("value", [-1.0, 50.0, 99.0, 100.0, 1000.0])
async def test_options_flow_out_of_range_margins_rejected(
    hass, setup_integration, value
):
    """Margins outside 0–100% are rejected by the selector."""
    entry, _ = setup_integration
    result = await _open_options(hass, entry)
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_CHEAP_ZONE_MARGIN_PERCENT: value}
        )
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_EXPENSIVE_ZONE_MARGIN_PERCENT: value}
        )


async def test_legacy_option_key_does_not_break_setup(hass, mock_client):
    """A stale unknown option key from an older install is ignored, not fatal."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Frank Quarter Prices (NL)",
        data={"country": "NL"},
        options={LEGACY_KEY: -0.017, CONF_FEED_IN_ADJUSTMENT: 0.0},
        unique_id="NL",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # The unknown key survives untouched (no risky migration) and the zone
    # entities come up on their defaults regardless.
    assert entry.options[LEGACY_KEY] == -0.017
    assert hass.states.get(CHEAP_START).attributes["margin_percent"] == (
        DEFAULT_ZONE_MARGIN_PERCENT
    )


async def test_legacy_option_key_is_not_offered_in_the_ui(hass, mock_client):
    """A stale unknown option key is never rendered as a form field."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Frank Quarter Prices (NL)",
        data={"country": "NL"},
        options={LEGACY_KEY: -0.017},
        unique_id="NL",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await _open_options(hass, entry)
    assert LEGACY_KEY not in [
        str(marker.schema) for marker in result["data_schema"].schema
    ]


# --- Optimal-period options -------------------------------------------------


async def test_optimal_periods_are_off_by_default(hass, setup_integration):
    """A fresh entry gets neither planner feature, and neither is stored."""
    entry, _ = setup_integration
    assert CONF_OPTIMAL_CHEAP_ENABLED not in entry.options
    assert CONF_OPTIMAL_EXPENSIVE_ENABLED not in entry.options

    result = await _open_options(hass, entry)
    defaults = {
        str(marker.schema): marker.default()
        for marker in result["data_schema"].schema
        if marker.default is not None
    }
    assert defaults[CONF_OPTIMAL_CHEAP_ENABLED] is False
    assert defaults[CONF_OPTIMAL_EXPENSIVE_ENABLED] is False
    # The duration is pre-filled even while the feature is off, so enabling it
    # is a single click rather than a click plus a number.
    assert defaults[CONF_OPTIMAL_CHEAP_DURATION_MINUTES] == (
        DEFAULT_OPTIMAL_DURATION_MINUTES
    )
    assert defaults[CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES] == (
        DEFAULT_OPTIMAL_DURATION_MINUTES
    )


async def test_config_flow_does_not_ask_for_optimal_periods(hass):
    """Initial setup stays a single country question."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"country": "NL"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert CONF_OPTIMAL_CHEAP_ENABLED not in result["data"]
    assert CONF_OPTIMAL_EXPENSIVE_ENABLED not in result["data"]


@pytest.mark.parametrize("value", [15, 30, 45, 60, 90, 120, 180, 240, 360, 480, 720])
async def test_optimal_duration_boundaries_accepted(hass, setup_integration, value):
    """Every documented duration, both boundaries included, is accepted."""
    entry, _ = setup_integration
    result = await _open_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_OPTIMAL_CHEAP_ENABLED: True,
            CONF_OPTIMAL_CHEAP_DURATION_MINUTES: value,
            CONF_OPTIMAL_EXPENSIVE_ENABLED: True,
            CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES: value,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_OPTIMAL_CHEAP_DURATION_MINUTES] == value
    assert entry.options[CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES] == value


@pytest.mark.parametrize("value", [0, 5, 10, 14, 721, 1000, 1440, -15, "abc"])
async def test_optimal_duration_out_of_range_rejected(hass, setup_integration, value):
    """Durations outside 15-720 minutes are rejected by the selector itself."""
    entry, _ = setup_integration
    result = await _open_options(hass, entry)
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_OPTIMAL_CHEAP_DURATION_MINUTES: value}
        )
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES: value}
        )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        (CONF_OPTIMAL_CHEAP_DURATION_MINUTES, 17),
        (CONF_OPTIMAL_CHEAP_DURATION_MINUTES, 22.5),
        (CONF_OPTIMAL_CHEAP_DURATION_MINUTES, 100),
        (CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES, 17),
        (CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES, 22.5),
        (CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES, 100),
    ],
)
async def test_off_step_duration_is_rejected_with_an_error(
    hass, setup_integration, key, value
):
    """A duration inside the range but off the 15-minute step is refused.

    The number selector checks the range and the type but *not* the step, so a
    submission that bypasses the frontend box would otherwise store a 17 that
    leaves the planner permanently unavailable for an invisible reason. The
    flow re-shows the form with a field error instead of storing it.
    """
    entry, _ = setup_integration
    result = await _open_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {key: value}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["errors"] == {key: "invalid_duration"}
    assert key not in entry.options


async def test_a_rejected_duration_keeps_the_other_edits_in_the_form(
    hass, setup_integration
):
    """Correcting one bad field must not mean retyping the whole form."""
    entry, _ = setup_integration
    result = await _open_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_FEED_IN_ADJUSTMENT: 0.02,
            CONF_CHEAP_ZONE_MARGIN_PERCENT: 25.0,
            CONF_OPTIMAL_CHEAP_ENABLED: True,
            CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 17,
        },
    )
    assert result["type"] == FlowResultType.FORM

    suggested = {
        str(marker.schema): marker.description["suggested_value"]
        for marker in result["data_schema"].schema
        if marker.description and "suggested_value" in marker.description
    }
    assert suggested[CONF_FEED_IN_ADJUSTMENT] == 0.02
    assert suggested[CONF_CHEAP_ZONE_MARGIN_PERCENT] == 25.0
    assert suggested[CONF_OPTIMAL_CHEAP_ENABLED] is True

    # Nothing was stored while the form was still invalid.
    assert CONF_FEED_IN_ADJUSTMENT not in entry.options


async def test_correcting_the_duration_then_saves_everything(hass, setup_integration):
    """After fixing the field, a resubmission stores the whole form."""
    entry, _ = setup_integration
    result = await _open_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_OPTIMAL_CHEAP_ENABLED: True, CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 17},
    )
    assert result["type"] == FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_OPTIMAL_CHEAP_ENABLED: True, CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 180},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_OPTIMAL_CHEAP_DURATION_MINUTES] == 180
    await hass.async_block_till_done()
    assert (
        hass.states.get("sensor.frank_optimal_cheap_period_today").attributes[
            "duration_minutes"
        ]
        == 180
    )


async def test_optimal_options_survive_a_margin_change(hass, setup_integration):
    """Retuning a zone margin does not silently reset the planner settings."""
    entry, _ = setup_integration
    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_OPTIMAL_CHEAP_ENABLED: True,
            CONF_OPTIMAL_CHEAP_DURATION_MINUTES: 180,
        },
    )
    await hass.async_block_till_done()

    result = await _open_options(hass, entry)
    submitted = {
        str(marker.schema): marker.default()
        for marker in result["data_schema"].schema
        if marker.default is not None
    }
    submitted[CONF_CHEAP_ZONE_MARGIN_PERCENT] = 25.0
    await hass.config_entries.options.async_configure(result["flow_id"], submitted)
    await hass.async_block_till_done()

    assert entry.options[CONF_CHEAP_ZONE_MARGIN_PERCENT] == 25.0
    assert entry.options[CONF_OPTIMAL_CHEAP_ENABLED] is True
    assert entry.options[CONF_OPTIMAL_CHEAP_DURATION_MINUTES] == 180


async def test_out_of_range_stored_margin_is_clamped(hass, mock_client):
    """A hand-edited out-of-range margin is clamped, never applied verbatim."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Frank Quarter Prices (NL)",
        data={"country": "NL"},
        options={
            CONF_CHEAP_ZONE_MARGIN_PERCENT: 400.0,
            CONF_EXPENSIVE_ZONE_MARGIN_PERCENT: -100.0,
        },
        unique_id="NL",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(CHEAP_START).attributes["margin_percent"] == 49.0
    assert hass.states.get(EXPENSIVE_START).attributes["margin_percent"] == 0.0
