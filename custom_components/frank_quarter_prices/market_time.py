"""The market's own calendar day, independent of Home Assistant's timezone.

Frank publishes a **market day**: midnight to midnight in the market's own
timezone (Europe/Amsterdam for NL, Europe/Brussels for BE). Home Assistant's
configured timezone is a *display* preference — a user may legitimately run
Home Assistant in UTC, or on holiday abroad — and it must therefore never decide

* which blocks belong to "today" and which to "tomorrow",
* where a day starts and ends when validating that a fetched day is complete,
* what "today" is when the coordinator decides which days to request.

Using Home Assistant's timezone for any of those breaks the integration outright
on a non-CET installation: a UTC Home Assistant sees a Dutch day as two hours
short, so no day is ever accepted as complete, the six price-zone entities stay
permanently unavailable, and both days get re-requested on every quarter tick
(~144 requests a day instead of ~2).

This module is the single place that maps a country to its market timezone. It
is deliberately free of Home Assistant imports so it can be unit-tested in
isolation, like :mod:`.price` and :mod:`.price_zone`.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo

from .const import DEFAULT_COUNTRY, MARKET_TIMEZONES


def market_timezone(country: str | None) -> tzinfo:
    """Return the timezone the given market publishes its price day in.

    An unknown or missing country falls back to the default market (NL) rather
    than to UTC. UTC is not the day boundary of any Frank market, so silently
    falling back to it would reintroduce exactly the bug this module exists to
    prevent; the config flow only ever stores a supported country anyway.
    """
    name = MARKET_TIMEZONES.get(
        country or DEFAULT_COUNTRY, MARKET_TIMEZONES[DEFAULT_COUNTRY]
    )
    return ZoneInfo(name)


def market_now(country: str | None) -> datetime:
    """Return the current instant expressed in the market's timezone."""
    return datetime.now(market_timezone(country))


def market_midnight(day: date_type, country: str | None) -> datetime:
    """Return market-local midnight starting ``day``."""
    return datetime.combine(day, time.min, tzinfo=market_timezone(country))


def market_day_bounds(day: date_type, country: str | None) -> tuple[datetime, datetime]:
    """Return the market-local start and end instants of ``day``.

    The end is the *next* market midnight, so the span is 23, 24 or 25 hours
    across a daylight-saving transition with no special-casing and no
    assumption that a day holds 96 quarters.
    """
    return (
        market_midnight(day, country),
        market_midnight(day + timedelta(days=1), country),
    )


def market_date_of(moment: datetime, country: str | None) -> date_type:
    """Return the market calendar date an aware instant falls on."""
    return moment.astimezone(market_timezone(country)).date()
