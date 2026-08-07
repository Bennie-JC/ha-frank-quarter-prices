"""DataUpdateCoordinator for the Frank Quarter Prices integration."""

from __future__ import annotations

import logging
from datetime import date as date_type
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    QUARTER_BOUNDARY_MINUTES,
    QUARTER_TICK_OFFSET_SECONDS,
    TOMORROW_ERROR_BACKOFF_MINUTES,
    TOMORROW_PUBLISH_HOUR,
)
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
        # Integration version (e.g. "0.1.1"), populated during setup and exposed
        # as the device ``sw_version``. Falls back to "unknown" if not set.
        self.integration_version: str = "unknown"

        # Published price blocks per local calendar day. Filled by the API and
        # then read locally: a day already held here is never requested again,
        # so the quarter ticks derive the active block from memory instead of
        # re-downloading two lists that change at most twice a day.
        self._prices_by_day: dict[date_type, list[dict[str, Any]]] = {}
        # Days whose cached list covers the complete local day. A day missing
        # from this set is still fetched again: a partial response stays usable
        # for the current cycle but must never freeze in for the rest of the day.
        self._complete_days: set[date_type] = set()
        # Consecutive tomorrow requests that failed with a transport/API error,
        # and when the last one happened. Used to back off a sustained outage
        # without delaying recovery from a single blip.
        self._tomorrow_errors = 0
        self._tomorrow_error_at: datetime | None = None

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            # No free-running interval: a plain ``timedelta`` interval starts
            # counting from config-entry setup, so it drifts out of sync with
            # the actual quarter-hour boundaries and the active price block
            # (and the today/tomorrow rollover) can lag behind by up to almost
            # 15 minutes. Refreshes are driven by the wall clock instead, via
            # the time-change listener registered below.
            update_interval=None,
        )

        entry.async_on_unload(
            async_track_time_change(
                hass,
                self._handle_quarter_tick,
                minute=list(QUARTER_BOUNDARY_MINUTES),
                second=QUARTER_TICK_OFFSET_SECONDS,
            )
        )

    async def _handle_quarter_tick(self, now: datetime) -> None:
        """Refresh right after each wall-clock quarter-hour boundary.

        Uses ``async_refresh`` rather than ``async_request_refresh``: the
        latter is debounced by a ~10s cooldown, which would reintroduce a
        window where the boundary has passed but the cached block is still
        the previous quarter's.
        """
        await self.async_refresh()

    async def _async_update_data(self) -> dict[str, Any]:
        """Derive the current state, fetching only the days that are missing.

        Fetching and deriving are deliberately separate. The published daily
        lists change at most twice a day, so they are cached per local calendar
        date and only requested when a complete list for that date is not held
        yet. Every other quarter tick is pure local arithmetic over the cache,
        which cannot fail and needs no network. A failed *optional* request
        therefore no longer takes every price entity to ``unavailable``.
        """
        now = dt_util.now()
        today = now.date()
        tomorrow = today + timedelta(days=1)

        self._purge_stale_days(today)

        # 1. Today. Only requested when no complete list is cached for it; the
        #    midnight rollover is normally free because the list was already
        #    fetched as "tomorrow" the previous afternoon. An update fails only
        #    when today is genuinely unobtainable — never merely because a
        #    refresh attempt failed while usable data is already held.
        today_prices = await self._async_ensure_today(today)

        # 2. Tomorrow. Optional by nature: not published before the afternoon,
        #    and a failure here must never invalidate today.
        tomorrow_prices = await self._async_ensure_tomorrow(tomorrow, now)
        tomorrow_available = bool(tomorrow_prices)
        if not tomorrow_available:
            _LOGGER.debug("Tomorrow's prices not available yet")

        resolution_minutes = self._detect_resolution(today_prices or tomorrow_prices)
        # Select the single active price block once and derive the current price
        # from it, so every current-price consumer (purchase and feed-in) shares
        # the exact same block without a second lookup or a second API request.
        current_price_block = self._determine_current_block(today_prices, now)
        current_price = (
            current_price_block.get("total_price_eur_kwh")
            if current_price_block is not None
            else None
        )

        _LOGGER.debug(
            "Update: today=%d blocks, tomorrow=%d blocks (available=%s), "
            "resolution=%d min",
            len(today_prices),
            len(tomorrow_prices),
            tomorrow_available,
            resolution_minutes,
        )

        return {
            "today": today_prices,
            "tomorrow": tomorrow_prices,
            "tomorrow_available": tomorrow_available,
            "current_price": current_price,
            "current_price_block": current_price_block,
            "resolution_minutes": resolution_minutes,
            "last_update": now,
            "last_attempt": now,
        }

    # --- Daily price cache -------------------------------------------------

    def _purge_stale_days(self, today: date_type) -> None:
        """Drop cached days that can no longer be reached.

        Only dates strictly before today are removed: tomorrow must survive so
        it can become today, free of charge, at the midnight rollover.
        """
        for day in [day for day in self._prices_by_day if day < today]:
            del self._prices_by_day[day]
            self._complete_days.discard(day)

    def _store_day(self, day: date_type, prices: list[dict[str, Any]]) -> None:
        """Cache a fetched day, keeping the best list seen for that date.

        A list covering the whole local day is cached as complete and is never
        requested again. Anything shorter is kept only as a working set: it
        still feeds the current cycle, it never replaces a complete list, and
        the day stays on the fetch list so the gaps can still fill in.

        Two partial lists are *merged* rather than one being chosen. Picking
        the longer list would discard a short fresh response covering the
        active quarter in favour of a long stale one that does not, which is
        the difference between a working current price and no current price at
        all. Merging can also complete a day that arrived in two pieces.
        """
        if self._covers_full_local_day(prices, day):
            self._prices_by_day[day] = prices
            self._complete_days.add(day)
            return

        if day in self._complete_days:
            _LOGGER.debug(
                "Keeping the complete cached list for %s; the API returned "
                "only %d block(s)",
                day.isoformat(),
                len(prices),
            )
            return

        if not prices:
            # An empty response teaches us nothing; keep what we already have.
            return

        merged = self._merge_blocks(self._prices_by_day.get(day, []), prices)
        self._prices_by_day[day] = merged
        if self._covers_full_local_day(merged, day):
            self._complete_days.add(day)

    @staticmethod
    def _merge_blocks(
        existing: list[dict[str, Any]], fresh: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Combine two partial lists for one day, newest winning per time slot.

        Slots are keyed on the absolute UTC start, so the repeated hour of the
        fall-back day stays two distinct blocks instead of collapsing into one.
        """
        if not existing:
            return fresh

        # A change of resolution means both lists describe the same hours with
        # different block boundaries; merging them would produce overlapping
        # blocks, so the fresher list wins outright.
        cls = FrankQuarterPricesCoordinator
        if cls._detect_resolution(existing) != cls._detect_resolution(fresh):
            return fresh

        by_start = {dt_util.as_utc(block["from"]): block for block in existing}
        by_start.update({dt_util.as_utc(block["from"]): block for block in fresh})
        return [by_start[start] for start in sorted(by_start)]

    @staticmethod
    def _covers_full_local_day(prices: list[dict[str, Any]], day: date_type) -> bool:
        """Return whether the blocks cover the complete local calendar day.

        Completeness is measured against the real local-midnight-to-local-
        midnight span rather than a fixed block count, so the 23-hour spring-
        forward day (92 quarters) and the 25-hour fall-back day (100 quarters)
        both validate correctly — as does an hourly fallback response.

        Sorting and comparison happen on absolute UTC instants. Local wall
        clock will not do: on the fall-back day 02:00-03:00 runs twice, and two
        same-zone datetimes differing only in ``fold`` compare equal, which
        both mis-sorts the repeated hour and lets a gap through unnoticed.
        """
        spans = sorted(
            (dt_util.as_utc(p["from"]), dt_util.as_utc(p["till"]))
            for p in prices
            if isinstance(p.get("from"), datetime)
            and isinstance(p.get("till"), datetime)
        )
        if not spans:
            return False

        cursor = dt_util.as_utc(dt_util.start_of_local_day(day))
        end = dt_util.as_utc(dt_util.start_of_local_day(day + timedelta(days=1)))
        for start, till in spans:
            # Any gap, overlap or duplicate breaks the chain, so a list with a
            # hole in it can never be mistaken for a complete day.
            if start != cursor:
                return False
            cursor = till
        return cursor == end

    async def _async_fetch_day(self, day: date_type) -> list[dict[str, Any]]:
        """Fetch and cache one calendar day, returning its blocks."""
        result = await self.client.async_get_prices_for_date(day)
        prices = self._filter_for_day(result.get("prices", []), day)
        self._store_day(day, prices)
        return self._prices_by_day.get(day, [])

    async def _async_ensure_today(self, day: date_type) -> list[dict[str, Any]]:
        """Return today's blocks, fetching only when they are missing.

        ``UpdateFailed`` is raised only when the fetch fails and nothing usable
        is cached for that day. When usable data *is* cached the failure is
        logged and the cached data is returned, so a transient blip cannot
        invalidate prices that are already known to be good.
        """
        if day in self._complete_days:
            return self._prices_by_day[day]

        try:
            return await self._async_fetch_day(day)
        except FrankClientError as err:
            cached = self._prices_by_day.get(day, [])
            if cached:
                _LOGGER.warning(
                    "Keeping the cached prices for %s; the Frank API request "
                    "failed: %s",
                    day.isoformat(),
                    err,
                )
                return cached
            if isinstance(err, FrankClientAuthError):
                raise UpdateFailed(f"Authentication error: {err}") from err
            raise UpdateFailed(f"Error communicating with Frank API: {err}") from err

    async def _async_ensure_tomorrow(
        self, tomorrow: date_type, now: datetime
    ) -> list[dict[str, Any]]:
        """Return tomorrow's blocks, requesting them only when it makes sense.

        Tomorrow is never requested before :data:`TOMORROW_PUBLISH_HOUR` (every
        earlier request is a guaranteed miss) and never requested again once a
        complete list is cached. A day that is simply not published yet is
        retried on the next quarter tick, as is a single failed request; only
        from the second consecutive failure is the next attempt held off for
        :data:`TOMORROW_ERROR_BACKOFF_MINUTES`. Failures are always non-fatal.
        """
        if tomorrow in self._complete_days:
            return self._prices_by_day[tomorrow]

        cached = self._prices_by_day.get(tomorrow, [])

        if now.hour < TOMORROW_PUBLISH_HOUR:
            return cached

        if self._in_tomorrow_error_backoff(now):
            return cached

        try:
            prices = await self._async_fetch_day(tomorrow)
        except FrankClientError as err:
            self._tomorrow_errors += 1
            self._tomorrow_error_at = now
            _LOGGER.info("Tomorrow's prices are not available yet: %s", err)
            return cached

        self._tomorrow_errors = 0
        self._tomorrow_error_at = None
        return prices

    def _in_tomorrow_error_backoff(self, now: datetime) -> bool:
        """Return whether the tomorrow request should be held off after errors."""
        if self._tomorrow_errors < 2 or self._tomorrow_error_at is None:
            return False
        elapsed = now - self._tomorrow_error_at
        # A backwards clock jump (the DST fall-back hour) must not park the
        # retry for an hour, so only a forward-running gap counts.
        if elapsed < timedelta(0):
            return False
        return elapsed < timedelta(minutes=TOMORROW_ERROR_BACKOFF_MINUTES)

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
    def _determine_current_block(
        prices: list[dict[str, Any]], now: datetime
    ) -> dict[str, Any] | None:
        """Return the price block for the currently active time slot."""
        for price in prices:
            start = price.get("from")
            end = price.get("till")
            if (
                isinstance(start, datetime)
                and isinstance(end, datetime)
                and start <= now < end
            ):
                return price
        return None

    @classmethod
    def _determine_current_price(
        cls, prices: list[dict[str, Any]], now: datetime
    ) -> float | None:
        """Return the total price for the currently active time slot."""
        block = cls._determine_current_block(prices, now)
        return block.get("total_price_eur_kwh") if block is not None else None

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

