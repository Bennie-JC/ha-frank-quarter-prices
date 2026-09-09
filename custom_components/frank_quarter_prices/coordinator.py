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
    CONF_OPTIMAL_CHEAP_DURATION_MINUTES,
    CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES,
    DEFAULT_COUNTRY,
    DOMAIN,
    MAX_OPTIMAL_DURATION_MINUTES,
    MIN_OPTIMAL_DURATION_MINUTES,
    OPTIMAL_DURATION_STEP_MINUTES,
    OPTIMAL_MODE_CHEAP,
    OPTIMAL_MODE_EXPENSIVE,
    QUARTER_BOUNDARY_MINUTES,
    QUARTER_TICK_OFFSET_SECONDS,
    TOMORROW_ERROR_BACKOFF_MINUTES,
    TOMORROW_PUBLISH_HOUR,
)
from .frank_client import FrankClient, FrankClientAuthError, FrankClientError
from .market_time import market_date_of, market_day_bounds, market_now
from .optimal_period import (
    calculate_optimal_period,
    get_optimal_cheap_duration_minutes,
    get_optimal_cheap_enabled,
    get_optimal_expensive_duration_minutes,
    get_optimal_expensive_enabled,
)
from .price import calculate_dynamic_price
from .price_zone import (
    calculate_price_zones,
    get_cheap_zone_margin_percent,
    get_expensive_zone_margin_percent,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

# Default resolution to assume when it cannot be derived from the data.
DEFAULT_RESOLUTION_MINUTES = 15


def _zone_summary(zone: dict[str, Any] | None) -> str:
    """Render a zone compactly for the debug log."""
    if not zone:
        return "none"
    return (
        f"{dt_util.as_local(zone['start']):%H:%M}-{dt_util.as_local(zone['end']):%H:%M}"
        f" (threshold {zone['threshold_eur_kwh']} @ {zone['margin_percent']}%)"
    )


def _period_summary(period: dict[str, Any] | None) -> str:
    """Render an optimal period compactly for the debug log."""
    if not period:
        return "none"
    return (
        f"{dt_util.as_local(period['start']):%H:%M}"
        f"-{dt_util.as_local(period['end']):%H:%M}"
        f" ({period['duration_minutes']} min @ {period['average_price_eur_kwh']})"
    )


class FrankQuarterPricesCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate fetching of Frank quarter prices."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: FrankClient,
        country: str = DEFAULT_COUNTRY,
    ) -> None:
        """Initialize the coordinator."""
        self.client = client
        self.entry = entry
        # The market whose calendar day Frank publishes. Every "which day is
        # this" decision below is made in this timezone, never in Home
        # Assistant's — see :mod:`.market_time`.
        self.country = country
        # Integration version (e.g. "0.1.1"), populated during setup and exposed
        # as the device ``sw_version``. Falls back to "unknown" if not set.
        self.integration_version: str = "unknown"

        # Published price blocks per *market* calendar day. Filled by the API and
        # then read locally: a day already held here is never requested again,
        # so the quarter ticks derive the active block from memory instead of
        # re-downloading two lists that change at most twice a day.
        self._prices_by_day: dict[date_type, list[dict[str, Any]]] = {}
        # Days whose cached list covers the complete market day. A day missing
        # from this set is still fetched again: a partial response stays usable
        # for the current cycle but must never freeze in for the rest of the day.
        self._complete_days: set[date_type] = set()
        # Consecutive tomorrow requests that failed with a transport/API error,
        # and when the last one happened. Used to back off a sustained outage
        # without delaying recovery from a single blip.
        self._tomorrow_errors = 0
        self._tomorrow_error_at: datetime | None = None
        # Unusable optimal-period durations already reported. A list rather
        # than a set because a stored value may be unhashable.
        self._warned_durations: list[Any] = []

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
        # Market time, not Home Assistant time: these three values decide which
        # days are fetched, cached and published, and they must match the day
        # Frank actually publishes regardless of how Home Assistant is set up.
        now = market_now(self.country)
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
        # Frank's "marktprijs+" basis (market price + sourcing markup), which is
        # what Frank bills as "het dynamische deel" -- not the all-in price. The
        # all-in price stays available on the block as ``total_price_eur_kwh`` and
        # is what every other price entity (cheapest/most expensive, the daily
        # arrays, the zones and the optimal periods) still uses.
        current_price = calculate_dynamic_price(current_price_block)

        # Derive today's price zones once per update, here, so the four zone
        # sensors and the two period binary sensors all read one shared result
        # and can never disagree. This is pure local arithmetic over the blocks
        # already held above: no request, no second cache, no second scheduler.
        #
        # A zone claims to describe the *whole* local day: "the cheapest stretch
        # of today". Deriving one from a partial list would silently answer a
        # different question — the cheapest stretch of the part that happens to
        # have arrived — and an EMS could charge on it at what is really an
        # expensive hour. So the zones are gated on the coordinator's own
        # authoritative completeness set (see ``_covers_full_market_day``) rather
        # than on a second, weaker notion of "enough data". No complete day, no
        # zone: the six zone entities go unavailable instead of misleading.
        cheap_zone: dict[str, Any] | None = None
        expensive_zone: dict[str, Any] | None = None
        if today in self._complete_days:
            cheap_zone, expensive_zone = calculate_price_zones(
                today_prices,
                get_cheap_zone_margin_percent(self.entry.options),
                get_expensive_zone_margin_percent(self.entry.options),
            )
        elif today_prices:
            _LOGGER.debug(
                "Today is incomplete (%d block(s)); publishing no price zones",
                len(today_prices),
            )

        # Derive the enabled optimal periods once per update too, from the same
        # already-fetched blocks. Each enabled period is calculated exactly once
        # here — never once per entity — so the today/tomorrow sensors and the
        # matching binary sensor always describe the identical window.
        optimal = self._derive_optimal_periods(
            today_prices, tomorrow_prices, today, tomorrow
        )

        _LOGGER.debug(
            "Update: today=%d blocks, tomorrow=%d blocks (available=%s), "
            "resolution=%d min, cheap_zone=%s, expensive_zone=%s, "
            "optimal_cheap=%s, optimal_expensive=%s",
            len(today_prices),
            len(tomorrow_prices),
            tomorrow_available,
            resolution_minutes,
            _zone_summary(cheap_zone),
            _zone_summary(expensive_zone),
            _period_summary(optimal["optimal_cheap_today"]),
            _period_summary(optimal["optimal_expensive_today"]),
        )

        return {
            "today": today_prices,
            "tomorrow": tomorrow_prices,
            "tomorrow_available": tomorrow_available,
            "current_price": current_price,
            "current_price_block": current_price_block,
            "resolution_minutes": resolution_minutes,
            "cheap_zone": cheap_zone,
            "expensive_zone": expensive_zone,
            **optimal,
            "last_update": now,
            "last_attempt": now,
        }

    # --- Optimal periods ---------------------------------------------------

    def _warn_invalid_duration(self, conf_key: str, value: Any) -> None:
        """Log an unusable configured duration, once per distinct value.

        The coordinator updates every quarter, so logging unconditionally would
        put the same warning in the log ~96 times a day. Warning once per
        offending value still surfaces it, and a corrected value is reported
        again if it is still wrong.
        """
        if value in self._warned_durations:
            return
        self._warned_durations.append(value)
        _LOGGER.warning(
            "Ignoring the configured %s value %r: a duration must be a whole "
            "number of minutes between %d and %d in steps of %d. The matching "
            "optimal-period entities stay unavailable until it is corrected "
            "under Settings > Devices & Services > Frank Quarter Prices > "
            "Configure",
            conf_key,
            value,
            MIN_OPTIMAL_DURATION_MINUTES,
            MAX_OPTIMAL_DURATION_MINUTES,
            OPTIMAL_DURATION_STEP_MINUTES,
        )

    def _derive_optimal_periods(
        self,
        today_prices: list[dict[str, Any]],
        tomorrow_prices: list[dict[str, Any]],
        today: date_type,
        tomorrow: date_type,
    ) -> dict[str, dict[str, Any] | None]:
        """Derive the enabled optimal periods for today and tomorrow.

        Pure local arithmetic over the blocks already held: no request, no
        second cache, no second scheduler. A disabled feature is not calculated
        at all, and its keys stay ``None``.

        Gated on the coordinator's own authoritative completeness set for the
        same reason the price zones are: "the cheapest four hours of the day"
        derived from a 20-block morning would silently answer "the cheapest four
        hours of whatever has arrived so far", and an EMS acting on it could
        charge straight through the real evening peak. No complete day, no
        period.

        The zone margins are deliberately not consulted here. An optimal period
        is a function of the actual prices and the requested duration only.

        A stored duration that is not a usable one (only reachable by editing
        the config entry by hand, since the options form cannot produce it)
        yields no period at all rather than a window of some substituted length.
        It is logged once per offending value so the cause is visible, instead
        of an entity that is quietly unavailable forever.
        """
        options = self.entry.options
        result: dict[str, dict[str, Any] | None] = {
            "optimal_cheap_today": None,
            "optimal_cheap_tomorrow": None,
            "optimal_expensive_today": None,
            "optimal_expensive_tomorrow": None,
        }

        for enabled, duration, mode, key, conf_key in (
            (
                get_optimal_cheap_enabled(options),
                get_optimal_cheap_duration_minutes(options),
                OPTIMAL_MODE_CHEAP,
                "optimal_cheap",
                CONF_OPTIMAL_CHEAP_DURATION_MINUTES,
            ),
            (
                get_optimal_expensive_enabled(options),
                get_optimal_expensive_duration_minutes(options),
                OPTIMAL_MODE_EXPENSIVE,
                "optimal_expensive",
                CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES,
            ),
        ):
            if not enabled:
                continue
            if duration is None:
                self._warn_invalid_duration(conf_key, options.get(conf_key))
                continue
            if today in self._complete_days:
                result[f"{key}_today"] = calculate_optimal_period(
                    today_prices, duration, mode
                )
            if tomorrow in self._complete_days:
                result[f"{key}_tomorrow"] = calculate_optimal_period(
                    tomorrow_prices, duration, mode
                )

        return result

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
        if self._covers_full_market_day(prices, day):
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
        if self._covers_full_market_day(merged, day):
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

    def _covers_full_market_day(
        self, prices: list[dict[str, Any]], day: date_type
    ) -> bool:
        """Return whether the blocks cover the complete *market* calendar day.

        Completeness is measured against the real market-midnight-to-market-
        midnight span rather than a fixed block count, so the 23-hour spring-
        forward day (92 quarters) and the 25-hour fall-back day (100 quarters)
        both validate correctly — as does an hourly fallback response.

        The span comes from the market's timezone, never Home Assistant's. A
        Home Assistant configured in UTC would otherwise measure a Dutch day
        against UTC midnights, find every day two hours short, and never accept
        one as complete.

        Sorting and comparison happen on absolute UTC instants. Wall clock will
        not do: on the fall-back day 02:00-03:00 runs twice, and two same-zone
        datetimes differing only in ``fold`` compare equal, which both mis-sorts
        the repeated hour and lets a gap through unnoticed.
        """
        spans = sorted(
            (dt_util.as_utc(p["from"]), dt_util.as_utc(p["till"]))
            for p in prices
            if isinstance(p.get("from"), datetime)
            and isinstance(p.get("till"), datetime)
        )
        if not spans:
            return False

        day_start, day_end = market_day_bounds(day, self.country)
        cursor = dt_util.as_utc(day_start)
        end = dt_util.as_utc(day_end)
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
        # Absolute instants again: subtracting two datetimes that share one
        # ``tzinfo`` object yields the naive wall-clock delta, which is off by
        # an hour in both directions across a daylight-saving transition.
        elapsed = dt_util.as_utc(now) - dt_util.as_utc(self._tomorrow_error_at)
        # A backwards clock jump (the DST fall-back hour) must not park the
        # retry for an hour, so only a forward-running gap counts.
        if elapsed < timedelta(0):
            return False
        return elapsed < timedelta(minutes=TOMORROW_ERROR_BACKOFF_MINUTES)

    def _filter_for_day(
        self, prices: list[dict[str, Any]], day: Any
    ) -> list[dict[str, Any]]:
        """Keep only blocks whose *market* start falls on the given day.

        Grouping on Home Assistant's local date instead would move blocks into
        the wrong day for any installation that is not on market time, silently
        shifting the whole today/tomorrow split.
        """
        result: list[dict[str, Any]] = []
        for block in prices:
            start = block.get("from")
            if (
                isinstance(start, datetime)
                and market_date_of(start, self.country) == day
            ):
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
        """Return the price block for the currently active time slot.

        Compared on absolute UTC instants. Comparing the aware datetimes
        directly is not equivalent: CPython short-circuits ``<`` between two
        datetimes that share the *same* ``tzinfo`` object to a naive wall-clock
        comparison that ignores ``fold`` — and ``ZoneInfo`` is cached per key,
        so market blocks and a market-time ``now`` always share one object. On
        the fall-back day 02:00-03:00 runs twice, both passes compare equal,
        and the first-pass block would be returned for the whole second hour.
        """
        now_utc = dt_util.as_utc(now)
        for price in prices:
            start = price.get("from")
            end = price.get("till")
            if (
                isinstance(start, datetime)
                and isinstance(end, datetime)
                and dt_util.as_utc(start) <= now_utc < dt_util.as_utc(end)
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

    # --- Price zones -------------------------------------------------------
    #
    # Both zones are calculated once per coordinator update (see
    # ``_async_update_data``). These accessors only hand out that one shared
    # result, so every zone entity is guaranteed to describe the same window.

    def get_cheap_zone(self) -> dict[str, Any] | None:
        """Return today's cheap price zone, or None when it is unknown."""
        return (self.data or {}).get("cheap_zone")

    def get_expensive_zone(self) -> dict[str, Any] | None:
        """Return today's expensive price zone, or None when it is unknown."""
        return (self.data or {}).get("expensive_zone")

    # --- Optimal periods ---------------------------------------------------
    #
    # Each enabled period is calculated once per coordinator update (see
    # ``_derive_optimal_periods``). These accessors only hand out that one
    # shared result, so the sensor and the binary sensor describing the same
    # period can never disagree.

    def get_optimal_cheap_today(self) -> dict[str, Any] | None:
        """Return today's optimal cheap period, or None when unavailable."""
        return (self.data or {}).get("optimal_cheap_today")

    def get_optimal_cheap_tomorrow(self) -> dict[str, Any] | None:
        """Return tomorrow's optimal cheap period, or None when unavailable."""
        return (self.data or {}).get("optimal_cheap_tomorrow")

    def get_optimal_expensive_today(self) -> dict[str, Any] | None:
        """Return today's optimal expensive period, or None when unavailable."""
        return (self.data or {}).get("optimal_expensive_today")

    def get_optimal_expensive_tomorrow(self) -> dict[str, Any] | None:
        """Return tomorrow's optimal expensive period, or None when unavailable."""
        return (self.data or {}).get("optimal_expensive_tomorrow")

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

