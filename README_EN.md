# Frank Energie Quarter-Hour Prices for Home Assistant

[🇳🇱 Nederlands](README.md) | 🇬🇧 English

[![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/default)
[![GitHub release](https://img.shields.io/github/v/release/Bennie-JC/ha-frank-quarter-prices?display_name=tag&sort=semver&color=blue)](https://github.com/Bennie-JC/ha-frank-quarter-prices/releases/latest)
[![HACS validation](https://github.com/Bennie-JC/ha-frank-quarter-prices/actions/workflows/hacs.yml/badge.svg)](https://github.com/Bennie-JC/ha-frank-quarter-prices/actions/workflows/hacs.yml)
[![Hassfest](https://github.com/Bennie-JC/ha-frank-quarter-prices/actions/workflows/hassfest.yml/badge.svg)](https://github.com/Bennie-JC/ha-frank-quarter-prices/actions/workflows/hassfest.yml)
[![GitHub stars](https://img.shields.io/github/stars/Bennie-JC/ha-frank-quarter-prices?style=flat&color=yellow)](https://github.com/Bennie-JC/ha-frank-quarter-prices/stargazers)
[![GitHub issues](https://img.shields.io/github/issues/Bennie-JC/ha-frank-quarter-prices?color=orange)](https://github.com/Bennie-JC/ha-frank-quarter-prices/issues)
[![GitHub last commit](https://img.shields.io/github/last-commit/Bennie-JC/ha-frank-quarter-prices?color=blueviolet)](https://github.com/Bennie-JC/ha-frank-quarter-prices/commits/main)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.1%2B-blue.svg)](https://www.home-assistant.io/)
[![Maintained](https://img.shields.io/maintenance/yes/2026.svg)](https://github.com/Bennie-JC/ha-frank-quarter-prices)

**Frank Energie Quarter-Hour Prices** is an unofficial Home Assistant **custom integration** for **Frank Energie's dynamic electricity prices** on a **15-minute basis** — the raw quarter-hour resolution as published by Frank Energie itself, not an hourly average.

The integration provides the full quarter-hour prices for **today** and, once published, **tomorrow**, together with the current purchase price, the current feed-in price, and the cheapest and most expensive price window of the day. The sensors are ready to use in **dashboards**, **automations**, for **home batteries**, and in your own **Energy Management System (EMS)** — well suited for anyone acting on **dynamic electricity prices**.

The integration is included in **HACS Default**, so it's directly searchable and installable through HACS without adding a custom repository.

> This integration reads the public Frank Energie GraphQL API and exposes today's and tomorrow's prices, the current price, and the cheapest and most expensive price window of each day. The active quarter-hour price is recalculated on every real quarter-hour boundary (`:00`/`:15`/`:30`/`:45`); the daily price series themselves are cached locally and only fetched when missing. The full price series are available as sensor attributes for your own EMS logic, battery control, and dynamic electricity tariffs.

---

## Table of Contents

- [Features](#features)
- [Installation](#installation)
  - [HACS installation (recommended)](#hacs-installation-recommended)
  - [Manual installation](#manual-installation)
- [Configuration](#configuration)
- [Sensors created](#sensors-created)
  - [Sensor overview](#sensor-overview)
  - [Cheapest / most expensive price window sensors](#cheapest--most-expensive-price-window-sensors)
  - [Price block attributes](#price-block-attributes)
- [Home Assistant Energy Dashboard](#home-assistant-energy-dashboard)
  - [Grid consumption](#grid-consumption)
  - [Grid feed-in](#grid-feed-in)
  - [Feed-in price calculation example](#feed-in-price-calculation-example)
- [Handling tomorrow's prices](#handling-tomorrows-prices)
- [GraphQL API source](#graphql-api-source)
- [ApexCharts dashboard](#apexcharts-dashboard)
- [EMS integration examples](#ems-integration-examples)
- [Example Home Assistant templates](#example-home-assistant-templates)
- [Brand assets (integration icon)](#brand-assets-integration-icon)
- [Troubleshooting](#troubleshooting)
- [Frequently asked questions](#frequently-asked-questions)
- [Contributing](#contributing)
- [Disclaimer](#disclaimer)
- [License](#license)

---

## Features

- ⚡ **Quarter-hour prices** — full 15-minute market price resolution (with automatic fallback to 60-minute data when that's what Frank Energie publishes).
- 📅 **Today & tomorrow** — both days are fetched automatically and cached locally; tomorrow's prices appear as soon as they're published (typically between 1 PM and 2 PM local time).
- 💶 **Current price sensor** — the currently active price block, with the full price breakdown as attributes.
- 📉 Sensors for the **cheapest and most expensive** price window (price + start time) for the **entire day**, for both today and tomorrow.
- 🗂️ **Full price series** for today and tomorrow as sensor attributes — ideal as a data source for an EMS.
- 📦 **HACS Default** — directly searchable and installable within HACS, no custom repository needed.
- 🔁 **Robust updates** — if tomorrow's data isn't available yet, the integration never breaks; the sensors simply stay unavailable until publication.
- 🌍 **NL as default with optional BE support** via the `x-country` header.
- 🛠️ **Diagnostics support** for easy troubleshooting (secrets are redacted).
- 🧩 Built on Home Assistant's `DataUpdateCoordinator` and config entries, following modern best practices (2025+).

---

## Installation

### HACS installation (recommended)

This integration is included in **HACS Default** and is directly searchable in HACS — adding a custom repository is not necessary.

[![Open this HACS repository in your Home Assistant.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Bennie-JC&repository=ha-frank-quarter-prices&category=integration)

> This button opens the repository directly in **HACS**, for **installing or updating** the custom integration. To then **configure** the integration, use the separate "Add Integration" button under [Configuration](#configuration).

1. Make sure [HACS](https://hacs.xyz/) is installed.
2. In Home Assistant, go to **HACS → Integrations**.
3. Search for **Frank Quarter Prices** and click **Download**.
4. **Restart Home Assistant**.

> Don't see the integration right away? Reload the HACS cache (**HACS → ⋮ top right → Reload HACS**). As a fallback, you can also temporarily add the repository manually via **HACS → Integrations → ⋮ (top right) → Custom repositories** with the URL `https://github.com/Bennie-JC/ha-frank-quarter-prices` (category **Integration**).

### Manual installation

1. Download the latest release from the [releases page](https://github.com/Bennie-JC/ha-frank-quarter-prices/releases).
2. Copy the `custom_components/frank_quarter_prices` folder into your Home Assistant's `config/custom_components/` folder:
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

Configuration is done entirely through the user interface (config flow).

> **Note:** install the integration via HACS first and restart Home Assistant. Only then can you add it with the button below.

[![Open your Home Assistant instance and add this integration.](https://my.home-assistant.io/badges/integration.svg)](https://my.home-assistant.io/redirect/integration/?domain=frank_quarter_prices)

Or manually:

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Frank Quarter Prices**.
3. Follow the steps and confirm.

All entities are grouped under a single **Frank** device, so entity IDs take the short form `sensor.frank_<name>` (for example `sensor.frank_current_price`). The examples in this README use those IDs directly — you can verify them via **Developer Tools → States** on your own system.

---

## Sensors created

The integration creates exactly **13 entities**, tailored for use within an EMS.

For each day, the integration requests **all** electricity price blocks from Frank Energie (local 00:00 → 24:00) and determines the single cheapest and single most expensive block of that **entire day**, at the raw resolution Frank returns (15 minutes or hourly). There is no filtering to the next 24/48 hours, no filtering to only the current time, no filtering to only the future, and no hourly averaging applied.

### Sensor overview

| Entity | Description | State | Unit |
| --- | --- | --- | --- |
| `sensor.frank_current_price` | Price of the currently active block | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_current_return_price` | Estimated current electricity feed-in price, based on the verified Frank market-price field and the configured feed-in adjustment | calculated price | EUR/kWh |
| `sensor.frank_cheapest_today` | Cheapest block price of the entire day today | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_cheapest_time_today` | Start time of the cheapest block today | `HH:MM` | — |
| `sensor.frank_most_expensive_today` | Most expensive block price of the entire day today | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_most_expensive_time_today` | Start time of the most expensive block today | `HH:MM` | — |
| `sensor.frank_cheapest_tomorrow` | Cheapest block price of the entire day tomorrow | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_cheapest_time_tomorrow` | Start time of the cheapest block tomorrow | `HH:MM` | — |
| `sensor.frank_most_expensive_tomorrow` | Most expensive block price of the entire day tomorrow | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_most_expensive_time_tomorrow` | Start time of the most expensive block tomorrow | `HH:MM` | — |
| `sensor.frank_prices_today` | Number of price blocks today (full series in attributes) | count | blocks |
| `sensor.frank_prices_tomorrow` | Number of price blocks tomorrow (full series in attributes) | count | blocks |
| `binary_sensor.frank_tomorrow_prices_available` | Whether tomorrow's prices have been published | on/off | — |

### Cheapest / most expensive price window sensors

For each day there's a matching pair of sensors, built from the same block:

**Price sensor** (`sensor.frank_cheapest_today`, `sensor.frank_most_expensive_today`, and the `*_tomorrow` variants):

- **State:** the block's `total_price_eur_kwh` (EUR/kWh).
- **Attributes:**
  - `time` — the block's local **start** time as `"HH:MM"` (e.g. `"19:45"`),
  - `timestamp` — the block's start as a local ISO datetime,
  - `end_timestamp` — the block's end as a local ISO datetime,
  - `duration_minutes` — the block length (15 or 60),
  - `full_block` — the full price breakdown.

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

The `*_tomorrow` sensors stay **unavailable** until Frank Energie publishes tomorrow's prices.

### Price block attributes

The `full_block` attribute (and each item in the `prices` series) has the following shape:

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

The `sensor.frank_prices_today` and `sensor.frank_prices_tomorrow` sensors expose the **full series** of price blocks for the entire day in their `prices` attribute, together with `resolution_minutes`, `cheapest_block`, `most_expensive_block`, `average_price`, `min_price`, and `max_price`. That makes them the convenient single source an EMS can plan against.

---

## Home Assistant Energy Dashboard

As of version `0.1.3`, the current-price sensors are compatible with the **Home Assistant Energy Dashboard**. This lets you link Frank Energie's **dynamic electricity price** — part of your **dynamic energy prices** — to both your grid consumption and your feed-in. You configure this via **Settings → Dashboards → Energy** in your electricity grid configuration.

**Quick overview — which entity goes where:**

```text
Track costs:
Use an entity with current price
→ Current price
→ sensor.frank_current_price

Export compensation:
Use an entity with current price
→ Current feed-in price
→ sensor.frank_current_return_price
```

> **Note — don't mix these up:**
> - `sensor.frank_current_price` is the **current electricity price** for electricity you **draw from the grid** (import).
> - `sensor.frank_current_return_price` is the **current feed-in compensation** for electricity you **feed back into the grid** (export).
> - Do **not** select `sensor.frank_current_price` as the feed-in compensation.
> - Do **not** select `sensor.frank_current_return_price` as the purchase price.

### Grid consumption

This is the **current electricity price** for electricity you **draw from the grid**. In your electricity grid configuration, under **Track costs**, choose:

```text
Use an entity with current price
```

Then select the entity shown as **Current price**:

```text
sensor.frank_current_price
```

This sensor is used for the **cost of electricity you draw from the grid** and holds the current purchase price (`total_price_eur_kwh`) as a numeric value in **EUR/kWh**, with the correct metadata (`device_class: monetary`), so the Home Assistant Energy Dashboard accepts it as a price entity. No `state_class` is deliberately set: this is a current price, not a cumulative total.

### Grid feed-in

This is the **current feed-in compensation** for electricity you **feed back into the grid**. In the same configuration, under **Export compensation**, choose:

```text
Use an entity with current price
```

Then select the entity shown as **Current feed-in price**:

```text
sensor.frank_current_return_price
```

This sensor is used for the **compensation for electricity you feed back into the grid** and holds the estimated current **feed-in price** as a numeric value in **EUR/kWh**.

Important to know:

- This sensor is an **estimate**, unless the Frank API offers an explicit feed-in-price field. On the public API that is currently **not** the case, so the value is calculated from the verified market-price field plus your configured feed-in adjustment.
- Contract terms can differ — always verify the value against your own Frank Energie contract.
- The feed-in adjustment can be **positive** (extra compensation), **negative** (a deduction or feed-in cost), or **zero**.
- The sensor applies **no** energy tax and **no** net metering.
- The calculation is independent of the phase-out of the Dutch net-metering scheme on January 1, 2027.

You change the feed-in adjustment and the VAT option via:

```text
Settings → Devices & Services → Frank Quarter Prices → Configure
```

The options dialog has two settings:

```text
Feed-in adjustment
Apply 21% VAT to feed-in price
```

The default feed-in adjustment is `0.0 EUR/kWh` and the VAT option is **off** by default, so existing installations keep showing the exact same value without reconfiguration.

The sensor also exposes a few stable attributes:

```yaml
market_price_source: market_price      # the verified price field used
market_price: 0.08000                  # the raw market price of the active block
feed_in_adjustment: 0.0                # the configured feed-in adjustment
calculation_method: market_price_plus_adjustment
```

### Feed-in price calculation example

The feed-in price is calculated based on the VAT option.

**Checkbox off (default):**

```text
feed_in_price = market_price + feed_in_adjustment
```

**Checkbox on:**

```text
feed_in_price = (market_price + feed_in_adjustment) × 1.21
```

So VAT is applied to the full compensation: the market price plus the configured feed-in adjustment.

Example with a positive adjustment (VAT off):

```text
Verified market price: 0.080 EUR/kWh
Configured adjustment: 0.018 EUR/kWh
Estimated feed-in price: 0.098 EUR/kWh
```

Example with a negative adjustment:

```text
Verified market price: 0.080 EUR/kWh
Configured adjustment:  -0.017 EUR/kWh
Estimated feed-in price: 0.063 EUR/kWh
```

The correct adjustment depends on your own contract. Both examples are purely illustrative and do **not** represent an actual Frank Energie contract. A negative feed-in price is possible and is not clamped to zero.

Example with **Apply 21% VAT to feed-in price** enabled:

```text
Verified market price: 0.00323 EUR/kWh
Configured adjustment: 0.01820 EUR/kWh
Estimated feed-in price: (0.00323 + 0.01820) × 1.21 = 0.0259303 EUR/kWh
```

About the VAT option:

- The option is **disabled by default**; leave it off and the calculation stays exactly as shown above, without VAT.
- **Verify yourself** in your own Frank Energie contract or statement whether your feed-in compensation is calculated including or excluding VAT — you remain responsible for the choice that fits your situation.
- Enabling or disabling it is **not** tied to the calendar year. The integration does **not** automatically turn VAT on in 2026 or off in 2027.
- VAT treatment and the net-metering scheme are **separate** matters. The phase-out of net metering does not automatically determine whether VAT applies.

> **About the price field used:** the public `marketPrices` query returns `marketPrice`, `marketPriceTax`, `sourcingMarkupPrice`, and `energyTaxPrice`. Verification against the live API showed that `marketPriceTax` is exactly 21% VAT on `marketPrice` (a cost on the *purchase* side) and that there is no explicit feed-in field. That's why the integration deliberately uses only the raw `marketPrice` (excluding VAT, energy tax, or sourcing markup) as the basis for the feed-in price.

---

## Handling tomorrow's prices

Frank Energie publishes the next day's prices in the early afternoon, shortly after the SDAC auction closes at 12:00 CET (in practice, **typically between 1 PM and 2 PM local time**). The integration handles this gracefully:

- Tomorrow's prices are requested **from 12:00 local time** onward. Any request before that is a guaranteed miss, so it isn't made.
- If they are **not yet available**:
  - the integration keeps `binary_sensor.frank_tomorrow_prices_available` **off**,
  - it leaves the `*_tomorrow` sensors **unavailable**,
  - it only logs an **info** message — an `UpdateFailed` is never raised and the integration is never marked as failed just because tomorrow is missing.
- Once published, `binary_sensor.frank_tomorrow_prices_available` turns **on** and tomorrow's sensors populate at the next quarter-hour refresh.
- Once a **full** day has been fetched, it is cached and not requested again. After midnight, the cached "tomorrow" becomes the new "today" without an extra request.

Use the binary sensor to gate automations that depend on tomorrow's prices until they're actually available.

---

## GraphQL API source

The prices are fetched from the public Frank Energie GraphQL API:

```
https://graphql.frankenergie.nl/
```

No authentication is required for market prices. The integration runs a query similar to:

```graphql
query MarketPrices($date: String!, $resolution: PriceResolution!) {
  marketPrices(date: $date, resolution: $resolution) {
    electricityPrices {
      from
      till
      resolution
      marketPrice
      marketPriceTax
      sourcingMarkupPrice
      energyTaxPrice
      perUnit
    }
  }
}
```

The integration requests `resolution: PT15M`, which returns **native quarter-hour prices (96 blocks per day)** — without authentication. The blocks are used exactly as returned and are never merged.

> **Important:** the `resolution: PriceResolution!` argument is what unlocks the quarter-hour data. Without it (or with `PT60M`), the same `marketPrices` query returns only **24 hourly blocks**, which is why the cheapest block used to jump to, for example, `14:00` instead of `13:45`. The `marketPricesElectricity(startDate, endDate)` query likewise only returns hourly data and is not used.

Requests use a 30-second timeout and are retried up to 3 times. Invalid records are validated and skipped. Belgium (BE) is supported by sending the `x-country: BE` header; the Netherlands (NL) is the default.

---

## ApexCharts dashboard

You can visualize the prices as a color-coded bar chart — **one bar per price block**. When Frank Energie returns native quarter-hour data you get **96 bars per day**; when only hourly data is available you get **24 bars**. The data is never merged.

![Frank electricity price today — quarter-hour bars colored green/orange/red based on price](images/apexcharts_today.png)

### Required frontend cards (HACS)

Install both via **HACS → Frontend**:

- **ApexCharts Card** — `RomRider/apexcharts-card`
- **Config Template Card** — `iantrich/config-template-card`

After installing, reload your browser (or clear the frontend cache) so the new card types become available.

### How it works

- The chart reads the **`prices`** attribute of `sensor.frank_prices_today` (or `sensor.frank_prices_tomorrow`).
- Each item in `attributes.prices` is plotted individually using its **`from`** timestamp (x-axis) and its **`total_price_eur_kwh`** value (y-axis).
- Because each bar carries its own timestamp, quarter-hour blocks are plotted exactly at `00:00`, `00:15`, `00:30`, … as returned — without rounding to the hour.
- The three **color thresholds** (green → orange → red) can be adjusted manually in the YAML, or driven by optional `input_number` helpers (`sensor.frank_green_threshold` / `sensor.frank_red_threshold`); the examples fall back to `0.12` and `0.25 €/kWh` when those helpers don't exist.

Ready-to-use files are available in [examples/](examples/):

- [examples/apexcharts_frank_prices_today.yaml](examples/apexcharts_frank_prices_today.yaml)
- [examples/apexcharts_frank_prices_tomorrow.yaml](examples/apexcharts_frank_prices_tomorrow.yaml)

### Today's chart

Add a new **Manual** dashboard card and paste:

```yaml
type: custom:config-template-card
variables:
  GREEN: "states['sensor.frank_green_threshold'] ? states['sensor.frank_green_threshold'].state : 0.12"
  RED: "states['sensor.frank_red_threshold'] ? states['sensor.frank_red_threshold'].state : 0.25"
entities:
  - sensor.frank_prices_today
card:
  type: custom:apexcharts-card
  graph_span: 24h
  span:
    start: day
  now:
    show: true
    label: Now
  experimental:
    color_threshold: true
  header:
    show: true
    title: Frank electricity price today (€/kWh)
  apex_config:
    chart:
      height: 320
    legend:
      show: false
    yaxis:
      min: 0
      decimalsInFloat: 3
      labels:
        formatter: |
          EVAL:function(val){ return "€ " + val.toFixed(3); }
    tooltip:
      x:
        format: dd MMM HH:mm
      "y":
        formatter: |
          EVAL:function(val){ return "€ " + val.toFixed(3) + " /kWh"; }
    dataLabels:
      enabled: false
    plotOptions:
      bar:
        columnWidth: 70%
        borderRadius: 2
  series:
    - entity: sensor.frank_prices_today
      name: Price
      type: column
      stroke_width: 0
      float_precision: 5
      color_threshold:
        - value: 0
          color: "#43a047"
        - value: ${Number(GREEN)}
          color: "#ffa600"
        - value: ${Number(RED)}
          color: "#db4437"
      data_generator: |
        return (entity.attributes.prices || [])
          .filter(r => r && r.from && r.total_price_eur_kwh !== null && r.total_price_eur_kwh !== undefined)
          .map(r => {
            const p = Number(String(r.total_price_eur_kwh).replace(',', '.'));
            return [new Date(r.from), isNaN(p) ? null : p];
          });
```

### Tomorrow's chart

Same style, but reads `sensor.frank_prices_tomorrow`. The card stays empty until Frank Energie publishes tomorrow's prices (typically between 1 PM and 2 PM local time).

> **Note on the span:** `apexcharts-card` has no reliable "tomorrow" span offset. The chart relies on the `data_generator`, which emits real timestamps from `attributes.prices`, so every bar is plotted at its correct absolute time regardless of the configured window. `span.offset: +24h` is added as a hint; if your version of the card ignores it, the bars are still shown at the correct times because every point carries its own `from` datetime.

```yaml
type: custom:config-template-card
variables:
  GREEN: "states['sensor.frank_green_threshold'] ? states['sensor.frank_green_threshold'].state : 0.12"
  RED: "states['sensor.frank_red_threshold'] ? states['sensor.frank_red_threshold'].state : 0.25"
entities:
  - sensor.frank_prices_tomorrow
card:
  type: custom:apexcharts-card
  graph_span: 24h
  span:
    start: day
    offset: +24h
  now:
    show: true
    label: Now
  experimental:
    color_threshold: true
  header:
    show: true
    title: Frank electricity price tomorrow (€/kWh)
  apex_config:
    chart:
      height: 320
    legend:
      show: false
    yaxis:
      min: 0
      decimalsInFloat: 3
      labels:
        formatter: |
          EVAL:function(val){ return "€ " + val.toFixed(3); }
    tooltip:
      x:
        format: dd MMM HH:mm
      "y":
        formatter: |
          EVAL:function(val){ return "€ " + val.toFixed(3) + " /kWh"; }
    dataLabels:
      enabled: false
    plotOptions:
      bar:
        columnWidth: 70%
        borderRadius: 2
  series:
    - entity: sensor.frank_prices_tomorrow
      name: Price
      type: column
      stroke_width: 0
      float_precision: 5
      color_threshold:
        - value: 0
          color: "#43a047"
        - value: ${Number(GREEN)}
          color: "#ffa600"
        - value: ${Number(RED)}
          color: "#db4437"
      data_generator: |
        return (entity.attributes.prices || [])
          .filter(r => r && r.from && r.total_price_eur_kwh !== null && r.total_price_eur_kwh !== undefined)
          .map(r => {
            const p = Number(String(r.total_price_eur_kwh).replace(',', '.'));
            return [new Date(r.from), isNaN(p) ? null : p];
          });
```

---

## EMS integration examples

Use the cheapest and most expensive price window to drive an energy management system (EMS), charging, or heavy appliances — think **charging a battery on cheap electricity**, **discharging a battery on expensive electricity**, and **energy arbitrage**. Every cheapest/most-expensive sensor exposes `timestamp` and `end_timestamp` attributes (local ISO datetimes) that are convenient for scheduling.

**Charge an EV during today's cheapest block:**

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

**Prevent the dishwasher from running during the daily peak:**

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

**Only react when the price is low enough (threshold):**

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

**Time until today's cheapest block:**

```yaml
{% set start = state_attr('sensor.frank_cheapest_today', 'timestamp') | as_datetime %}
{% if start %}
  {{ (start - now()).total_seconds() // 60 }} minutes
{% else %}
  unknown
{% endif %}
```

**Is the current price lower than today's average?**

```yaml
{% set avg = state_attr('sensor.frank_prices_today', 'average_price') %}
{% if avg is not none %}
  {{ states('sensor.frank_current_price') | float(0) < avg }}
{% else %}
  unknown
{% endif %}
```

**Cheapest price tomorrow (wait until published):**

```yaml
{% if is_state('binary_sensor.frank_tomorrow_prices_available', 'on') %}
  {{ states('sensor.frank_cheapest_tomorrow') }} €/kWh
{% else %}
  Tomorrow's prices not published yet
{% endif %}
```

---

## Brand assets (integration icon)

This integration ships with neutral, custom-made icon and logo assets (a lightning bolt for a quarter-hour clock, in a cloud-blue style). The **ready-to-use PNG files** are located under [custom_components/frank_quarter_prices/brand/](custom_components/frank_quarter_prices/brand/):

- `icon.png` — 256×256
- `icon@2x.png` — 512×512
- `logo.png` — 256×256
- `logo@2x.png` — 512×512

The editable source files (SVG) are located under [custom_components/frank_quarter_prices/icons/](custom_components/frank_quarter_prices/icons/) (`icon.svg`, `logo.svg`). None of this material uses Frank Energie's official logo or any trademark.

### The icon shows up everywhere (Home Assistant 2026.3+)

Since **Home Assistant 2026.3**, custom integrations load their own brand assets directly from a local `brand/` folder inside the integration — a PR to the [home-assistant/brands](https://github.com/home-assistant/brands) repository is **no longer** required. Local brand images even take **priority** over the central Brands repository. This integration already includes that folder ([custom_components/frank_quarter_prices/brand/](custom_components/frank_quarter_prices/brand/)), so the icon shows up automatically everywhere — both on the integration card and in the **integrations list**.

> **Still seeing *"icon not available"*?** Restart Home Assistant (or reload the integration) and clear your browser cache if needed. The images are served via `/api/brands/integration/frank_quarter_prices/icon.png`. On Home Assistant versions older than 2026.3, the list shows a generic placeholder image until you upgrade; this is purely cosmetic and doesn't affect functionality.

> **Contributing to Home Assistant Core?** Only if this integration is ever merged into HA core should the local `brand/` files be removed and instead submitted via a PR to the [home-assistant/brands](https://github.com/home-assistant/brands) repository (folder `custom_integrations/frank_quarter_prices/`).

---

## Troubleshooting

- **Entities show `unavailable`:**
  - For the tomorrow / cheapest-tomorrow sensors, this is expected before Frank Energie publishes the next day (typically between 1 PM and 2 PM local time). Check `binary_sensor.frank_tomorrow_prices_available`.
  - For all sensors: check that the integration is loaded under **Settings → Devices & Services**.
- **Entity IDs don't match this README:** see the note under [Configuration](#configuration) — adjust them to the IDs shown in **Developer Tools → States**.
- **No data at all:** check that Home Assistant has outbound internet access to `https://graphql.frankenergie.nl/`.
- **Enable debug logging** by adding this to `configuration.yaml` and restarting:

  ```yaml
  logger:
    default: warning
    logs:
      custom_components.frank_quarter_prices: debug
  ```

- **Diagnostics:** open the device page → **⋮ → Download diagnostics** and attach the (secrets-redacted) file to any bug report.

---

## Frequently asked questions

**Does Frank Energie work with Home Assistant?**
Yes, through this independent custom integration. It exposes the public Frank Energie GraphQL market prices as Home Assistant sensors at quarter-hour resolution.

**Can I install this integration through HACS?**
Yes. The integration is in **HACS Default**, so it's directly searchable under **HACS → Integrations** — adding a custom repository isn't needed. See [Installation](#installation).

**Do I need a Frank Energie account or API token?**
No. Market prices are public and require no authentication.

**Does this show my personal contract or usage costs?**
No. It shows the market-price components (market price, tax, sourcing markup, energy tax). Your actual tariff may differ depending on your contract.

**What resolution do the prices have?**
Native quarter-hour prices (15 minutes, **96 blocks per day**) — the integration requests `resolution: PT15M` via the public `marketPrices` query. If Frank Energie has no quarter-hour data for a given day, hourly data (60 minutes, 24 blocks) is returned instead. The blocks are used exactly as returned and are never merged, so the cheapest/most-expensive times reflect the exact quarter-hour start (e.g. `13:45`).

**How often is it updated?**
Every quarter hour, synchronized with the real quarter-hour boundaries (`:00`/`:15`/`:30`/`:45`). The active quarter-hour price is recalculated locally from the cached daily series; a request to the API is only made for a day that's still missing.

**Why is tomorrow empty in the morning?**
Frank Energie publishes the next day's prices in the early afternoon (typically between 1 PM and 2 PM local time). The integration requests them starting at 12:00 local time. The `*_tomorrow` sensors stay unavailable until then, and the integration never raises an error in the meantime.

**Does it support Belgium?**
Yes — the Netherlands (NL) is the default; Belgian (BE) prices are requested via the `x-country` header.

**Can I use the quarter-hour prices for a home battery?**
Yes. The cheapest and most expensive price-window sensors (with `timestamp` and `end_timestamp`) are designed to align a home battery's charge and discharge moments. See [EMS integration examples](#ems-integration-examples).

**Can I use Frank Quarter Prices in an EMS?**
Yes. The `sensor.frank_prices_today` and `sensor.frank_prices_tomorrow` sensors expose the full quarter-hour series (with resolution, average, min, and max price) as an attribute, so an external or self-built Energy Management System can plan directly against it.

**Is this an official Frank Energie integration?**
No, this is an independent community project. See the [disclaimer](#disclaimer).

---

## Contributing

Contributions are welcome! Feel free to open an [issue](https://github.com/Bennie-JC/ha-frank-quarter-prices/issues) or submit a pull request. For larger changes, please open an issue first to discuss what you'd like to change.

---

## Disclaimer

This project is **not affiliated with, endorsed by, or supported by Frank Energie**. It uses a publicly accessible API and is provided "as is", without any warranty. Prices shown may differ from your actual contract prices. Use at your own risk.

---

## License

Distributed under the terms of the [LICENSE](LICENSE) file in this repository.
