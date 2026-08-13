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

from datetime import datetime, timedelta, timezone
from datetime import time as dt_time
from typing import Any
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
import pytest_socket
from freezegun import freeze_time

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

# Timezone the integration is documented and tested against. This is both the
# NL market timezone and, by default, the Home Assistant timezone the tests
# configure — the market-timezone tests deliberately drive the two apart.
TEST_TIMEZONE = "Europe/Amsterdam"

# The NL market's own timezone: where Frank's price day starts and ends,
# whatever Home Assistant is configured to.
MARKET_TIMEZONE = "Europe/Amsterdam"

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


def market_midnight(day, timezone_name: str = MARKET_TIMEZONE):
    """Return market-local midnight starting ``day``."""
    return datetime.combine(day, dt_time.min, tzinfo=ZoneInfo(timezone_name))


def build_local_day_blocks(
    day,
    market_price: float | None = 0.08,
    resolution_minutes: int = 15,
    timezone_name: str = MARKET_TIMEZONE,
) -> list[dict[str, Any]]:
    """Build the blocks covering one complete **market** calendar day.

    Steps through *absolute* time from market midnight to the next market
    midnight, which is what the API returns and what makes the 23-hour
    spring-forward day (92 quarters) and the 25-hour fall-back day (100
    quarters) come out right. Naive ``midnight + i * 15min`` arithmetic would
    silently produce a 96-block list on both.

    The span is anchored to the *market* timezone, never to whatever timezone
    Home Assistant happens to be configured in — that is the whole point of the
    market-day handling under test.

    ``market_price`` of ``None`` produces the realistic shaped day from
    :func:`realistic_market_price`; a number produces a flat day at that price.
    A flat day is still what most cache and scheduler tests want, because they
    care about coverage rather than about price shape.
    """
    cursor = market_midnight(day, timezone_name).astimezone(timezone.utc)
    end = market_midnight(day + timedelta(days=1), timezone_name).astimezone(
        timezone.utc
    )
    step = timedelta(minutes=resolution_minutes)
    tz = ZoneInfo(timezone_name)

    blocks: list[dict[str, Any]] = []
    while cursor < end:
        nxt = min(cursor + step, end)
        start_local = cursor.astimezone(tz)
        price = (
            realistic_market_price(start_local)
            if market_price is None
            else market_price
        )
        blocks.append(build_block_span(start_local, nxt.astimezone(tz), price))
        cursor = nxt
    return blocks


def realistic_market_price(start_local: datetime) -> float:
    """Return a realistic Dutch market price for a block's market-local start.

    Shaped like an ordinary summer day rather than sized for a test: a solar
    dip around midday and an evening peak, at magnitudes the real API returns
    (a few cents per kWh). The all-in totals this produces span roughly
    0.15-0.44 EUR/kWh.

    Deliberately keyed on the market-local *time of day* rather than on a block
    index, so the 92- and 100-quarter daylight-saving days get the same shape
    without any special-casing.

    The 14:00-18:00 plateau sits at exactly 0.08 so that the long-standing
    assertions anchored on :data:`SETUP_NOW` (14:07) keep their original values.
    """
    hour = start_local.hour + start_local.minute / 60
    if 11.0 <= hour < 13.0:
        return 0.018  # midday solar dip -> the cheap zone
    if 13.0 <= hour < 14.0:
        return 0.065
    if 14.0 <= hour < 18.0:
        return 0.08  # the SETUP_NOW plateau
    if 18.0 <= hour < 21.0:
        return 0.26  # evening peak -> the expensive zone
    if hour >= 21.0:
        return 0.12
    return 0.075  # night and morning


def build_day(day, market_price: float | None = None) -> dict[str, Any]:
    """Build a full market day of quarter-hour blocks for a date.

    Defaults to the realistic shaped day: a flat day has no cheapest-versus-
    most-expensive distinction at all, so it can no longer produce price zones
    and would leave the six zone entities unavailable in every shared fixture.
    """
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
