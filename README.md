# Frank Quarter Prices for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/v/release/Bennie-JC/ha-frank-quarter-prices?include_prereleases)](https://github.com/Bennie-JC/ha-frank-quarter-prices/releases)
[![License](https://img.shields.io/github/license/Bennie-JC/ha-frank-quarter-prices)](LICENSE)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.1%2B-blue.svg)](https://www.home-assistant.io/)

A Home Assistant custom integration that exposes **Frank Energie** dynamic market electricity prices — including **quarter-hourly (15-minute)** resolution — as a compact set of sensors, designed as a clean **price source for an Energy Management System (EMS)**.

> The integration polls the public Frank Energie GraphQL API every 15 minutes and provides today's and tomorrow's prices, the current price, and the cheapest/most-expensive windows for each day. The full price arrays are available as sensor attributes for your EMS logic.

---

## Table of contents

- [Features](#features)
- [Installation](#installation)
  - [HACS installation (recommended)](#hacs-installation-recommended)
  - [Manual installation](#manual-installation)
- [Configuration](#configuration)
- [Sensors created](#sensors-created)
  - [Sensor overview](#sensor-overview)
  - [Cheapest / most expensive sensors](#cheapest--most-expensive-sensors)
  - [Price block attributes](#price-block-attributes)
- [Tomorrow prices handling](#tomorrow-prices-handling)
- [GraphQL API source](#graphql-api-source)
- [EMS integration examples](#ems-integration-examples)
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
- 📉 **Cheapest / most expensive** price + start-time sensors for the **full day** today and tomorrow.
- 🗂️ **Full price arrays** for today and tomorrow exposed as sensor attributes — ideal as an EMS data source.
- 🔁 **Resilient updates** — tomorrow data being unavailable never breaks the integration; it simply stays unavailable until published.
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

All entities are grouped under a single **Frank** device, so entity IDs take the short form `sensor.frank_<name>` (for example `sensor.frank_current_price`). The examples in this README use those IDs directly — you can confirm them in **Developer Tools → States** on your system.

---

## Sensors created

The integration creates exactly **12 entities**, scoped for EMS use.

For each day the integration requests **all** electricity price blocks from Frank (local 00:00 → 24:00) and finds the single cheapest and single most-expensive block of that **full day**, at the raw resolution Frank returns (15-minute or hourly). No next-24h/48h windows, current-time-only filtering, future-only filtering, or hourly averaging is used.

### Sensor overview

| Entity | Description | State | Unit |
| --- | --- | --- | --- |
| `sensor.frank_current_price` | Price of the currently active slot | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_cheapest_today` | Cheapest block price of the full day today | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_cheapest_time_today` | Start time of the cheapest block today | `HH:MM` | — |
| `sensor.frank_most_expensive_today` | Most expensive block price of the full day today | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_most_expensive_time_today` | Start time of the most expensive block today | `HH:MM` | — |
| `sensor.frank_cheapest_tomorrow` | Cheapest block price of the full day tomorrow | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_cheapest_time_tomorrow` | Start time of the cheapest block tomorrow | `HH:MM` | — |
| `sensor.frank_most_expensive_tomorrow` | Most expensive block price of the full day tomorrow | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_most_expensive_time_tomorrow` | Start time of the most expensive block tomorrow | `HH:MM` | — |
| `sensor.frank_prices_today` | Number of price blocks today (full array in attributes) | count | blocks |
| `sensor.frank_prices_tomorrow` | Number of price blocks tomorrow (full array in attributes) | count | blocks |
| `binary_sensor.frank_tomorrow_prices_available` | Whether tomorrow's prices are published | on/off | — |

### Cheapest / most expensive sensors

For each day there is a matched pair of sensors built from the same block:

**Price sensor** (`sensor.frank_cheapest_today`, `sensor.frank_most_expensive_today`, and the `*_tomorrow` variants):

- **State:** the block's `total_price_eur_kwh` (EUR/kWh).
- **Attributes:**
  - `time` — the block's local **start** time as `"HH:MM"` (e.g. `"19:45"`),
  - `timestamp` — the block start as a local ISO datetime,
  - `end_timestamp` — the block end as a local ISO datetime,
  - `duration_minutes` — the block length (15 or 60),
  - `full_block` — the complete price breakdown.

**Time sensor** (`sensor.frank_cheapest_time_today`, `sensor.frank_most_expensive_time_today`, and the `*_tomorrow` variants):

- **State:** the block's local **start** time as `"HH:MM"` (e.g. `"13:45"`).
- **Attributes:** `price`, `timestamp`, `end_timestamp`, `duration_minutes`, `full_block`.

Example:

```text
sensor.frank_cheapest_today = 0.0735           # EUR/kWh
  attributes:
    time: "19:45"
    timestamp: "2026-06-13T19:45:00+02:00"
    end_timestamp: "2026-06-13T20:00:00+02:00"
    duration_minutes: 15

sensor.frank_cheapest_time_today = "19:45"
  attributes:
    price: 0.0735
    timestamp: "2026-06-13T19:45:00+02:00"
    end_timestamp: "2026-06-13T20:00:00+02:00"
    duration_minutes: 15
```

The `*_tomorrow` sensors stay **unavailable** until Frank publishes tomorrow's prices.

### Price block attributes

The `full_block` attribute (and each entry of the `prices` arrays) has the form:

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

The `sensor.frank_prices_today` and `sensor.frank_prices_tomorrow` sensors expose the **complete array** of price blocks for the full day in their `prices` attribute, along with `resolution_minutes`, `cheapest_block`, `most_expensive_block`, `average_price`, `min_price` and `max_price`. This makes them the convenient single source for an EMS to plan against.

---

## Tomorrow prices handling

Frank Energie publishes the next day's prices during the afternoon (typically around **15:00 CET**). The integration handles this gracefully:

- Tomorrow's prices are **always attempted** on every update (every 15 minutes).
- If they are **not yet available**, the integration:
  - keeps `binary_sensor.frank_tomorrow_prices_available` **off**,
  - leaves the `*_tomorrow` sensors **unavailable**,
  - logs an **info** message only — it never raises `UpdateFailed` or marks the integration as failed just because tomorrow is missing.
- Once published (typically after **15:00 local time**), `binary_sensor.frank_tomorrow_prices_available` turns **on** and the tomorrow sensors populate on the next 15-minute refresh.

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

Use the cheapest/most-expensive windows to drive an Energy Management System, charging, or heavy appliances. Each cheapest/most-expensive sensor exposes `timestamp` and `end_timestamp` attributes (local ISO datetimes) that are convenient for scheduling.

**Charge an EV during the cheapest block today:**

```yaml
automation:
  - alias: "Charge EV at cheapest price today"
    trigger:
      - platform: template
        value_template: >
          {{ now() >= state_attr('sensor.frank_cheapest_today', 'timestamp') | as_datetime
             and now() < state_attr('sensor.frank_cheapest_today', 'end_timestamp') | as_datetime }}
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
          {{ now() >= state_attr('sensor.frank_most_expensive_today', 'timestamp') | as_datetime
             and now() < state_attr('sensor.frank_most_expensive_today', 'end_timestamp') | as_datetime }}
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
        entity_id: sensor.frank_current_price
    condition:
      - condition: numeric_state
        entity_id: sensor.frank_current_price
        below: 0.15
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.water_heater
```

---

## Example Home Assistant templates

**Show the current price nicely formatted:**

```yaml
{{ states('sensor.frank_current_price') | float(0) | round(4) }} €/kWh
```

**Time until the cheapest block today:**

```yaml
{% set start = state_attr('sensor.frank_cheapest_today', 'timestamp') | as_datetime %}
{% if start %}
  {{ (start - now()).total_seconds() // 60 }} minutes
{% else %}
  unknown
{% endif %}
```

**Is the current price below today's average?**

```yaml
{% set avg = state_attr('sensor.frank_prices_today', 'average_price') %}
{% if avg is not none %}
  {{ states('sensor.frank_current_price') | float(0) < avg }}
{% else %}
  unknown
{% endif %}
```

**Cheapest price tomorrow (waits until published):**

```yaml
{% if is_state('binary_sensor.frank_tomorrow_prices_available', 'on') %}
  {{ states('sensor.frank_cheapest_tomorrow') }} €/kWh
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
Frank typically publishes next-day prices in the afternoon (~15:00 CET). The `*_tomorrow` sensors stay unavailable until then and the integration never errors out in the meantime.

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
