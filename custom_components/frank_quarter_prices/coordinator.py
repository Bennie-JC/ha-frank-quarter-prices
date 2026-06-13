"""DataUpdateCoordinator for the Frank Quarter Prices integration."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .frank_client import FrankClient, FrankClientAuthError, FrankClientError

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

# Default resolution to assume when it cannot be derived from the data.
DEFAULT_RESOLUTION_MINUTES = 15


class FrankQuarterPricesCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate fetching of Frank quarter prices."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: FrankClient,
    ) -> None:
        """Initialize the coordinator."""
        self.client = client
        self.entry = entry

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch today's and tomorrow's prices from the Frank API."""
        now = dt_util.now()
        today = now.date()
        tomorrow = today + timedelta(days=1)

        # 1. Always fetch today. Failures here are fatal for the update.
        try:
            today_result = await self.client.async_get_prices_for_date(today)
        except FrankClientAuthError as err:
            raise UpdateFailed(f"Authentication error: {err}") from err
        except FrankClientError as err:
            raise UpdateFailed(f"Error communicating with Frank API: {err}") from err

        today_prices = self._filter_for_day(today_result.get("prices", []), today)

        # 2. Always attempt tomorrow. Failures here are non-fatal: tomorrow's
        #    prices are typically only published after ~15:00 local time.
        tomorrow_prices: list[dict[str, Any]] = []
        tomorrow_available = False
        try:
            tomorrow_result = await self.client.async_get_prices_for_date(tomorrow)
            tomorrow_prices = self._filter_for_day(
                tomorrow_result.get("prices", []), tomorrow
            )
        except FrankClientError as err:
            _LOGGER.info("Tomorrow's prices are not available yet: %s", err)
            tomorrow_prices = []

        if tomorrow_prices:
            tomorrow_available = True
        else:
            _LOGGER.info("Tomorrow's prices not available yet")
            tomorrow_prices = []

        resolution_minutes = self._detect_resolution(today_prices or tomorrow_prices)
        current_price = self._determine_current_price(today_prices, now)

        return {
            "today": today_prices,
            "tomorrow": tomorrow_prices,
            "tomorrow_available": tomorrow_available,
            "current_price": current_price,
            "resolution_minutes": resolution_minutes,
            "last_update": now,
            "last_attempt": now,
        }

    @staticmethod
    def _filter_for_day(
        prices: list[dict[str, Any]], day: Any
    ) -> list[dict[str, Any]]:
        """Keep only blocks whose local start falls on the given calendar day."""
        result: list[dict[str, Any]] = []
        for block in prices:
            start = block.get("from")
            if isinstance(start, datetime) and dt_util.as_local(start).date() == day:
                result.append(block)
        return result


    @staticmethod
    def _detect_resolution(prices: list[dict[str, Any]]) -> int:
        """Detect the price resolution (15 or 60 minutes) from the data."""
        for price in prices:
            duration = price.get("duration_minutes")
            if isinstance(duration, int) and duration > 0:
                # Snap to the two supported resolutions.
                return 60 if duration >= 60 else 15
        return DEFAULT_RESOLUTION_MINUTES

    @staticmethod
    def _determine_current_price(
        prices: list[dict[str, Any]], now: datetime
    ) -> float | None:
        """Return the total price for the currently active time slot."""
        for price in prices:
            start = price.get("from")
            end = price.get("till")
            if isinstance(start, datetime) and isinstance(end, datetime):
                if start <= now < end:
                    return price.get("total_price_eur_kwh")
        return None

    # --- Helper methods ----------------------------------------------------

    @staticmethod
    def _min_by_total(
        prices: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Return the price block with the lowest total price."""
        valid = [
            p for p in prices if isinstance(p.get("total_price_eur_kwh"), (int, float))
        ]
        if not valid:
            return None
        return min(valid, key=lambda p: p["total_price_eur_kwh"])

    @staticmethod
    def _max_by_total(
        prices: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Return the price block with the highest total price."""
        valid = [
            p for p in prices if isinstance(p.get("total_price_eur_kwh"), (int, float))
        ]
        if not valid:
            return None
        return max(valid, key=lambda p: p["total_price_eur_kwh"])

    def _today(self) -> list[dict[str, Any]]:
        """Return today's price blocks."""
        return (self.data or {}).get("today", [])

    def _tomorrow(self) -> list[dict[str, Any]]:
        """Return tomorrow's price blocks."""
        return (self.data or {}).get("tomorrow", [])

    def get_cheapest_today(self) -> dict[str, Any] | None:
        """Return the cheapest price block for today."""
        return self._min_by_total(self._today())

    def get_most_expensive_today(self) -> dict[str, Any] | None:
        """Return the most expensive price block for today."""
        return self._max_by_total(self._today())

    def get_cheapest_tomorrow(self) -> dict[str, Any] | None:
        """Return the cheapest price block for tomorrow."""
        return self._min_by_total(self._tomorrow())

    def get_most_expensive_tomorrow(self) -> dict[str, Any] | None:
        """Return the most expensive price block for tomorrow."""
        return self._max_by_total(self._tomorrow())

    # --- Statistics helpers -----------------------------------------------

    @staticmethod
    def _totals(prices: list[dict[str, Any]]) -> list[float]:
        """Return the list of valid total prices."""
        return [
            p["total_price_eur_kwh"]
            for p in prices
            if isinstance(p.get("total_price_eur_kwh"), (int, float))
        ]

    @classmethod
    def average_price(cls, prices: list[dict[str, Any]]) -> float | None:
        """Return the average total price of the given blocks."""
        totals = cls._totals(prices)
        if not totals:
            return None
        return round(sum(totals) / len(totals), 6)

    @classmethod
    def min_price(cls, prices: list[dict[str, Any]]) -> float | None:
        """Return the lowest total price of the given blocks."""
        totals = cls._totals(prices)
        return min(totals) if totals else None

    @classmethod
    def max_price(cls, prices: list[dict[str, Any]]) -> float | None:
        """Return the highest total price of the given blocks."""
        totals = cls._totals(prices)
        return max(totals) if totals else None

