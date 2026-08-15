"""Cheapest / most expensive contiguous window of an exact requested duration.

Like :mod:`.price` and :mod:`.price_zone` this module is intentionally free of
Home Assistant imports so the algorithm can be unit-tested in isolation, and it
performs **no** I/O: an optimal period is a pure local derivation over the day's
already-fetched price blocks, so the feature costs zero extra Frank API
requests.

Not the same thing as a price zone
----------------------------------

The v0.1.6 price zone answers::

    Which contiguous part of the day falls inside my cheap/expensive threshold?

An optimal period answers a different question entirely::

    Which exact X-minute contiguous window has the lowest/highest average price?

The two are independent by design. This module never reads a zone margin: the
window is selected from the actual prices and the requested duration alone, so
a 120-minute cheap period is the same window whether the cheap-zone margin is
0% or 49%. Conversely nothing here can move a zone boundary.

What makes a candidate valid
----------------------------

A candidate is a run of **whole source blocks** that is

* chronologically contiguous — ``next.from == previous.till`` compared as
  absolute UTC instants, so a gap, an overlap or the repeated hour of the
  fall-back day is judged on real time rather than on list position, and
* exactly ``duration_minutes`` of real elapsed time long, measured the same way.

Source blocks are never split, never merged and never interpolated. A requested
duration that no run of whole blocks can add up to — 90 minutes against an
hourly-fallback day, say — simply yields no result, which the entities surface
as ``unavailable``. Fabricating two 30-minute halves out of an hourly block
would invent prices Frank never published.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from .const import (
    CONF_OPTIMAL_CHEAP_DURATION_MINUTES,
    CONF_OPTIMAL_CHEAP_ENABLED,
    CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES,
    CONF_OPTIMAL_EXPENSIVE_ENABLED,
    DEFAULT_OPTIMAL_DURATION_MINUTES,
    DEFAULT_OPTIMAL_ENABLED,
    MAX_OPTIMAL_DURATION_MINUTES,
    MIN_OPTIMAL_DURATION_MINUTES,
    OPTIMAL_DURATION_STEP_MINUTES,
    OPTIMAL_MODE_CHEAP,
    OPTIMAL_MODE_EXPENSIVE,
)

# Price block key the windows are averaged over: the all-in consumer purchase
# price, the same field the price zones and the cheapest/most-expensive sensors
# compare on.
PRICE_FIELD: str = "total_price_eur_kwh"

# Precision used for the published and compared average price.
#
# The *same* rounded value both selects the winning window and is published as
# ``average_price_eur_kwh``, so a dashboard can never show two windows with an
# identical average and be unable to explain which one was chosen. It also
# stops float noise around 1e-17 from silently deciding a tie that should be
# resolved by the documented earliest-wins rule.
_PRICE_PRECISION = 6


def _as_number(value: Any) -> float | None:
    """Return ``value`` as a float, or ``None`` when it is not numeric.

    Booleans are rejected: ``True``/``False`` are ints in Python but never a
    valid price or duration.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _utc(value: datetime) -> datetime:
    """Return an aware datetime as an absolute UTC instant.

    Local wall clock will not do: on the fall-back day 02:00-03:00 runs twice
    and two same-zone datetimes differing only in ``fold`` compare equal, which
    would both mis-order the repeated hour and let a gap pass as contiguous.
    """
    return value.astimezone(timezone.utc)


def _elapsed_minutes(start: datetime, end: datetime) -> int:
    """Return the real elapsed minutes between two aware datetimes."""
    return int((_utc(end) - _utc(start)).total_seconds() // 60)


def validate_duration_minutes(value: Any) -> int | None:
    """Return a stored duration in whole minutes, or ``None`` when it is invalid.

    A **valid** duration is a whole number of minutes inside the supported range
    and on the supported step: ``15 <= value <= 720`` and ``value % 15 == 0``.
    Those are exactly the values the options form can produce, so any other
    stored value can only come from a hand-edited config entry or a corrupted
    ``.storage`` file.

    Such a value is **rejected**, never repaired. It is not clamped into range
    and not rounded onto the step, and — importantly — it does not fall back to
    the 120-minute default either. Silently planning a 120-minute window for
    someone whose configuration says ``-500`` would run an automation on a
    duration the user never asked for and never sees; the honest answer is that
    the configuration is unusable, which the entities surface as ``unavailable``
    and the coordinator logs once with the offending value.

    A *missing* key is a different thing entirely and is not handled here: that
    is ordinary backward compatibility, and the callers below answer it with the
    documented default.

    The step check costs nothing and only ever rejects durations that could not
    have worked anyway: every duration an hourly-fallback day can compose is a
    multiple of 60, and therefore also a multiple of 15. Rejecting them here
    turns a silently unavailable entity into a logged, explicable one.
    """
    number = _as_number(value)
    if number is None or not float(number).is_integer():
        return None
    minutes = int(number)
    if minutes < MIN_OPTIMAL_DURATION_MINUTES:
        return None
    if minutes > MAX_OPTIMAL_DURATION_MINUTES:
        return None
    if minutes % OPTIMAL_DURATION_STEP_MINUTES:
        return None
    return minutes


def _option(options: Mapping[str, Any] | None, key: str, default: Any) -> Any:
    """Return a raw option value, or ``default`` when it is absent."""
    if not isinstance(options, Mapping):
        return default
    return options.get(key, default)


def _duration(options: Mapping[str, Any] | None, key: str) -> int | None:
    """Return the effective duration for ``key``.

    Missing key -> the documented default (an entry from before this feature
    existed must keep working). Present but invalid -> ``None``, meaning "do not
    plan anything with this".
    """
    if not isinstance(options, Mapping) or key not in options:
        return DEFAULT_OPTIMAL_DURATION_MINUTES
    return validate_duration_minutes(options[key])


def get_optimal_cheap_enabled(options: Mapping[str, Any] | None) -> bool:
    """Return whether the optimal cheap period is enabled (default off).

    An entry created before this feature existed has no such key and therefore
    gains no planner entities without the user asking for them.
    """
    return bool(_option(options, CONF_OPTIMAL_CHEAP_ENABLED, DEFAULT_OPTIMAL_ENABLED))


def get_optimal_expensive_enabled(options: Mapping[str, Any] | None) -> bool:
    """Return whether the optimal expensive period is enabled (default off)."""
    return bool(
        _option(options, CONF_OPTIMAL_EXPENSIVE_ENABLED, DEFAULT_OPTIMAL_ENABLED)
    )


def get_optimal_cheap_duration_minutes(options: Mapping[str, Any] | None) -> int | None:
    """Return the cheap-period duration: 120 when unset, ``None`` when invalid."""
    return _duration(options, CONF_OPTIMAL_CHEAP_DURATION_MINUTES)


def get_optimal_expensive_duration_minutes(
    options: Mapping[str, Any] | None,
) -> int | None:
    """Return the expensive-period duration: 120 when unset, ``None`` if invalid."""
    return _duration(options, CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES)


def _usable_blocks(
    prices: Sequence[Mapping[str, Any]] | None,
) -> list[tuple[datetime, datetime, float, int]]:
    """Return ``(from, till, price, minutes)`` tuples, chronologically ordered.

    ``minutes`` is the block's *real* elapsed duration derived from its own
    timestamps, not the API's ``duration_minutes`` field: the elapsed time is
    what the requested window duration has to add up to, and it is the only one
    of the two that stays correct across a daylight-saving transition.

    Blocks without an aware interval or a numeric total price are skipped: they
    cannot take part in a contiguity chain and must never silently join two
    unrelated runs together.
    """
    usable: list[tuple[datetime, datetime, float, int]] = []
    if not isinstance(prices, Sequence):
        return usable

    for block in prices:
        if not isinstance(block, Mapping):
            continue
        start = block.get("from")
        till = block.get("till")
        price = _as_number(block.get(PRICE_FIELD))
        if (
            not isinstance(start, datetime)
            or not isinstance(till, datetime)
            or start.tzinfo is None
            or till.tzinfo is None
            or price is None
            or _utc(till) <= _utc(start)
        ):
            continue
        usable.append((start, till, price, _elapsed_minutes(start, till)))

    return sorted(usable, key=lambda item: _utc(item[0]))


def _contiguous_segments(
    blocks: list[tuple[datetime, datetime, float, int]],
) -> list[list[tuple[datetime, datetime, float, int]]]:
    """Split the day into runs of blocks that really touch each other.

    Splitting first is what keeps the sliding window below honest: a window can
    then never span a gap or an overlap, because a break in the chain starts a
    new segment that the window is not allowed to reach back across.
    """
    segments: list[list[tuple[datetime, datetime, float, int]]] = []
    current: list[tuple[datetime, datetime, float, int]] = []

    for block in blocks:
        if current and _utc(block[0]) != _utc(current[-1][1]):
            segments.append(current)
            current = [block]
        else:
            current.append(block)
    if current:
        segments.append(current)

    return segments


def calculate_optimal_period(
    prices: Sequence[Mapping[str, Any]] | None,
    duration_minutes: int,
    mode: str,
) -> dict[str, Any] | None:
    """Return the cheapest or most expensive window of exactly that duration.

    ``mode`` is :data:`~.const.OPTIMAL_MODE_CHEAP` or
    :data:`~.const.OPTIMAL_MODE_EXPENSIVE`. Every contiguous run of whole source
    blocks whose real elapsed duration equals ``duration_minutes`` exactly is a
    candidate; each is scored on its duration-weighted average price::

        average = sum(price_i * minutes_i) / sum(minutes_i)

    For the ordinary day of equal 15-minute blocks that is the plain arithmetic
    mean, but the weighting is applied anyway so an hourly-fallback day — or a
    day that mixes resolutions — is scored correctly rather than letting a
    single 60-minute block count for as much as one quarter.

    Cheap mode takes the lowest average, expensive mode the highest. Prices are
    used exactly as published: never clamped, never made absolute. A negative
    price is simply a low one, so a cheap window naturally prefers the most
    negative average, and on an all-negative day the expensive window is the
    least negative one.

    Ties are resolved to the **earliest** window, for both modes: candidates are
    generated in chronological order and a later one must be *strictly* better
    to take over. That is what makes a perfectly flat day meaningful here — every
    candidate scores the same, so the first valid window wins — even though the
    same flat day yields no price *zone* at all, there being no cheap-versus-
    expensive distinction to draw.

    Returns ``None`` when no candidate exists: an empty or unusable list, a
    duration longer than the day, or a duration no run of whole blocks can add
    up to (90 minutes against hourly data, for instance).

    Complexity is O(n) in the number of blocks — each block is added to and
    removed from the sliding window at most once — so a 100-block day costs a
    single linear pass.
    """
    if mode not in (OPTIMAL_MODE_CHEAP, OPTIMAL_MODE_EXPENSIVE):
        raise ValueError(f"Unknown optimal-period mode: {mode!r}")

    duration = _as_number(duration_minutes)
    if duration is None or duration <= 0:
        return None
    target = int(duration)

    prefer_lower = mode == OPTIMAL_MODE_CHEAP
    best: dict[str, Any] | None = None
    best_average: float | None = None

    for segment in _contiguous_segments(_usable_blocks(prices)):
        first = 0
        total_minutes = 0
        weighted_sum = 0.0

        for last, (_start, _till, price, minutes) in enumerate(segment):
            total_minutes += minutes
            weighted_sum += price * minutes

            # Shrink from the left until the window is no longer too long. The
            # left edge only ever moves forward, which is what keeps the pass
            # linear and the candidates chronological.
            while total_minutes > target and first <= last:
                _, _, dropped_price, dropped_minutes = segment[first]
                total_minutes -= dropped_minutes
                weighted_sum -= dropped_price * dropped_minutes
                first += 1

            if total_minutes != target:
                continue

            average = round(weighted_sum / total_minutes, _PRICE_PRECISION)
            if best_average is not None and not (
                average < best_average if prefer_lower else average > best_average
            ):
                # Not strictly better than the incumbent, so the earlier window
                # keeps it: equal averages resolve to the earliest period.
                continue

            best_average = average
            best = _describe(segment[first : last + 1], average, mode)

    return best


def _describe(
    window: list[tuple[datetime, datetime, float, int]],
    average: float,
    mode: str,
) -> dict[str, Any]:
    """Return the published description of one selected window.

    Deliberately compact. The full daily price array already travels on
    ``sensor.frank_prices_today``/``_tomorrow``; repeating it on every planner
    entity would bloat the state machine and push these entities over the
    Recorder attribute-size limit for no benefit.
    """
    prices = [price for _, _, price, _ in window]
    return {
        "mode": mode,
        "start": window[0][0],
        "end": window[-1][1],
        "duration_minutes": sum(minutes for _, _, _, minutes in window),
        "average_price_eur_kwh": average,
        "min_price_eur_kwh": min(prices),
        "max_price_eur_kwh": max(prices),
        "block_count": len(window),
        # The source resolution the window is built from. Every real day has
        # one resolution throughout; the minimum is reported so a hypothetical
        # mixed day still names the finest block it had to work with.
        "resolution_minutes": min(minutes for _, _, _, minutes in window),
    }


def is_within_period(period: Mapping[str, Any] | None, moment: datetime) -> bool | None:
    """Return whether ``moment`` falls inside ``period``.

    The boundary rule is ``start <= moment < end``, matching the price-zone
    period sensors and the coordinator's active-block selection: the period ends
    precisely at its final block's ``till``.

    All three values are converted to UTC first. Comparing the aware datetimes
    directly is *not* equivalent: CPython short-circuits ``<`` between two
    datetimes sharing the same ``tzinfo`` object to a naive wall-clock
    comparison that ignores ``fold``, and ``ZoneInfo`` is cached per key, so a
    period boundary and ``dt_util.now()`` always share one object. A boundary
    inside the repeated 02:00-03:00 hour of the fall-back day would otherwise
    make the sensor switch an hour early and flap on/off/on.

    Returns ``None`` when there is no usable period, which the binary sensors
    surface as ``unavailable``.
    """
    if not isinstance(period, Mapping):
        return None
    start = period.get("start")
    end = period.get("end")
    if (
        not isinstance(start, datetime)
        or not isinstance(end, datetime)
        or start.tzinfo is None
        or end.tzinfo is None
        or moment.tzinfo is None
    ):
        return None
    return _utc(start) <= _utc(moment) < _utc(end)
