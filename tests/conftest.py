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

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
import pytest_socket
from freezegun import freeze_time
from homeassistant.util import dt as dt_util

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

# Timezone the integration is documented and tested against.
TEST_TIMEZONE = "Europe/Amsterdam"

# Wall-clock instant ``setup_integration`` runs at. Pinned so the suite behaves
# identically whenever it runs: the coordinator only requests tomorrow from
# ``TOMORROW_PUBLISH_HOUR`` onwards, so a test set up "now" would fetch one day
# in the morning and two in the afternoon. 14:07 is deliberately off a quarter
# boundary and past the publication hour, matching the pre-existing expectation
# that both days are loaded during setup.
SETUP_NOW = datetime(2026, 8, 6, 14, 7, 0, tzinfo=ZoneInfo(TEST_TIMEZONE))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading the custom integration in every test."""
    yield


def build_block_span(
    start: datetime, till: datetime, market_price: float
) -> dict[str, Any]:
    """Build a normalized price block spanning ``start``..``till``."""
    market_price_tax = round(market_price * 0.21, 6)
    total = market_price + market_price_tax + _SOURCING_MARKUP + _ENERGY_TAX
    return {
        "from": start,
        "till": till,
        "duration_minutes": int((till - start).total_seconds() // 60),
        "market_price": market_price,
        "market_price_tax": market_price_tax,
        "sourcing_markup_price": _SOURCING_MARKUP,
        "energy_tax_price": _ENERGY_TAX,
        "total_price_eur_kwh": round(total, 6),
        "per_unit": "KWH",
    }


def build_block(start: datetime, market_price: float) -> dict[str, Any]:
    """Build a single normalized 15-minute price block (client output shape)."""
    return build_block_span(start, start + timedelta(minutes=15), market_price)


def build_local_day_blocks(
    day, market_price: float = 0.08, resolution_minutes: int = 15
) -> list[dict[str, Any]]:
    """Build the blocks covering one complete local calendar day.

    Steps through *absolute* time from local midnight to the next local
    midnight, which is what the API returns and what makes the 23-hour
    spring-forward day (92 quarters) and the 25-hour fall-back day (100
    quarters) come out right. Naive ``local_midnight + i * 15min`` arithmetic
    would silently produce a 96-block list on both.
    """
    cursor = dt_util.as_utc(dt_util.start_of_local_day(day))
    end = dt_util.as_utc(dt_util.start_of_local_day(day + timedelta(days=1)))
    step = timedelta(minutes=resolution_minutes)

    blocks: list[dict[str, Any]] = []
    while cursor < end:
        nxt = min(cursor + step, end)
        blocks.append(
            build_block_span(
                dt_util.as_local(cursor), dt_util.as_local(nxt), market_price
            )
        )
        cursor = nxt
    return blocks


def build_day(day, market_price: float = 0.08) -> dict[str, Any]:
    """Build a full local day of quarter-hour blocks for a date."""
    return {"prices": build_local_day_blocks(day, market_price)}


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
    """Set up the integration with the mocked client and return the entry.

    The clock stays frozen at :data:`SETUP_NOW` for the duration of the test so
    the coordinator's time-dependent fetch decisions are reproducible.
    """
    await hass.config.async_set_time_zone(TEST_TIMEZONE)
    freezer = freeze_time(SETUP_NOW)
    freezer.start()
    try:
        mock_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        yield mock_config_entry, mock_client
    finally:
        freezer.stop()
