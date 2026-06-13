# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-06-14

Initial release.

### Added

- Config-flow setup for the Frank Energie market price integration (NL default, optional BE via `x-country`).
- Native **quarter-hourly (15-minute, 96 blocks/day)** electricity prices via the public `marketPrices(date:, resolution: PT15M)` GraphQL query, with automatic fallback to hourly data when Frank has not published quarter-hour prices for a day.
- `DataUpdateCoordinator` polling every 15 minutes for today's and tomorrow's prices.
- Current price sensor with the full price breakdown as attributes.
- Today and tomorrow price sensors exposing the full raw price arrays as attributes.
- Cheapest and most-expensive price and start-time sensors for today and tomorrow.
- Binary sensor indicating whether tomorrow's prices are available (typically after ~15:00 CET).
- Diagnostics support with secrets redacted.
- HACS compatibility (`hacs.json`) and documentation.

[0.1.0]: https://github.com/Bennie-JC/ha-frank-quarter-prices/releases/tag/v0.1.0
