"""Constants for the Frank Quarter Prices integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "frank_quarter_prices"

# Platforms supported by this integration.
PLATFORMS: Final[list[str]] = ["sensor", "binary_sensor"]

# Configuration / option keys.
CONF_COUNTRY: Final = "country"

# Feed-in (return-to-grid) price adjustment option.
#
# The amount in EUR/kWh added to the verified current market price to estimate
# the feed-in price. It may be positive (extra compensation), negative (a
# deduction / feed-in cost) or zero (market price unchanged). Default 0.0 so
# existing installations keep working without any reconfiguration.
CONF_FEED_IN_ADJUSTMENT: Final = "feed_in_adjustment"
DEFAULT_FEED_IN_ADJUSTMENT: Final = 0.0
MIN_FEED_IN_ADJUSTMENT: Final = -1.0
MAX_FEED_IN_ADJUSTMENT: Final = 1.0
FEED_IN_ADJUSTMENT_STEP: Final = 0.001

# Optional 21% VAT on the feed-in price. Off by default so existing
# installations keep the exact same sensor value after updating. When enabled,
# VAT is applied to the market price plus the configured adjustment. This is an
# explicit user choice: it is never inferred from API fields nor tied to a
# calendar year or the net-metering (saldering) scheme.
CONF_APPLY_FEED_IN_VAT: Final = "apply_feed_in_vat"
DEFAULT_APPLY_FEED_IN_VAT: Final = False
FEED_IN_VAT_RATE: Final = 0.21

# Daily price zones.
#
# Both margins are a percentage of the day's own price *range* (its most
# expensive quarter minus its cheapest), measured inward from the respective
# extreme. Applying the percentage to the absolute all-in price instead does not
# work: that price carries a fixed ~0.129 EUR/kWh energy-tax and markup floor
# that dwarfs the daily spread, so on a flat winter day a 15% band exceeds the
# whole day's range and the cheap and expensive zones overlap. Measured against
# a year of real Frank data, the absolute-price formula produced contradictory
# zones on 33 of 317 days at 15% and on 90 of 317 at 25%.
CONF_CHEAP_ZONE_MARGIN_PERCENT: Final = "cheap_zone_margin_percent"
CONF_EXPENSIVE_ZONE_MARGIN_PERCENT: Final = "expensive_zone_margin_percent"
DEFAULT_ZONE_MARGIN_PERCENT: Final = 15.0

# Accepted margin range. 0% selects only the quarters priced exactly at the
# day's extreme. The maximum is 49% rather than 50% so that the two bands are
# separated *by construction*: the cheap band ends at
# ``day_min + spread * cheap%`` and the expensive band starts at
# ``day_min + spread * (100 - expensive%)``, so they stay disjoint as long as
# ``cheap% + expensive% < 100``. Capping each at 49 guarantees at most 98.
MIN_ZONE_MARGIN_PERCENT: Final = 0.0
MAX_ZONE_MARGIN_PERCENT: Final = 49.0
ZONE_MARGIN_PERCENT_STEP: Final = 1.0

# Zone modes accepted by ``price_zone.calculate_price_zone``.
ZONE_MODE_CHEAP: Final = "cheap"
ZONE_MODE_EXPENSIVE: Final = "expensive"

# Optimal periods.
#
# A price *zone* answers "which contiguous part of the day falls inside my
# cheap/expensive threshold?". An optimal *period* answers a different question:
# "which exact X-minute contiguous window has the lowest (or highest) average
# price?". The two are deliberately independent features — an optimal period is
# derived from the actual prices and the requested duration alone and never
# consults the zone margins above, just as changing a duration never moves a
# zone boundary.
#
# Both are off by default so an installation upgrading from an earlier version
# gains no entities it did not ask for.
CONF_OPTIMAL_CHEAP_ENABLED: Final = "optimal_cheap_enabled"
CONF_OPTIMAL_CHEAP_DURATION_MINUTES: Final = "optimal_cheap_duration_minutes"
CONF_OPTIMAL_EXPENSIVE_ENABLED: Final = "optimal_expensive_enabled"
CONF_OPTIMAL_EXPENSIVE_DURATION_MINUTES: Final = "optimal_expensive_duration_minutes"
DEFAULT_OPTIMAL_ENABLED: Final = False

# Accepted duration range, in minutes.
#
# The minimum is one native quarter-hour block: the finest window the data can
# describe. The step matches it, so every value the selector offers is a whole
# number of quarter-hour blocks.
#
# The maximum is 12 hours. It is a deliberate half-day ceiling rather than a
# technical limit: beyond half a day the "cheapest contiguous window" converges
# on "most of the day" and stops being an actionable planning answer, while 12
# hours still covers the two cases this feature exists for — an overnight EV or
# battery charge, and a whole-evening avoid window. It also stays comfortably
# inside the 23-hour spring-forward day, so no configurable duration can become
# structurally impossible on one day of the year.
MIN_OPTIMAL_DURATION_MINUTES: Final = 15
MAX_OPTIMAL_DURATION_MINUTES: Final = 720
OPTIMAL_DURATION_STEP_MINUTES: Final = 15
DEFAULT_OPTIMAL_DURATION_MINUTES: Final = 120

# Modes accepted by ``optimal_period.calculate_optimal_period``.
OPTIMAL_MODE_CHEAP: Final = "cheap"
OPTIMAL_MODE_EXPENSIVE: Final = "expensive"

MINUTES_UNIT: Final = "min"

# Shared price unit for the monetary sensors.
PRICE_UNIT_EUR_KWH: Final = "EUR/kWh"
PERCENT_UNIT: Final = "%"

# Frank Energie GraphQL API.
GRAPHQL_ENDPOINT: Final = "https://graphql.frankenergie.nl/"
REQUEST_TIMEOUT: Final = 30
MAX_RETRIES: Final = 3

# Supported countries. NL is the default; BE is selected via the x-country header.
COUNTRY_NL: Final = "NL"
COUNTRY_BE: Final = "BE"
SUPPORTED_COUNTRIES: Final[tuple[str, ...]] = (COUNTRY_NL, COUNTRY_BE)
DEFAULT_COUNTRY: Final = COUNTRY_NL

# Timezone each market's price day is published in.
#
# Frank publishes a *market* day: midnight-to-midnight in the market's own
# timezone. Home Assistant's configured timezone is a display preference and may
# be anything at all, so it must never define which blocks belong to "today",
# nor where the day starts and ends when validating that a fetched day is
# complete. A Home Assistant running in UTC would otherwise see every Dutch day
# as two hours short, never accept one as complete, and re-request both days on
# every quarter tick forever.
MARKET_TIMEZONES: Final[dict[str, str]] = {
    COUNTRY_NL: "Europe/Amsterdam",
    COUNTRY_BE: "Europe/Brussels",
}

# The coordinator refreshes on these wall-clock minute boundaries rather than on
# a free-running interval, so the active price block and the today/tomorrow
# rollover never lag behind the real quarter-hour change (see coordinator.py).
QUARTER_BOUNDARY_MINUTES: Final[tuple[int, ...]] = (0, 15, 30, 45)

# Small buffer after each boundary before refreshing, to be robust against
# minor clock skew between Home Assistant and the Frank API rather than racing
# the exact boundary instant.
QUARTER_TICK_OFFSET_SECONDS: Final = 3

# Earliest local hour at which tomorrow's prices are requested.
#
# Frank publishes the day-ahead prices shortly after the 12:00 CET SDAC auction
# closes; they were observed appearing between 13:13 and 13:51 local time. Every
# request before publication is a guaranteed miss, so the coordinator does not
# ask for tomorrow before this hour. 12 rather than 13 leaves margin for an
# earlier-than-usual publication.
TOMORROW_PUBLISH_HOUR: Final = 12

# Minimum delay between tomorrow requests once they keep failing.
#
# A "not published yet" response is cheap and is retried on the next quarter
# tick, so tomorrow shows up within 15 minutes of publication. A single failed
# request is retried on the next tick too, so a blip costs nothing. Only from
# the second consecutive failure does this backoff engage, so a sustained
# outage cannot turn every remaining quarter tick of the day into a request.
TOMORROW_ERROR_BACKOFF_MINUTES: Final = 30

# Default integration title used in the config flow.
DEFAULT_NAME: Final = "Frank Quarter Prices"

# Device name. Kept short ("Frank") so entity ids become e.g.
# ``sensor.frank_current_price`` instead of a long device-name prefix.
DEVICE_NAME: Final = "Frank"
