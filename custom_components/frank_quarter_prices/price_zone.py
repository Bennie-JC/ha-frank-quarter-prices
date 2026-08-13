"""Daily cheap/expensive price-zone derivation.

Like :mod:`.price` this module is intentionally free of Home Assistant imports
so the algorithm can be unit-tested in isolation. It performs **no** I/O: a zone
is a pure local derivation over the day's already-fetched quarter-price blocks,
so adding the zone entities costs zero extra Frank API requests.

A zone is the **longest chronologically contiguous run** of qualifying quarters,
not simply "first qualifying quarter until last qualifying quarter". A single
cheap quarter at 03:00 must not bridge into an unrelated cheap stretch at
12:30–15:15; the zone is the 12:30–15:15 run alone.

Contiguity is decided on the blocks' real ``from``/``till`` timestamps compared
as **absolute instants** (``next.from == previous.till``), never on list
position and never on a fixed block count. That keeps the derivation correct on
the 92-quarter spring-forward day, the 96-quarter normal day, the 100-quarter
fall-back day — where 02:00–03:00 local runs twice — and on an hourly fallback
response.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from .const import (
    CONF_CHEAP_ZONE_MARGIN_PERCENT,
    CONF_EXPENSIVE_ZONE_MARGIN_PERCENT,
    DEFAULT_ZONE_MARGIN_PERCENT,
    MAX_ZONE_MARGIN_PERCENT,
    MIN_ZONE_MARGIN_PERCENT,
    ZONE_MODE_CHEAP,
    ZONE_MODE_EXPENSIVE,
)

# Price block key the zones are derived from: the all-in consumer purchase
# price, the same field the cheapest/most-expensive sensors compare on.
PRICE_FIELD: str = "total_price_eur_kwh"

# Precision used for the published threshold. Price blocks are already rounded
# to six decimals by the client, so rounding the threshold to the same precision
# keeps the value that selects the quarters identical to the value published in
# the ``threshold_eur_kwh`` attribute and shown on a dashboard.
_PRICE_PRECISION = 6


def _as_number(value: Any) -> float | None:
    """Return ``value`` as a float, or ``None`` when it is not numeric.

    Booleans are rejected: ``True``/``False`` are ints in Python but never a
    valid price or percentage.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _utc(value: datetime) -> datetime:
    """Return an aware datetime as an absolute UTC instant.

    Local wall clock will not do: on the fall-back day 02:00–03:00 runs twice
    and two same-zone datetimes differing only in ``fold`` compare equal, which
    would both mis-order the repeated hour and let a gap pass as contiguous.
    """
    return value.astimezone(timezone.utc)


def _elapsed_minutes(start: datetime, end: datetime) -> int:
    """Return the real elapsed minutes between two aware datetimes."""
    return int((_utc(end) - _utc(start)).total_seconds() // 60)


def clamp_margin_percent(value: Any) -> float:
    """Return a usable margin percentage, clamped into the supported range.

    A value that is missing or non-numeric falls back to the default; a value
    outside the supported range is clamped rather than rejected, so a hand-
    edited config entry can never produce a nonsensical zone.
    """
    number = _as_number(value)
    if number is None:
        return DEFAULT_ZONE_MARGIN_PERCENT
    return min(max(number, MIN_ZONE_MARGIN_PERCENT), MAX_ZONE_MARGIN_PERCENT)


def _zone_margin(options: Mapping[str, Any] | None, key: str) -> float:
    """Return the configured margin for ``key``, defaulting to 15%."""
    if not isinstance(options, Mapping):
        return DEFAULT_ZONE_MARGIN_PERCENT
    if key not in options:
        return DEFAULT_ZONE_MARGIN_PERCENT
    return clamp_margin_percent(options[key])


def get_cheap_zone_margin_percent(options: Mapping[str, Any] | None) -> float:
    """Return the configured cheap-zone margin, defaulting to 15%.

    Accepts a config entry's ``options`` mapping. An entry created before
    v0.1.6 has no such key and therefore keeps the 15% default without any
    migration or reconfiguration.
    """
    return _zone_margin(options, CONF_CHEAP_ZONE_MARGIN_PERCENT)


def get_expensive_zone_margin_percent(options: Mapping[str, Any] | None) -> float:
    """Return the configured expensive-zone margin, defaulting to 15%."""
    return _zone_margin(options, CONF_EXPENSIVE_ZONE_MARGIN_PERCENT)


def _usable_blocks(
    prices: Sequence[Mapping[str, Any]] | None,
) -> list[tuple[datetime, datetime, float]]:
    """Return ``(from, till, price)`` triples, chronologically ordered.

    Blocks without an aware interval or a numeric total price are skipped: they
    cannot take part in a contiguity chain and must never silently join two
    unrelated runs together.
    """
    usable: list[tuple[datetime, datetime, float]] = []
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
        usable.append((start, till, price))

    return sorted(usable, key=lambda item: _utc(item[0]))


def _longest_contiguous_run(
    blocks: list[tuple[datetime, datetime, float]],
    qualifies: Any,
) -> list[tuple[datetime, datetime, float]]:
    """Return the longest contiguous run of qualifying blocks.

    Runs are compared on real elapsed duration. Because the blocks are walked
    chronologically and a later run must be *strictly* longer to replace the
    incumbent, two equally long runs resolve to the **earliest** one.
    """
    best: list[tuple[datetime, datetime, float]] = []
    best_duration = -1
    current: list[tuple[datetime, datetime, float]] = []

    def consider(run: list[tuple[datetime, datetime, float]]) -> None:
        nonlocal best, best_duration
        if not run:
            return
        duration = _elapsed_minutes(run[0][0], run[-1][1])
        if duration > best_duration:
            best, best_duration = run, duration

    for block in blocks:
        if not qualifies(block[2]):
            consider(current)
            current = []
            continue
        if current and _utc(block[0]) != _utc(current[-1][1]):
            # A gap (or an overlap) ends the run; this block starts a new one.
            consider(current)
            current = [block]
        else:
            current.append(block)
    consider(current)

    return best


def calculate_price_zone(
    prices: Sequence[Mapping[str, Any]] | None,
    mode: str,
    margin_percent: float,
) -> dict[str, Any] | None:
    """Derive the cheap or expensive price zone for one day of blocks.

    ``mode`` is :data:`~.const.ZONE_MODE_CHEAP` or
    :data:`~.const.ZONE_MODE_EXPENSIVE`. The margin is a percentage of the day's
    own price **range**, measured inward from the respective extreme::

        daily_spread        = day_max - day_min
        cheap_threshold     = day_min + daily_spread * margin_percent / 100
        expensive_threshold = day_max - daily_spread * margin_percent / 100

    A quarter qualifies when ``price <= cheap_threshold`` respectively
    ``price >= expensive_threshold``.

    The spread is what makes this safe. Applying the percentage to the absolute
    all-in price instead lets the fixed energy-tax and markup floor (~0.129
    EUR/kWh, unrelated to the market) set the band width, so on a flat day both
    bands can span the whole range and a quarter is reported as cheap *and*
    expensive at once.

    Returns ``None`` when the day holds no usable block, and also when the day
    is perfectly flat (``day_max == day_min``): there is then no cheap-versus-
    expensive distinction to draw, and labelling every quarter as both would be
    worse than saying nothing. Prefer :func:`calculate_price_zones`, which
    derives both zones together and enforces the no-overlap invariant.
    """
    blocks = _usable_blocks(prices)
    if not blocks:
        return None

    totals = [price for _, _, price in blocks]
    day_min = min(totals)
    day_max = max(totals)
    spread = day_max - day_min
    if spread <= 0:
        # A perfectly flat day. Every quarter is simultaneously the cheapest and
        # the most expensive, so neither zone means anything.
        return None

    margin = clamp_margin_percent(margin_percent)
    offset = spread * margin / 100.0

    if mode == ZONE_MODE_CHEAP:
        reference = day_min
        threshold = round(day_min + offset, _PRICE_PRECISION)

        def qualifies(price: float) -> bool:
            return price <= threshold

    elif mode == ZONE_MODE_EXPENSIVE:
        reference = day_max
        threshold = round(day_max - offset, _PRICE_PRECISION)

        def qualifies(price: float) -> bool:
            return price >= threshold

    else:
        raise ValueError(f"Unknown price-zone mode: {mode!r}")

    run = _longest_contiguous_run(blocks, qualifies)
    if not run:
        # Unreachable in practice — the day's own extreme always qualifies —
        # but never fabricate a zone if a future threshold rule changes that.
        return None

    start = run[0][0]
    end = run[-1][1]
    return {
        "start": start,
        "end": end,
        "threshold_eur_kwh": threshold,
        "margin_percent": margin,
        "day_reference_price": reference,
        "day_min_price": day_min,
        "day_max_price": day_max,
        "quarter_count": len(run),
        "duration_minutes": _elapsed_minutes(start, end),
    }


def calculate_price_zones(
    prices: Sequence[Mapping[str, Any]] | None,
    cheap_margin_percent: float,
    expensive_margin_percent: float,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Derive both zones for one day and guarantee they cannot overlap.

    This is the entry point the integration uses: deriving the pair together is
    the only place that can see both thresholds, and therefore the only place
    that can enforce the invariant they must satisfy.

    With ``spread = day_max - day_min > 0`` and both margins capped at
    :data:`~.const.MAX_ZONE_MARGIN_PERCENT`::

        cheap_threshold     = day_min + spread * cheap%     / 100
        expensive_threshold = day_min + spread * (100 - expensive%) / 100

    so ``cheap_threshold < expensive_threshold`` exactly when
    ``cheap% + expensive% < 100`` — guaranteed, since each is at most 49. A
    quarter therefore cannot satisfy both ``price <= cheap_threshold`` and
    ``price >= expensive_threshold``, and the two selected windows cannot share
    a quarter.

    The guard below re-checks the invariant on the *rounded* thresholds rather
    than trusting the algebra. Rounding to six decimals can only collapse the
    two onto each other when the spread is smaller than a rounding step, which
    is a degenerate day; both zones are then withheld together, so the six
    entities stay consistent with each other rather than one going unavailable
    while the other publishes.
    """
    cheap = calculate_price_zone(prices, ZONE_MODE_CHEAP, cheap_margin_percent)
    expensive = calculate_price_zone(
        prices, ZONE_MODE_EXPENSIVE, expensive_margin_percent
    )

    if cheap is None or expensive is None:
        # A flat day, or no usable data: neither zone is meaningful on its own.
        return None, None

    if cheap["threshold_eur_kwh"] >= expensive["threshold_eur_kwh"]:
        return None, None

    return cheap, expensive


def is_within_zone(zone: Mapping[str, Any] | None, moment: datetime) -> bool | None:
    """Return whether ``moment`` falls inside ``zone``.

    The boundary rule is ``start <= moment < end``: a zone ends exactly at its
    ``till`` boundary, matching how the coordinator selects the active price
    block.

    All three values are converted to UTC first. Comparing the aware datetimes
    directly is *not* equivalent: CPython short-circuits ``<`` between two
    datetimes sharing the same ``tzinfo`` object to a naive wall-clock
    comparison that ignores ``fold``, and ``ZoneInfo`` is cached per key, so a
    zone boundary and ``dt_util.now()`` always share one object. A zone
    boundary inside the repeated 02:00-03:00 hour of the fall-back day would
    otherwise make the period sensors switch an hour early and flap on/off/on.

    Returns ``None`` when there is no usable zone, which the binary sensors
    surface as ``unavailable``.
    """
    if not isinstance(zone, Mapping):
        return None
    start = zone.get("start")
    end = zone.get("end")
    if (
        not isinstance(start, datetime)
        or not isinstance(end, datetime)
        or start.tzinfo is None
        or end.tzinfo is None
        or moment.tzinfo is None
    ):
        return None
    return _utc(start) <= _utc(moment) < _utc(end)
