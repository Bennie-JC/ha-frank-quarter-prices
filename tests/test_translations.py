"""Tests that every options-flow field resolves to a translated label.

Home Assistant renders a config/options form by looking up
``component.<domain>.options.step.<step_id>.data.<field>`` in the translation
bundle for the active language. When that lookup misses, the frontend falls
back to printing the raw schema key -- so a field whose translation is missing
shows up in the UI as ``optimal_cheap_enabled`` instead of a readable label.

Nothing in the schema itself can catch that: the form serializes and validates
perfectly fine with no translations at all. These tests close the gap by
driving the real options flow, taking the field list from the schema Home
Assistant actually renders, and resolving each one through Home Assistant's own
translation loader for both shipped languages. Adding an option without a label
or a description therefore fails the suite instead of reaching a user as a raw
key.
"""

from __future__ import annotations

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.translation import async_get_translations

from custom_components.frank_quarter_prices.const import DOMAIN

# Both languages the integration ships. English doubles as Home Assistant's
# fallback locale, so a gap there leaks into every untranslated language.
LANGUAGES = ("en", "nl")

_PREFIX = f"component.{DOMAIN}.options.step.init"

# The exact user-visible labels, pinned so a well-meaning reword cannot quietly
# drift the UI away from the documented settings list in the READMEs.
EXPECTED_NL = {
    "feed_in_adjustment": "Teruglevercorrectie",
    "apply_feed_in_vat": "21% btw toepassen op terugleverprijs",
    "cheap_zone_margin_percent": "Marge goedkope prijszone",
    "expensive_zone_margin_percent": "Marge dure prijszone",
    "optimal_cheap_enabled": "Optimale goedkope periode inschakelen",
    "optimal_cheap_duration_minutes": "Duur optimale goedkope periode",
    "optimal_expensive_enabled": "Optimale dure periode inschakelen",
    "optimal_expensive_duration_minutes": "Duur optimale dure periode",
}

EXPECTED_EN = {
    "feed_in_adjustment": "Feed-in adjustment",
    "apply_feed_in_vat": "Apply 21% VAT to feed-in price",
    "cheap_zone_margin_percent": "Cheap price-zone margin",
    "expensive_zone_margin_percent": "Expensive price-zone margin",
    "optimal_cheap_enabled": "Enable optimal cheap period",
    "optimal_cheap_duration_minutes": "Optimal cheap period duration",
    "optimal_expensive_enabled": "Enable optimal expensive period",
    "optimal_expensive_duration_minutes": "Optimal expensive period duration",
}

# The order the user reads them in, top to bottom: feed-in, then the two zone
# margins, then each optimal period with its own duration directly beneath it.
EXPECTED_ORDER = list(EXPECTED_NL)


async def _schema_keys(hass, entry) -> list[str]:
    """Return the field keys of the rendered options form, in display order."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    return [str(marker) for marker in result["data_schema"].schema]


async def _bundle(hass, language: str) -> dict[str, str]:
    """Return the flattened options translations Home Assistant would serve."""
    return await async_get_translations(hass, language, "options", {DOMAIN})


async def test_the_form_renders_the_documented_fields_in_order(hass, setup_integration):
    """The options form shows exactly the eight documented fields, in order."""
    entry, _ = setup_integration
    assert await _schema_keys(hass, entry) == EXPECTED_ORDER


@pytest.mark.parametrize("language", LANGUAGES)
async def test_every_field_has_a_label(hass, setup_integration, language):
    """Every rendered field resolves to a label, so no raw key can appear."""
    entry, _ = setup_integration
    bundle = await _bundle(hass, language)

    missing = [
        key
        for key in await _schema_keys(hass, entry)
        if f"{_PREFIX}.data.{key}" not in bundle
    ]
    assert not missing, f"no {language} label for: {missing}"


@pytest.mark.parametrize("language", LANGUAGES)
async def test_no_label_is_just_the_raw_key(hass, setup_integration, language):
    """A label that echoes its own key would be indistinguishable from a miss."""
    entry, _ = setup_integration
    bundle = await _bundle(hass, language)

    for key in await _schema_keys(hass, entry):
        label = bundle[f"{_PREFIX}.data.{key}"]
        assert label != key
        assert label.strip()


@pytest.mark.parametrize("language", LANGUAGES)
async def test_every_field_has_a_description(hass, setup_integration, language):
    """Every field explains itself, so no setting is a mystery in the UI."""
    entry, _ = setup_integration
    bundle = await _bundle(hass, language)

    missing = [
        key
        for key in await _schema_keys(hass, entry)
        if f"{_PREFIX}.data_description.{key}" not in bundle
    ]
    assert not missing, f"no {language} description for: {missing}"


@pytest.mark.parametrize(
    ("language", "expected"), [("nl", EXPECTED_NL), ("en", EXPECTED_EN)]
)
async def test_the_labels_are_exactly_what_the_readmes_document(
    hass, setup_integration, language, expected
):
    """The rendered labels match the settings tables in README and README_EN."""
    entry, _ = setup_integration
    bundle = await _bundle(hass, language)

    actual = {
        key: bundle[f"{_PREFIX}.data.{key}"] for key in await _schema_keys(hass, entry)
    }
    assert actual == expected


@pytest.mark.parametrize("language", LANGUAGES)
async def test_the_duration_error_is_translated(hass, setup_integration, language):
    """The off-step duration error is a sentence, not an ``invalid_duration`` key."""
    bundle = await _bundle(hass, language)

    key = f"component.{DOMAIN}.options.error.invalid_duration"
    assert key in bundle
    assert bundle[key] != "invalid_duration"
    # The message has to say which values are acceptable to be actionable.
    assert "15" in bundle[key] and "720" in bundle[key]


@pytest.mark.parametrize("language", LANGUAGES)
async def test_the_planner_descriptions_state_the_duration_bounds(
    hass, setup_integration, language
):
    """Each duration description names the 15-720 range and the 15-minute step."""
    bundle = await _bundle(hass, language)

    for key in (
        "optimal_cheap_duration_minutes",
        "optimal_expensive_duration_minutes",
    ):
        description = bundle[f"{_PREFIX}.data_description.{key}"]
        assert "15" in description
        assert "720" in description


@pytest.mark.parametrize("language", LANGUAGES)
async def test_the_planner_descriptions_disclaim_the_zone_margin(
    hass, setup_integration, language
):
    """Each toggle says it is independent of the matching price-zone margin.

    The two features are easy to confuse -- both talk about "cheap" and both
    have a setting -- so the distinction has to be visible at the point of
    configuration, not only in the README.
    """
    bundle = await _bundle(hass, language)

    for key in ("optimal_cheap_enabled", "optimal_expensive_enabled"):
        description = bundle[f"{_PREFIX}.data_description.{key}"].lower()
        assert "zone" in description


async def test_both_languages_expose_the_same_keys(hass, setup_integration):
    """Dutch and English stay in step, so neither language can fall behind."""

    def _own(bundle: dict[str, str]) -> set[str]:
        return {key for key in bundle if key.startswith(f"component.{DOMAIN}.")}

    assert _own(await _bundle(hass, "nl")) == _own(await _bundle(hass, "en"))
