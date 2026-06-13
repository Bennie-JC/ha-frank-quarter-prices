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
        # Cache of the last successfully fetched tomorrow prices.
        self._last_tomorrow: list[dict[str, Any]] = []

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch today's and tomorrow's quarter prices from the Frank API."""
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

        today_prices: list[dict[str, Any]] = today_result.get("prices", [])

        # 2. Always attempt tomorrow. Failures here are non-fatal.
        tomorrow_prices: list[dict[str, Any]] = []
        tomorrow_available = False
        try:
            tomorrow_result = await self.client.async_get_prices_for_date(tomorrow)
            tomorrow_prices = tomorrow_result.get("prices", [])
        except FrankClientError as err:
            # Tomorrow's prices may not be published yet (typically before ~15:00).
            _LOGGER.info("Tomorrow's prices are not available yet: %s", err)
            tomorrow_prices = []

        if tomorrow_prices:
            tomorrow_available = True
            self._last_tomorrow = tomorrow_prices
        else:
            # 3. Keep last valid tomorrow data if we have it, else empty list.
            if self._last_tomorrow:
                _LOGGER.info(
                    "Tomorrow's prices unavailable; keeping last known values"
                )
                tomorrow_prices = self._last_tomorrow
            else:
                _LOGGER.info("Tomorrow's prices unavailable; using empty list")
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
        }

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

    def get_cheapest_next_48h(self) -> dict[str, Any] | None:
        """Return the cheapest price block across today and tomorrow."""
        return self._min_by_total(self._today() + self._tomorrow())

    def get_most_expensive_next_48h(self) -> dict[str, Any] | None:
        """Return the most expensive price block across today and tomorrow."""
        return self._max_by_total(self._today() + self._tomorrow())

    # --- Future-window helpers --------------------------------------------

    def _all_blocks(self) -> list[dict[str, Any]]:
        """Return today's and tomorrow's blocks sorted by start time."""
        blocks = self._today() + self._tomorrow()
        return sorted(
            (b for b in blocks if isinstance(b.get("from"), datetime)),
            key=lambda b: b["from"],
        )

    def _future_blocks(self, hours: int) -> list[dict[str, Any]]:
        """Return blocks active from now until ``now + hours``."""
        now = dt_util.now()
        end = now + timedelta(hours=hours)
        result: list[dict[str, Any]] = []
        for block in self._all_blocks():
            start = block.get("from")
            till = block.get("till")
            if not isinstance(start, datetime) or not isinstance(till, datetime):
                continue
            # Include blocks that are currently active or start within the window.
            if till > now and start < end:
                result.append(block)
        return result

    def get_cheapest_next_24h(self) -> dict[str, Any] | None:
        """Return the cheapest block in the next 24 hours from now."""
        return self._min_by_total(self._future_blocks(24))

    def get_most_expensive_next_24h(self) -> dict[str, Any] | None:
        """Return the most expensive block in the next 24 hours from now."""
        return self._max_by_total(self._future_blocks(24))

    # --- ApexCharts helpers -----------------------------------------------

    @staticmethod
    def _to_apex_series(blocks: list[dict[str, Any]]) -> list[list[Any]]:
        """Convert price blocks into ``[timestamp_ms, price]`` pairs."""
        series: list[list[Any]] = []
        for block in blocks:
            start = block.get("from")
            price = block.get("total_price_eur_kwh")
            if isinstance(start, datetime) and isinstance(price, (int, float)):
                series.append([int(start.timestamp() * 1000), price])
        return series

    def _aggregate_hourly(
        self, blocks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Aggregate sub-hourly blocks into hourly average price blocks.

        If the source data is already hourly, it is returned unchanged.
        """
        if self.resolution_minutes >= 60:
            return blocks

        buckets: dict[datetime, list[float]] = {}
        for block in blocks:
            start = block.get("from")
            price = block.get("total_price_eur_kwh")
            if not isinstance(start, datetime) or not isinstance(price, (int, float)):
                continue
            hour = start.replace(minute=0, second=0, microsecond=0)
            buckets.setdefault(hour, []).append(price)

        aggregated: list[dict[str, Any]] = []
        for hour in sorted(buckets):
            prices = buckets[hour]
            aggregated.append(
                {
                    "from": hour,
                    "till": hour + timedelta(hours=1),
                    "total_price_eur_kwh": round(sum(prices) / len(prices), 6),
                }
            )
        return aggregated

    @property
    def resolution_minutes(self) -> int:
        """Return the detected resolution in minutes."""
        return (self.data or {}).get("resolution_minutes", DEFAULT_RESOLUTION_MINUTES)

    def get_apex_24h_quarter(self) -> list[list[Any]]:
        """Return the next 24h of price blocks at the source resolution."""
        return self._to_apex_series(self._future_blocks(24))

    def get_apex_48h_quarter(self) -> list[list[Any]]:
        """Return the next 48h of price blocks at the source resolution."""
        return self._to_apex_series(self._future_blocks(48))

    def get_apex_24h_hourly(self) -> list[list[Any]]:
        """Return the next 24h of price blocks aggregated to hourly averages."""
        return self._to_apex_series(self._aggregate_hourly(self._future_blocks(24)))

    def get_apex_48h_hourly(self) -> list[list[Any]]:
        """Return the next 48h of price blocks aggregated to hourly averages."""
        return self._to_apex_series(self._aggregate_hourly(self._future_blocks(48)))
