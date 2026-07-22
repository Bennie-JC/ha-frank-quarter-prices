"""Constants for the Frank Quarter Prices integration."""

from __future__ import annotations

from datetime import timedelta
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

# Shared price unit for the monetary sensors.
PRICE_UNIT_EUR_KWH: Final = "EUR/kWh"

# Frank Energie GraphQL API.
GRAPHQL_ENDPOINT: Final = "https://graphql.frankenergie.nl/"
REQUEST_TIMEOUT: Final = 30
MAX_RETRIES: Final = 3

# Supported countries. NL is the default; BE is selected via the x-country header.
COUNTRY_NL: Final = "NL"
COUNTRY_BE: Final = "BE"
SUPPORTED_COUNTRIES: Final[tuple[str, ...]] = (COUNTRY_NL, COUNTRY_BE)
DEFAULT_COUNTRY: Final = COUNTRY_NL

# Default polling interval for the coordinator.
DEFAULT_SCAN_INTERVAL: Final = timedelta(minutes=15)

# Default integration title used in the config flow.
DEFAULT_NAME: Final = "Frank Quarter Prices"

# Device name. Kept short ("Frank") so entity ids become e.g.
# ``sensor.frank_current_price`` instead of a long device-name prefix.
DEVICE_NAME: Final = "Frank"
