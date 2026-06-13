"""Constants for the Frank Quarter Prices integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "frank_quarter_prices"

# Platforms supported by this integration.
PLATFORMS: Final[list[str]] = ["sensor", "binary_sensor"]

# Configuration / option keys.
CONF_COUNTRY: Final = "country"

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
