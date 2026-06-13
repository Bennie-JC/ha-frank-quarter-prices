"""Client for communicating with the Frank Energie GraphQL API.

This client talks to the public Frank Energie GraphQL endpoint, which does not
require authentication for market prices. It fetches the quarter-hourly
electricity prices for a given date and normalizes them into a stable structure
that the rest of the integration consumes.
"""

from __future__ import annotations

import asyncio
from datetime import date as date_type, datetime
import logging
from typing import Any

import aiohttp
from aiohttp import ClientError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import (
    COUNTRY_NL,
    DEFAULT_COUNTRY,
    GRAPHQL_ENDPOINT,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    SUPPORTED_COUNTRIES,
)

_LOGGER = logging.getLogger(__name__)

# GraphQL query for the quarter-hourly market prices on a given date.
MARKET_PRICES_QUERY = """
query MarketPrices($date: String!) {
  marketPrices(date: $date) {
    electricityPrices {
      from
      till
      marketPrice
      marketPriceTax
      sourcingMarkupPrice
      energyTaxPrice
      perUnit
    }
  }
}
"""

# Delay (seconds) between retry attempts.
RETRY_BACKOFF = 2


class FrankClientError(Exception):
    """Base error for the Frank client."""


class FrankClientAuthError(FrankClientError):
    """Raised when authentication with the Frank API fails."""


class FrankClient:
    """Client wrapper around the Frank Energie GraphQL API."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        country: str = DEFAULT_COUNTRY,
    ) -> None:
        """Initialize the client."""
        self._hass = hass
        self._entry = entry
        self._country = country if country in SUPPORTED_COUNTRIES else DEFAULT_COUNTRY
        self._session = async_get_clientsession(hass)

    async def async_get_prices_for_date(
        self, target_date: date_type
    ) -> dict[str, Any]:
        """Fetch and normalize the quarter-hourly prices for a given date.

        Returns a dict of the shape ``{"prices": [...]}`` where each price entry
        is normalized. Invalid records are skipped and logged.
        """
        payload = {
            "query": MARKET_PRICES_QUERY,
            "variables": {"date": target_date.isoformat()},
            "operationName": "MarketPrices",
        }

        data = await self._async_request(payload)
        raw_prices = self._extract_electricity_prices(data)

        prices: list[dict[str, Any]] = []
        for record in raw_prices:
            normalized = self._normalize_record(record)
            if normalized is not None:
                prices.append(normalized)

        _LOGGER.debug(
            "Fetched %d valid price records for %s (country=%s)",
            len(prices),
            target_date.isoformat(),
            self._country,
        )

        return {"prices": prices}

    async def _async_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Perform the GraphQL request with timeout and retries."""
        headers = {"Content-Type": "application/json"}
        # NL is the default; only send the x-country header for other countries.
        if self._country != COUNTRY_NL:
            headers["x-country"] = self._country

        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with self._session.post(
                    GRAPHQL_ENDPOINT,
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                ) as response:
                    response.raise_for_status()
                    data: dict[str, Any] = await response.json()

                if errors := data.get("errors"):
                    raise FrankClientError(f"GraphQL errors: {errors}")

                return data
            except (ClientError, asyncio.TimeoutError) as err:
                last_error = err
                _LOGGER.warning(
                    "Frank API request failed (attempt %d/%d): %s",
                    attempt,
                    MAX_RETRIES,
                    err,
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF * attempt)

        _LOGGER.error(
            "Frank API request failed after %d attempts: %s", MAX_RETRIES, last_error
        )
        raise FrankClientError(
            f"Failed to fetch data after {MAX_RETRIES} attempts"
        ) from last_error

    @staticmethod
    def _extract_electricity_prices(data: dict[str, Any]) -> list[dict[str, Any]]:
        """Safely extract the electricity prices list from the response."""
        market_prices = (data.get("data") or {}).get("marketPrices") or {}
        electricity_prices = market_prices.get("electricityPrices")
        if not isinstance(electricity_prices, list):
            _LOGGER.warning("No electricityPrices list found in response")
            return []
        return electricity_prices

    @staticmethod
    def _normalize_record(record: Any) -> dict[str, Any] | None:
        """Validate and normalize a single price record.

        Returns ``None`` when the record is invalid so the caller can skip it.
        """
        if not isinstance(record, dict):
            _LOGGER.debug("Skipping non-dict price record: %r", record)
            return None

        try:
            from_dt = FrankClient._parse_datetime(record.get("from"))
            till_dt = FrankClient._parse_datetime(record.get("till"))

            market_price = float(record["marketPrice"])
            market_price_tax = float(record["marketPriceTax"])
            sourcing_markup_price = float(record["sourcingMarkupPrice"])
            energy_tax_price = float(record["energyTaxPrice"])

            per_unit = record.get("perUnit")
            if not isinstance(per_unit, str) or not per_unit:
                raise ValueError(f"Invalid perUnit: {per_unit!r}")
        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.warning("Skipping invalid price record %r: %s", record, err)
            return None

        if from_dt is None or till_dt is None or till_dt <= from_dt:
            _LOGGER.warning(
                "Skipping price record with invalid interval: from=%s till=%s",
                record.get("from"),
                record.get("till"),
            )
            return None

        duration_minutes = int((till_dt - from_dt).total_seconds() // 60)
        total_price = (
            market_price
            + market_price_tax
            + sourcing_markup_price
            + energy_tax_price
        )

        return {
            "from": from_dt,
            "till": till_dt,
            "duration_minutes": duration_minutes,
            "market_price": market_price,
            "market_price_tax": market_price_tax,
            "sourcing_markup_price": sourcing_markup_price,
            "energy_tax_price": energy_tax_price,
            "total_price_eur_kwh": round(total_price, 6),
            "per_unit": per_unit,
        }

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        """Parse an ISO 8601 datetime string into a local timezone-aware datetime."""
        if not isinstance(value, str) or not value:
            return None
        parsed = dt_util.parse_datetime(value)
        if parsed is None:
            return None
        # Ensure the datetime is timezone-aware, then convert to HA local time.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_util.UTC)
        return dt_util.as_local(parsed)
