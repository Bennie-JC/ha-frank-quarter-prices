# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.3] - 2026-07-22

### Added

- Home Assistant Energy Dashboard support for `sensor.frank_current_price` as the current electricity purchase-price entity.
- New `sensor.frank_current_return_price` entity exposing the estimated current electricity feed-in price.
- Configurable **feed-in adjustment** through the integration options (positive, negative or zero; default `0.0 EUR/kWh`).
- Optionele instelling toegevoegd om 21% btw toe te passen op de berekende terugleverprijs (standaard uitgeschakeld).
- Dutch and English translations for the new options.
- Energy Dashboard setup instructions and a feed-in-price calculation example in the README.

### Changed

- The feed-in-price calculation uses the Frank API's verified raw `market_price` field (the EPEX/spot price, excluding VAT, energy tax and markups) plus the configured adjustment. It does **not** assume VAT (`market_price_tax`), energy tax or purchase-price components apply to electricity returned to the grid. Verified against the live public API: `market_price_tax` is 21% VAT charged on the purchase side, and the public endpoint exposes no explicit feed-in-price field.

## [0.1.2] - 2026-06-21

### Added

- Dutch translation file (`translations/nl.json`) for the config flow.
- GitHub Actions workflows: Hassfest validation, HACS validation, and Ruff lint.
- `country` key in `hacs.json` (`["NL", "BE"]`) for HACS Default inclusion.
- Brands-ready PNG assets documented in the README for the Home Assistant Brands submission.

### Changed

- README fully translated to Dutch and optimized for SEO (Frank Energie, kwartierprijzen, EMS, batterijoptimalisatie).
- Clarified the integration delivers **quarter-hour (15-minute) prices**, never hourly prices (hourly is only a fallback).

### Fixed

- Removed the unsupported `domains` key from `hacs.json` so HACS manifest validation passes.
- Documented the exact fix for the *"icon not available"* entry in the Home Assistant integration list (Home Assistant Brands submission).

## [0.1.1] - 2026-06-14

### Added

- ApexCharts dashboard examples for today and tomorrow price charts (`examples/apexcharts_frank_prices_today.yaml`, `examples/apexcharts_frank_prices_tomorrow.yaml`).
- README instructions for the ApexCharts Card and Config Template Card.
- Integration icon/logo assets (`icons/icon.svg`, `icons/logo.svg`) and Home Assistant Brands guidance.

### Changed

- Integration manufacturer/service info changed to **Jouw Cloud B.V.** (device model is now "Frank Energie Market Prices"; `sw_version` reflects the integration version).
- Documentation improved for EMS usage and quarter-hour price attributes.

### Fixed

- Clarified chart usage with `sensor.frank_prices_today` attributes — each block from `attributes.prices` is rendered individually (96 bars for quarter-hour data, 24 for hourly).

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

[0.1.3]: https://github.com/Bennie-JC/ha-frank-quarter-prices/releases/tag/v0.1.3
[0.1.2]: https://github.com/Bennie-JC/ha-frank-quarter-prices/releases/tag/v0.1.2
[0.1.1]: https://github.com/Bennie-JC/ha-frank-quarter-prices/releases/tag/v0.1.1
[0.1.0]: https://github.com/Bennie-JC/ha-frank-quarter-prices/releases/tag/v0.1.0

[0.1.0]: https://github.com/Bennie-JC/ha-frank-quarter-prices/releases/tag/v0.1.0