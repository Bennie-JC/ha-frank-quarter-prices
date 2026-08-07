"""Backward-compatibility guard for the public entity contract.

Everything below is the contract as released in v0.1.4. Dashboards,
automations, templates and external EMS consumers are written against exactly
these entity ids, unique ids, names, units and attribute keys, so an internal
refactor — the issue #3 caching rework, or anything after it — must leave every
one of them untouched. A sensor that disappears, gets renamed, changes unit or
grows/loses a public attribute fails here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

import pytest
from homeassistant.const import ATTR_FRIENDLY_NAME
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.frank_quarter_prices.const import DOMAIN

pytestmark = pytest.mark.usefixtures("setup_integration")

# Attributes Home Assistant itself adds; asserted separately from the
# integration's own attribute keys.
_HA_MANAGED_ATTRS = {
    ATTR_FRIENDLY_NAME,
    "device_class",
    "state_class",
    "unit_of_measurement",
    "icon",
}

# Attribute keys shared by the cheapest/most-expensive *price* sensors.
_BLOCK_PRICE_ATTRS = {
    "time",
    "timestamp",
    "end_timestamp",
    "duration_minutes",
    "full_block",
}

# Attribute keys shared by the cheapest/most-expensive *time* sensors.
_BLOCK_TIME_ATTRS = {
    "price",
    "timestamp",
    "end_timestamp",
    "duration_minutes",
    "full_block",
}

# Attribute keys shared by the two full-day price-list sensors.
_DAY_LIST_ATTRS = {
    "prices",
    "resolution_minutes",
    "cheapest_block",
    "most_expensive_block",
    "average_price",
    "min_price",
    "max_price",
}

# The complete v0.1.4 public contract, keyed by entity id.
#
#   unique_id_suffix -- the unique id is f"{entry_id}_{suffix}"
#   name             -- friendly name as shown in the UI
#   unit             -- native unit of measurement (None when unitless)
#   device_class     -- sensor device class (None when unset)
#   state_class      -- deliberately unset on every entity
#   icon             -- deliberately unset on every entity
#   entity_category  -- deliberately unset: all entities are primary
#   attrs            -- exact set of integration-provided attribute keys
#   state_type       -- Python type the state parses back to
BASELINE: dict[str, dict[str, Any]] = {
    "sensor.frank_current_price": {
        "unique_id_suffix": "current_price",
        "name": "Frank Current price",
        "unit": "EUR/kWh",
        "device_class": "monetary",
        "state_class": None,
        "icon": None,
        "entity_category": None,
        "attrs": _BLOCK_PRICE_ATTRS,
        "state_type": float,
    },
    "sensor.frank_current_return_price": {
        "unique_id_suffix": "current_return_price",
        "name": "Frank Current feed-in price",
        "unit": "EUR/kWh",
        "device_class": "monetary",
        "state_class": None,
        "icon": None,
        "entity_category": None,
        "attrs": {
            "market_price_source",
            "market_price",
            "feed_in_adjustment",
            "apply_vat",
            "vat_rate",
            "calculation_method",
        },
        "state_type": float,
    },
    "sensor.frank_prices_today": {
        "unique_id_suffix": "prices_today",
        "name": "Frank Prices today",
        "unit": "blocks",
        "device_class": None,
        "state_class": None,
        "icon": None,
        "entity_category": None,
        "attrs": _DAY_LIST_ATTRS,
        "state_type": int,
    },
    "sensor.frank_prices_tomorrow": {
        "unique_id_suffix": "prices_tomorrow",
        "name": "Frank Prices tomorrow",
        "unit": "blocks",
        "device_class": None,
        "state_class": None,
        "icon": None,
        "entity_category": None,
        "attrs": _DAY_LIST_ATTRS | {"available", "last_attempt"},
        "state_type": int,
    },
    "sensor.frank_cheapest_today": {
        "unique_id_suffix": "cheapest_today",
        "name": "Frank Cheapest today",
        "unit": "EUR/kWh",
        "device_class": "monetary",
        "state_class": None,
        "icon": None,
        "entity_category": None,
        "attrs": _BLOCK_PRICE_ATTRS,
        "state_type": float,
    },
    "sensor.frank_cheapest_time_today": {
        "unique_id_suffix": "cheapest_time_today",
        "name": "Frank Cheapest time today",
        "unit": None,
        "device_class": None,
        "state_class": None,
        "icon": None,
        "entity_category": None,
        "attrs": _BLOCK_TIME_ATTRS,
        "state_type": str,
    },
    "sensor.frank_most_expensive_today": {
        "unique_id_suffix": "most_expensive_today",
        "name": "Frank Most expensive today",
        "unit": "EUR/kWh",
        "device_class": "monetary",
        "state_class": None,
        "icon": None,
        "entity_category": None,
        "attrs": _BLOCK_PRICE_ATTRS,
        "state_type": float,
    },
    "sensor.frank_most_expensive_time_today": {
        "unique_id_suffix": "most_expensive_time_today",
        "name": "Frank Most expensive time today",
        "unit": None,
        "device_class": None,
        "state_class": None,
        "icon": None,
        "entity_category": None,
        "attrs": _BLOCK_TIME_ATTRS,
        "state_type": str,
    },
    "sensor.frank_cheapest_tomorrow": {
        "unique_id_suffix": "cheapest_tomorrow",
        "name": "Frank Cheapest tomorrow",
        "unit": "EUR/kWh",
        "device_class": "monetary",
        "state_class": None,
        "icon": None,
        "entity_category": None,
        "attrs": _BLOCK_PRICE_ATTRS,
        "state_type": float,
    },
    "sensor.frank_cheapest_time_tomorrow": {
        "unique_id_suffix": "cheapest_time_tomorrow",
        "name": "Frank Cheapest time tomorrow",
        "unit": None,
        "device_class": None,
        "state_class": None,
        "icon": None,
        "entity_category": None,
        "attrs": _BLOCK_TIME_ATTRS,
        "state_type": str,
    },
    "sensor.frank_most_expensive_tomorrow": {
        "unique_id_suffix": "most_expensive_tomorrow",
        "name": "Frank Most expensive tomorrow",
        "unit": "EUR/kWh",
        "device_class": "monetary",
        "state_class": None,
        "icon": None,
        "entity_category": None,
        "attrs": _BLOCK_PRICE_ATTRS,
        "state_type": float,
    },
    "sensor.frank_most_expensive_time_tomorrow": {
        "unique_id_suffix": "most_expensive_time_tomorrow",
        "name": "Frank Most expensive time tomorrow",
        "unit": None,
        "device_class": None,
        "state_class": None,
        "icon": None,
        "entity_category": None,
        "attrs": _BLOCK_TIME_ATTRS,
        "state_type": str,
    },
    "binary_sensor.frank_tomorrow_prices_available": {
        "unique_id_suffix": "tomorrow_prices_available",
        "name": "Frank Tomorrow prices available",
        "unit": None,
        "device_class": None,
        "state_class": None,
        "icon": None,
        "entity_category": None,
        "attrs": set(),
        "state_type": str,
    },
}

# Keys of a single price block, in the order the client produces them. External
# consumers index these directly out of the ``prices`` array.
PRICE_BLOCK_KEYS = [
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


def _integration_attrs(state) -> set[str]:
    """Return the attribute keys the integration itself contributes."""
    return set(state.attributes) - _HA_MANAGED_ATTRS


def test_no_entity_is_missing_or_extra(hass):
    """The integration creates exactly the v0.1.4 set of entities."""
    registry = er.async_get(hass)
    created = {
        entity.entity_id
        for entity in registry.entities.values()
        if entity.platform == DOMAIN
    }
    assert created == set(BASELINE)


@pytest.mark.parametrize("entity_id", sorted(BASELINE))
def test_entity_registry_metadata_unchanged(hass, entity_id):
    """Unique id, name, unit, categories and enabled-default are unchanged."""
    expected = BASELINE[entity_id]
    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)

    assert entry is not None, f"{entity_id} is missing from the entity registry"
    # The unique id is what survives a rename; breaking it orphans the entity
    # and silently creates a duplicate for every existing installation.
    assert entry.unique_id.endswith(f"_{expected['unique_id_suffix']}")
    assert entry.unique_id == f"{entry.config_entry_id}_{expected['unique_id_suffix']}"
    assert entry.unit_of_measurement == expected["unit"]
    assert entry.device_class is None
    assert entry.original_device_class == expected["device_class"]
    assert entry.entity_category == expected["entity_category"]
    assert entry.disabled_by is None
    assert entry.hidden_by is None
    assert entry.translation_key is None
    assert entry.original_icon == expected["icon"]


@pytest.mark.parametrize("entity_id", sorted(BASELINE))
def test_entity_state_contract_unchanged(hass, entity_id):
    """Friendly name, state type and the exact attribute keys are unchanged."""
    expected = BASELINE[entity_id]
    state = hass.states.get(entity_id)

    assert state is not None, f"{entity_id} has no state"
    assert state.state not in ("unavailable", "unknown"), entity_id
    assert state.attributes[ATTR_FRIENDLY_NAME] == expected["name"]
    assert state.attributes.get("device_class") == expected["device_class"]
    assert state.attributes.get("state_class") == expected["state_class"]
    assert state.attributes.get("unit_of_measurement") == expected["unit"]
    assert state.attributes.get("icon") == expected["icon"]
    assert _integration_attrs(state) == expected["attrs"]
    # The state must stay machine-readable in its original type.
    assert expected["state_type"](state.state) is not None


def test_all_entities_share_one_service_device(hass):
    """Device identity and association are unchanged."""
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    device_ids = {
        entity_registry.async_get(entity_id).device_id for entity_id in BASELINE
    }
    assert len(device_ids) == 1

    device = device_registry.async_get(device_ids.pop())
    entry_id = next(iter(device.config_entries))
    assert device.identifiers == {(DOMAIN, entry_id)}
    assert device.name == "Frank"
    assert device.manufacturer == "Jouw Cloud B.V."
    assert device.model == "Frank Energie Market Prices"
    assert device.entry_type is dr.DeviceEntryType.SERVICE


# --- EMS contract ----------------------------------------------------------
#
# sensor.frank_prices_today / _tomorrow are the entities external systems such
# as Alpha EMS Manager plan against. Their ``prices`` array is the interface.


@pytest.mark.parametrize(
    "entity_id", ["sensor.frank_prices_today", "sensor.frank_prices_tomorrow"]
)
def test_full_price_array_schema_unchanged(hass, entity_id):
    """Every block keeps the same keys, value types and timestamp format."""
    state = hass.states.get(entity_id)
    prices = state.attributes["prices"]

    assert isinstance(prices, list)
    assert len(prices) == 96
    assert int(state.state) == len(prices)

    for block in prices:
        assert list(block) == PRICE_BLOCK_KEYS, "key set or order changed"
        # Timestamps stay local ISO 8601 strings with an offset, not epochs
        # and not datetime objects.
        for key in ("from", "till"):
            assert isinstance(block[key], str)
            parsed = datetime.fromisoformat(block[key])
            assert parsed.tzinfo is not None
        assert isinstance(block["duration_minutes"], int)
        assert isinstance(block["per_unit"], str)
        for key in (
            "market_price",
            "market_price_tax",
            "sourcing_markup_price",
            "energy_tax_price",
            "total_price_eur_kwh",
        ):
            assert isinstance(block[key], float), key


@pytest.mark.parametrize(
    "entity_id", ["sensor.frank_prices_today", "sensor.frank_prices_tomorrow"]
)
def test_full_price_array_is_chronological_and_contiguous(hass, entity_id):
    """Ordering is unchanged: chronological, gap-free, quarter-hour blocks."""
    prices = hass.states.get(entity_id).attributes["prices"]

    starts = [datetime.fromisoformat(block["from"]) for block in prices]
    assert starts == sorted(starts)

    for block, following in pairwise(prices):
        assert block["till"] == following["from"]
        assert block["duration_minutes"] == 15


def test_today_and_tomorrow_arrays_stay_separated(hass):
    """Day separation is unchanged: neither list leaks into the other."""
    today = hass.states.get("sensor.frank_prices_today").attributes["prices"]
    tomorrow = hass.states.get("sensor.frank_prices_tomorrow").attributes["prices"]

    today_dates = {datetime.fromisoformat(b["from"]).date() for b in today}
    tomorrow_dates = {datetime.fromisoformat(b["from"]).date() for b in tomorrow}

    assert len(today_dates) == 1
    assert len(tomorrow_dates) == 1
    assert tomorrow_dates.pop() == today_dates.pop() + timedelta(days=1)


def test_day_summary_attributes_unchanged(hass):
    """The derived summary values EMS consumers read keep their shape."""
    for entity_id in ("sensor.frank_prices_today", "sensor.frank_prices_tomorrow"):
        attrs = hass.states.get(entity_id).attributes
        assert attrs["resolution_minutes"] == 15
        assert isinstance(attrs["average_price"], float)
        assert isinstance(attrs["min_price"], float)
        assert isinstance(attrs["max_price"], float)
        for key in ("cheapest_block", "most_expensive_block"):
            assert list(attrs[key]) == PRICE_BLOCK_KEYS

    tomorrow = hass.states.get("sensor.frank_prices_tomorrow")
    assert tomorrow.attributes["available"] is True
