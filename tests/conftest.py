"""Shared fixtures for the Frank Quarter Prices tests."""

from __future__ import annotations

import asyncio
import sys

# On Windows the default ProactorEventLoop uses a socket for its self-pipe,
# which pytest_socket (enabled by pytest-homeassistant-custom-component) blocks.
# Force the selector loop before any loop is created so the HA test harness can
# run locally on Windows. No effect on Linux/macOS (CI).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from datetime import datetime, timedelta  # noqa: E402
from typing import Any  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402

import pytest  # noqa: E402
import pytest_socket  # noqa: E402

from homeassistant.util import dt as dt_util  # noqa: E402

# On Windows every asyncio event loop creates an ``AF_INET`` socket for its
# self-pipe, which pytest_socket (enabled by pytest-homeassistant) blocks. On
# Linux/macOS CI the self-pipe uses an allowed unix socket, so blocking is fine
# there. Neutralise the blocker for local Windows runs only.
if sys.platform == "win32":
    pytest_socket.disable_socket = lambda *args, **kwargs: None

from custom_components.frank_quarter_prices.const import DOMAIN

_CLIENT_METHOD = (
    "custom_components.frank_quarter_prices.frank_client."
    "FrankClient.async_get_prices_for_date"
)

# Constant purchase-side components (mirror the live API shape).
_SOURCING_MARKUP = 0.018
_ENERGY_TAX = 0.11085


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading the custom integration in every test."""
    yield


def build_block(start: datetime, market_price: float) -> dict[str, Any]:
    """Build a single normalized 15-minute price block (client output shape)."""
    market_price_tax = round(market_price * 0.21, 6)
    total = market_price + market_price_tax + _SOURCING_MARKUP + _ENERGY_TAX
    return {
        "from": start,
        "till": start + timedelta(minutes=15),
        "duration_minutes": 15,
        "market_price": market_price,
        "market_price_tax": market_price_tax,
        "sourcing_markup_price": _SOURCING_MARKUP,
        "energy_tax_price": _ENERGY_TAX,
        "total_price_eur_kwh": round(total, 6),
        "per_unit": "KWH",
    }


def build_day(day, market_price: float = 0.08) -> dict[str, Any]:
    """Build a full local day of 96 quarter-hour blocks for a date."""
    midnight = dt_util.start_of_local_day(day)
    blocks = [
        build_block(midnight + timedelta(minutes=15 * i), market_price)
        for i in range(96)
    ]
    return {"prices": blocks}


@pytest.fixture
def mock_config_entry():
    """Return a mock config entry for the NL integration."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    return MockConfigEntry(
        domain=DOMAIN,
        title="Frank Quarter Prices (NL)",
        data={"country": "NL"},
        options={},
        unique_id="NL",
    )


@pytest.fixture
def mock_client():
    """Patch the Frank API client to return generated price data.

    The mock builds a full local day of quarter-hour blocks for whatever date
    the coordinator requests, so the current block always covers "now" without
    hitting the network. Its ``call_count`` lets tests assert no extra request.
    """
    mock = AsyncMock(side_effect=lambda target_date: build_day(target_date))
    with patch(_CLIENT_METHOD, mock):
        yield mock


@pytest.fixture
async def setup_integration(hass, mock_config_entry, mock_client):
    """Set up the integration with the mocked client and return the entry."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry, mock_client
