# Frank Quarter Prices for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/v/release/Bennie-JC/ha-frank-quarter-prices?include_prereleases)](https://github.com/Bennie-JC/ha-frank-quarter-prices/releases)
[![License](https://img.shields.io/github/license/Bennie-JC/ha-frank-quarter-prices)](LICENSE)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.1%2B-blue.svg)](https://www.home-assistant.io/)

A Home Assistant custom integration that exposes **Frank Energie** dynamic market electricity prices — including **quarter-hourly (15-minute)** resolution — as rich sensors, ready for automation, energy management systems (EMS) and beautiful [ApexCharts](https://github.com/RomRider/apexcharts-card) dashboards.

> The integration polls the public Frank Energie GraphQL API every 15 minutes and provides today's and tomorrow's prices, cheapest/most-expensive windows, and chart-ready data series.

---

## Table of contents

- [Features](#features)
- [Installation](#installation)
  - [HACS installation (recommended)](#hacs-installation-recommended)
  - [Manual installation](#manual-installation)
- [Configuration](#configuration)
- [Sensors created](#sensors-created)
  - [Sensor overview](#sensor-overview)
  - [Cheapest price sensors](#cheapest-price-sensors)
  - [Most expensive price sensors](#most-expensive-price-sensors)
  - [ApexCharts sensors](#apexcharts-sensors)
- [Tomorrow prices handling](#tomorrow-prices-handling)
- [GraphQL API source](#graphql-api-source)
- [EMS integration examples](#ems-integration-examples)
- [Example ApexCharts cards](#example-apexcharts-cards)
- [Example Home Assistant templates](#example-home-assistant-templates)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [Contributing](#contributing)
- [Disclaimer](#disclaimer)
- [License](#license)

---

## Features

- ⚡ **Quarter-hourly prices** — full 15-minute market price resolution (with automatic fallback to 60-minute data when that is what Frank publishes).
- 📅 **Today & tomorrow** — both days fetched automatically; tomorrow's prices appear once published (typically around 15:00 CET).
- 💶 **Current price sensor** — the active price slot, with the full price breakdown as attributes.
- 📉 **Cheapest / most expensive** sensors for **today**, **tomorrow**, the **next 24h** and the **next 48h**, each with start/end time sensors.
- 📈 **ApexCharts-ready** data series sensors (24h/48h, quarter & hourly aggregation).
- 🔁 **Resilient updates** — tomorrow data being unavailable never breaks the integration; the last known values are retained.
- 🌍 **NL default with optional BE support** via the `x-country` header.
- 🛠️ **Diagnostics support** for easy troubleshooting (secrets redacted).
- 🧩 Built on Home Assistant's `DataUpdateCoordinator` and config entries, following modern (2025+) best practices.

---

## Installation

### HACS installation (recommended)

1. Make sure [HACS](https://hacs.xyz/) is installed.
2. In Home Assistant go to **HACS → Integrations → ⋮ (top right) → Custom repositories**.
3. Add the repository URL:
   ```
   https://github.com/Bennie-JC/ha-frank-quarter-prices
   ```
   and select the category **Integration**.
4. Search for **Frank Quarter Prices** in HACS and click **Download**.
5. **Restart Home Assistant**.

### Manual installation

1. Download the latest release from the [releases page](https://github.com/Bennie-JC/ha-frank-quarter-prices/releases).
2. Copy the folder `custom_components/frank_quarter_prices` into your Home Assistant `config/custom_components/` directory:
   ```
   config/
   └── custom_components/
       └── frank_quarter_prices/
           ├── __init__.py
           ├── manifest.json
           ├── ...
   ```
3. **Restart Home Assistant**.

---

## Configuration

Configuration is done entirely through the UI (config flow).

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Frank Quarter Prices**.
3. Follow the prompts and submit.

All entities are grouped under a single **Frank Quarter Prices** device.

> **Note on entity IDs:** Home Assistant derives entity IDs from the device and entity names. Depending on your setup, the entities may be named e.g. `sensor.frank_quarter_prices_current_electricity_price`. The examples in this README use the short form `sensor.frank_current_electricity_price` for readability — adjust them to match the entity IDs in **Developer Tools → States** on your system, or rename the entities to the short form.

---

## Sensors created

### Sensor overview

| Entity | Description | State | Unit |
| --- | --- | --- | --- |
| `sensor.frank_current_electricity_price` | Price of the currently active slot | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_prices_today` | Number of price blocks today | count | blocks |
| `sensor.frank_prices_tomorrow` | Number of price blocks tomorrow | count | blocks |
| `sensor.frank_cheapest_price_today` | Cheapest block today | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_cheapest_price_today_start` | Start of cheapest block today | ISO datetime | — |
| `sensor.frank_cheapest_price_today_end` | End of cheapest block today | ISO datetime | — |
| `sensor.frank_most_expensive_price_today` | Most expensive block today | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_most_expensive_price_today_start` | Start of most expensive block today | ISO datetime | — |
| `sensor.frank_most_expensive_price_today_end` | End of most expensive block today | ISO datetime | — |
| `sensor.frank_cheapest_price_tomorrow` | Cheapest block tomorrow | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_cheapest_price_tomorrow_start` | Start of cheapest block tomorrow | ISO datetime | — |
| `sensor.frank_cheapest_price_tomorrow_end` | End of cheapest block tomorrow | ISO datetime | — |
| `sensor.frank_most_expensive_price_tomorrow` | Most expensive block tomorrow | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_most_expensive_price_tomorrow_start` | Start of most expensive block tomorrow | ISO datetime | — |
| `sensor.frank_most_expensive_price_tomorrow_end` | End of most expensive block tomorrow | ISO datetime | — |
| `sensor.frank_cheapest_price_next_24h` | Cheapest block in the next 24h (from now) | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_most_expensive_price_next_24h` | Most expensive block in the next 24h (from now) | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_cheapest_price_next_48h` | Cheapest block across today + tomorrow | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_most_expensive_price_next_48h` | Most expensive block across today + tomorrow | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_apex_24h_quarter` | ApexCharts series, next 24h, source resolution | datapoint count | points |
| `sensor.frank_apex_48h_quarter` | ApexCharts series, next 48h, source resolution | datapoint count | points |
| `sensor.frank_apex_24h_hourly` | ApexCharts series, next 24h, hourly average | datapoint count | points |
| `sensor.frank_apex_48h_hourly` | ApexCharts series, next 48h, hourly average | datapoint count | points |
| `binary_sensor.frank_tomorrow_prices_available` | Whether tomorrow's prices are published | on/off | — |

> The `next_24h` cheapest/most-expensive sensors also expose `_start` and `_end` companion sensors.

Every price/cheapest/most-expensive sensor exposes the **full price block** as attributes:

```yaml
from: "2026-06-13T14:00:00+02:00"
till: "2026-06-13T14:15:00+02:00"
duration_minutes: 15
market_price: 0.08123
market_price_tax: 0.01705
sourcing_markup_price: 0.01700
energy_tax_price: 0.10154
total_price_eur_kwh: 0.21682
per_unit: "kWh"
```

### Cheapest price sensors

Find the lowest price window and act on it:

- `sensor.frank_cheapest_price_today` — cheapest slot for the rest of today's published prices.
- `sensor.frank_cheapest_price_tomorrow` — cheapest slot tomorrow (once published).
- `sensor.frank_cheapest_price_next_24h` — cheapest slot in the next 24 hours from **now** (future-only).
- `sensor.frank_cheapest_price_next_48h` — cheapest slot across today and tomorrow.

Each comes with `_start` / `_end` sensors returning ISO datetime strings, ideal for scheduling.

### Most expensive price sensors

Avoid the peaks:

- `sensor.frank_most_expensive_price_today`
- `sensor.frank_most_expensive_price_tomorrow`
- `sensor.frank_most_expensive_price_next_24h`
- `sensor.frank_most_expensive_price_next_48h`

Also with `_start` / `_end` companions.

### ApexCharts sensors

These sensors expose chart-ready data in the `data` attribute as an array of `[timestamp_ms, price]` pairs:

```yaml
data:
  - [1749816000000, 0.21682]
  - [1749816900000, 0.20114]
  # ...
span_hours: 48
resolution: 15        # 60 for the *_hourly sensors
generated_at: "2026-06-13T14:02:00+02:00"
tomorrow_available: true
```

| Sensor | Window | Resolution |
| --- | --- | --- |
| `sensor.frank_apex_24h_quarter` | Next 24h | Source (15m or 60m) |
| `sensor.frank_apex_48h_quarter` | Next 48h | Source (15m or 60m) |
| `sensor.frank_apex_24h_hourly` | Next 24h | Hourly average |
| `sensor.frank_apex_48h_hourly` | Next 48h | Hourly average |

---

## Tomorrow prices handling

Frank Energie publishes the next day's prices during the afternoon (typically around **15:00 CET**). The integration handles this gracefully:

- Tomorrow's prices are **always attempted** on every update.
- If they are **not yet available**, the integration:
  - keeps `binary_sensor.frank_tomorrow_prices_available` **off**,
  - retains the **last known** tomorrow data if it exists, otherwise an empty list,
  - logs an **info** message only — it never raises an error or marks the integration as failed.
- Once published, `binary_sensor.frank_tomorrow_prices_available` turns **on** and the tomorrow sensors populate.

Use the binary sensor to gate automations that depend on tomorrow's prices.

---

## GraphQL API source

Prices are sourced from the public Frank Energie GraphQL API:

```
https://graphql.frankenergie.nl/
```

No authentication is required for market prices. The integration issues a query similar to:

```graphql
query MarketPrices($date: String!) {
  marketPrices(date: $date) {
    electricityPrices {
      from
      till
      marketPrice
      marketPriceTax
      sourcingMarkupPrice
      energyTaxPrice
      perUnit
    }
  }
}
```

Requests use a 30-second timeout and are retried up to 3 times. Invalid records are validated and skipped. Belgium (BE) is supported by sending the `x-country: BE` header; the Netherlands (NL) is the default.

---

## EMS integration examples

Use the cheapest/most-expensive windows to drive an Energy Management System, charging, or heavy appliances.

**Charge an EV during the cheapest block today:**

```yaml
automation:
  - alias: "Charge EV at cheapest price today"
    trigger:
      - platform: template
        value_template: >
          {{ now() >= states('sensor.frank_cheapest_price_today_start') | as_datetime
             and now() < states('sensor.frank_cheapest_price_today_end') | as_datetime }}
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.ev_charger
```

**Avoid running the dishwasher during the daily peak:**

```yaml
automation:
  - alias: "Block dishwasher during peak price"
    trigger:
      - platform: template
        value_template: >
          {{ now() >= states('sensor.frank_most_expensive_price_today_start') | as_datetime
             and now() < states('sensor.frank_most_expensive_price_today_end') | as_datetime }}
    action:
      - service: switch.turn_off
        target:
          entity_id: switch.dishwasher
```

**Only act when prices are cheap enough (threshold):**

```yaml
automation:
  - alias: "Heat water when price is low"
    trigger:
      - platform: state
        entity_id: sensor.frank_current_electricity_price
    condition:
      - condition: numeric_state
        entity_id: sensor.frank_current_electricity_price
        below: 0.15
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.water_heater
```

---

## Example ApexCharts cards

Requires the [apexcharts-card](https://github.com/RomRider/apexcharts-card) custom Lovelace card.

**48h quarter-hourly price chart:**

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Frank Energie — Next 48h (15 min)
graph_span: 48h
span:
  start: hour
series:
  - entity: sensor.frank_apex_48h_quarter
    name: Price
    type: column
    unit: €/kWh
    data_generator: |
      return entity.attributes.data.map((point) => {
        return [point[0], point[1]];
      });
```

**24h hourly average with current price line:**

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Frank Energie — Next 24h (hourly)
graph_span: 24h
series:
  - entity: sensor.frank_apex_24h_hourly
    name: Hourly average
    type: area
    unit: €/kWh
    data_generator: |
      return entity.attributes.data.map((p) => [p[0], p[1]]);
```

---

## Example Home Assistant templates

**Show the current price nicely formatted:**

```yaml
{{ states('sensor.frank_current_electricity_price') | float(0) | round(4) }} €/kWh
```

**Time until the cheapest block today:**

```yaml
{% set start = states('sensor.frank_cheapest_price_today_start') | as_datetime %}
{% if start %}
  {{ (start - now()).total_seconds() // 60 }} minutes
{% else %}
  unknown
{% endif %}
```

**Is the current price below today's average?**

```yaml
{% set prices = state_attr('sensor.frank_prices_today', 'prices') %}
{% if prices %}
  {% set avg = (prices | map(attribute='total_price_eur_kwh') | sum) / (prices | length) %}
  {{ states('sensor.frank_current_electricity_price') | float(0) < avg }}
{% else %}
  unknown
{% endif %}
```

**Cheapest price tomorrow (waits until published):**

```yaml
{% if is_state('binary_sensor.frank_tomorrow_prices_available', 'on') %}
  {{ states('sensor.frank_cheapest_price_tomorrow') }} €/kWh
{% else %}
  Tomorrow's prices not published yet
{% endif %}
```

---

## Troubleshooting

- **Entities show `unavailable`:**
  - For tomorrow / cheapest-tomorrow sensors this is expected before Frank publishes the next day (around 15:00 CET). Check `binary_sensor.frank_tomorrow_prices_available`.
  - For all sensors, verify the integration loaded under **Settings → Devices & Services**.
- **Entity IDs don't match the README:** see the [Configuration](#configuration) note — adjust to the IDs shown in **Developer Tools → States**.
- **No data at all:** confirm Home Assistant has outbound internet access to `https://graphql.frankenergie.nl/`.
- **Enable debug logging** by adding this to `configuration.yaml` and restarting:

  ```yaml
  logger:
    default: warning
    logs:
      custom_components.frank_quarter_prices: debug
  ```

- **Diagnostics:** open the device page → **⋮ → Download diagnostics** and attach the (secret-redacted) file to any bug report.

---

## FAQ

**Do I need a Frank Energie account or API token?**
No. Market prices are public and require no authentication.

**Does this show my personal contract/usage costs?**
No. It exposes the market price components (market price, tax, sourcing markup, energy tax). Your effective tariff may differ depending on your contract.

**What resolution are the prices?**
Quarter-hourly (15-minute) where Frank publishes it; the integration automatically detects and falls back to hourly (60-minute) data when needed.

**How often does it update?**
Every 15 minutes via a `DataUpdateCoordinator`.

**Why is tomorrow empty in the morning?**
Frank typically publishes next-day prices in the afternoon (~15:00 CET). The integration retains the last known values and never errors out in the meantime.

**Does it support Belgium?**
Yes — Netherlands (NL) is the default; Belgian (BE) pricing is requested via the `x-country` header.

**Is this an official Frank Energie integration?**
No, this is an independent community project. See the [disclaimer](#disclaimer).

---

## Contributing

Contributions are welcome! Please open an [issue](https://github.com/Bennie-JC/ha-frank-quarter-prices/issues) or submit a pull request. For larger changes, open an issue first to discuss what you would like to change.

---

## Disclaimer

This project is **not affiliated with, endorsed by, or supported by Frank Energie**. It uses a publicly accessible API and is provided "as is", without warranty of any kind. Prices shown may differ from your actual contract pricing. Use at your own risk.

---

## License

Distributed under the terms of the [LICENSE](LICENSE) file in this repository.
