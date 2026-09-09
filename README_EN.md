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

The integration provides the full quarter-hour prices for **today** and, once published, **tomorrow**, together with the current purchase price, the current feed-in price, the cheapest and most expensive price window of the day, and today's configurable **cheap and expensive price zone**. The sensors are ready to use in **dashboards**, **automations**, for **home batteries**, and in your own **Energy Management System (EMS)** — well suited for anyone acting on **dynamic electricity prices**.

The integration is included in **HACS Default**, so it's directly searchable and installable through HACS without adding a custom repository.

> This integration reads the public Frank Energie GraphQL API and exposes today's and tomorrow's prices, the current price, and the cheapest and most expensive price window of each day. The active quarter-hour price is recalculated on every real quarter-hour boundary (`:00`/`:15`/`:30`/`:45`); the daily price series themselves are cached locally and only fetched when missing. The full price series are available as sensor attributes for your own EMS logic, battery control, and dynamic electricity tariffs.

---

## Table of Contents

- [Features](#features)
- [Installation](#installation)
  - [HACS installation (recommended)](#hacs-installation-recommended)
  - [Manual installation](#manual-installation)
- [Configuration](#configuration)
  - [Settings](#settings)
- [Sensors created](#sensors-created)
  - [Sensor overview](#sensor-overview)
  - [Cheapest / most expensive price window sensors](#cheapest--most-expensive-price-window-sensors)
  - [Price zones (cheap / expensive)](#price-zones-cheap--expensive)
  - [Optimal periods (cheap / expensive)](#optimal-periods-cheap--expensive)
  - [Price block attributes](#price-block-attributes)
- [Home Assistant Energy Dashboard](#home-assistant-energy-dashboard)
  - [Grid consumption](#grid-consumption)
  - [Grid feed-in](#grid-feed-in)
- [Price zone dashboard](#price-zone-dashboard)
- [Handling tomorrow's prices](#handling-tomorrows-prices)
- [GraphQL API source](#graphql-api-source)
- [ApexCharts dashboard](#apexcharts-dashboard)
- [EMS integration examples](#ems-integration-examples)
- [Example Home Assistant templates](#example-home-assistant-templates)
- [Troubleshooting](#troubleshooting)
- [Frequently asked questions](#frequently-asked-questions)
- [Contributing](#contributing)
- [Disclaimer](#disclaimer)
- [License](#license)

---

## Features

- ⚡ **Quarter-hour prices** — full 15-minute market price resolution (with automatic fallback to 60-minute data when that's what Frank Energie publishes).
- 📅 **Today & tomorrow** — both days are fetched automatically and cached locally; tomorrow's prices appear as soon as they're published (typically between 13:00 and 14:00 market-local time).
- 💶 **Current price sensor** — the currently active price block, with the full price breakdown as attributes.
- 📉 Sensors for the **cheapest and most expensive** price window (price + start time) for the **entire day**, for both today and tomorrow.
- 🏷️ **Price zones** — today's longest contiguous cheap and expensive period, with start/end sensors (real timestamps) and binary sensors telling you whether you are inside that period right now. Both margins are configurable (15% by default).
- 🎯 **Optimal periods** (optional, off by default) — the cheapest or most expensive contiguous period of **exactly** the duration you set (120 minutes, say), for today *and* tomorrow. Ideal for running a washing machine, heat pump or home battery at the best possible moment.
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

All entities are grouped under a single **Frank** device. The integration uses entity IDs of the form `sensor.frank_<name>`, for example `sensor.frank_current_price`. The examples in this README use those IDs directly — you can verify them via **Developer Tools → States** on your own system.

Adding the integration only asks for the **country** (NL or BE). No account, token or password is required.

### Settings

Every other setting is changed afterwards via:

```text
Settings → Devices & Services → Frank Quarter Prices → Configure
```

| Setting | Default | Range | Meaning |
| --- | --- | --- | --- |
| **Feed-in adjustment** | `0.0 EUR/kWh` | −1.0 … 1.0, step 0.001 | Amount added to the market price to estimate your feed-in price. Positive = extra compensation, negative = a deduction. |
| **Apply 21% VAT to feed-in price** | off | on/off | Calculates the feed-in price including 21% VAT, applied to the market price *plus* the feed-in adjustment. |
| **Cheap price-zone margin** | `15%` | 0 … 49%, step 1% | How much of the day's price range, measured up from the cheapest quarter, still counts as cheap. |
| **Expensive price-zone margin** | `15%` | 0 … 49%, step 1% | How much of the day's price range, measured down from the most expensive quarter, still counts as expensive. |
| **Enable optimal cheap period** | off | on/off | Makes the entities for the cheapest contiguous period available. Never switched on? Then they are not created at all. Switch the feature off again later and entities created earlier stay as `unavailable`, so entity IDs and customizations are preserved. |
| **Optimal cheap period duration** | `120 min` | 15 … 720 min, step 15 | The exact length of that period. Whole minutes on the 15-minute step only; anything else is refused. |
| **Enable optimal expensive period** | off | on/off | The same for the most expensive contiguous period: never enabled means no entities, disabling later leaves them as `unavailable`. |
| **Optimal expensive period duration** | `120 min` | 15 … 720 min, step 15 | The exact length of that period. Whole minutes on the 15-minute step only; anything else is refused. |

The form is deliberately one clear list in three logical groups: the feed-in settings first, then the two zone margins, then the two optional optimal periods with their own duration directly beneath each toggle.

Both zone margins **default to 15%** and are freely configurable between 0 and 49% — 15% is not a fixed rule, only the starting value.

The margin is a percentage of the **day's own price range** — its most expensive quarter minus its cheapest — and not of the price in euros. At the default 15%, a quarter counts towards the cheap zone as long as it sits no more than 15% of that daily range above the lowest price. The **longest contiguous run** of those quarters forms the zone. The expensive zone mirrors this, measured from the day's most expensive quarter price.

The maximum is 49% rather than 50% so the cheap and expensive zones can never overlap: together they always stay below 100% of the daily range, so no quarter can be both cheap and expensive.

Change a margin and the zone sensors, the binary sensors and the dashboard follow automatically. Home Assistant reloads the integration to apply it — as it does for any option change — after which today's prices (and tomorrow's, past 12:00 market-local time) are fetched once more. The zone calculation itself is pure local arithmetic and issues no request of its own.

> Existing installations need to do nothing. A configuration without these settings automatically uses the defaults; re-adding the integration is not necessary.

---

## Sensors created

By default the integration creates exactly **19 entities**, tailored for use within an EMS. Enable one of the [optimal periods](#optimal-periods-cheap--expensive) and each feature adds three more: 22 with one feature on, 25 with both. Switch such a feature off again afterwards and those entities remain but become `unavailable` — see [Optimal periods](#optimal-periods-cheap--expensive).

For each day, the integration requests **all** electricity price blocks from Frank Energie (local 00:00 → 24:00) and determines the single cheapest and single most expensive block of that **entire day**, at the raw resolution Frank returns (15 minutes or hourly). There is no filtering to the next 24/48 hours, no filtering to only the current time, no filtering to only the future, and no hourly averaging applied.

### Sensor overview

| Entity | Description | State | Unit |
| --- | --- | --- | --- |
| `sensor.frank_current_price` | Dynamic purchase price ("marktprijs+") of the currently active block | `market_price + market_price_tax + sourcing_markup_price` | EUR/kWh |
| `sensor.frank_current_return_price` | Estimated current electricity feed-in price, based on the verified Frank market-price field and the configured feed-in adjustment | calculated price | EUR/kWh |
| `sensor.frank_cheapest_today` | Cheapest block price of the entire day today | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_cheapest_time_today` | Start time of the cheapest block today | `HH:MM` | — |
| `sensor.frank_most_expensive_today` | Most expensive block price of the entire day today | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_most_expensive_time_today` | Start time of the most expensive block today | `HH:MM` | — |
| `sensor.frank_cheapest_tomorrow` | Cheapest block price of the entire day tomorrow | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_cheapest_time_tomorrow` | Start time of the cheapest block tomorrow | `HH:MM` | — |
| `sensor.frank_most_expensive_tomorrow` | Most expensive block price of the entire day tomorrow | `total_price_eur_kwh` | EUR/kWh |
| `sensor.frank_most_expensive_time_tomorrow` | Start time of the most expensive block tomorrow | `HH:MM` | — |
| `sensor.frank_cheap_zone_start_today` | Start of today's cheap price zone | timestamp | — |
| `sensor.frank_cheap_zone_end_today` | End of today's cheap price zone | timestamp | — |
| `sensor.frank_expensive_zone_start_today` | Start of today's expensive price zone | timestamp | — |
| `sensor.frank_expensive_zone_end_today` | End of today's expensive price zone | timestamp | — |
| `sensor.frank_prices_today` | Number of price blocks today (full series in attributes) | count | blocks |
| `sensor.frank_prices_tomorrow` | Number of price blocks tomorrow (full series in attributes) | count | blocks |
| `binary_sensor.frank_cheap_period` | Whether electricity is cheap right now (inside the cheap price zone) | on/off | — |
| `binary_sensor.frank_expensive_period` | Whether electricity is expensive right now (inside the expensive price zone) | on/off | — |
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

### Price zones (cheap / expensive)

Where the sensors above point at the *single* cheapest and most expensive quarter, the price zones give you the **whole period** in which electricity is cheap respectively expensive. That is what you need to run a boiler, washing machine or home battery for a stretch at a time.

**How a zone is determined:**

1. The integration first works out the **price range of the entire day**: its most expensive quarter price minus its cheapest.
2. The configured margin — **15%** by default — is a percentage of *that range*, measured from the respective extreme:

   ```text
   daily range        = highest price − lowest price
   cheap threshold    = lowest price  + daily range × margin%
   expensive threshold= highest price − daily range × margin%
   ```

   For example: lowest price `0.10`, highest price `0.30`, so a daily range of `0.20`. At 15% the cheap threshold is `0.10 + 0.20 × 0.15 = 0.13` and the expensive threshold is `0.30 − 0.20 × 0.15 = 0.27`.

3. Every quarter meeting that threshold is a candidate.
4. The zone is the **longest contiguous run** of candidates. Isolated cheap quarters elsewhere in the day are therefore not pulled in: if 03:00–03:15 is cheap and 12:30–15:15 is contiguously cheap, the zone is `12:30–15:15` and not `03:00–15:15`.
5. If two runs are exactly the same length, the **earliest** one wins.

Because the margin is measured against the daily range and is capped at 49%, the two thresholds always stay apart. A quarter can therefore never be marked as both cheap and expensive, and the two zones cannot overlap.

The calculation uses the price blocks' real start and end timestamps, so the daylight-saving transition days (92 or 100 quarters) work exactly like an ordinary 96-quarter day.

**A price zone is only published for a complete day.** A zone makes a claim about the whole day ("today's cheapest contiguous block"), and that cannot be answered from the morning alone. While today's price series is incomplete — shortly after a restart, say, or when Frank publishes the day in parts — all six zone entities stay **unavailable** rather than showing a misleading zone derived from half a day. They appear by themselves once the day is complete. Once a complete day is known, the zones keep working from that cached day even while the Frank API is down.

Completeness is measured against the real **market-day** span (midnight to midnight in the market's own timezone: `Europe/Amsterdam` for NL, `Europe/Brussels` for BE), not against a fixed block count — which is why the 92- and 100-quarter daylight-saving days validate correctly too. The timezone configured in Home Assistant plays no part: run Home Assistant in UTC or anywhere else and the Frank market day stays exactly the same.

**If every quarter of the day has exactly the same price**, there is no cheap-versus-expensive distinction to draw. In that rare case all six zone entities stay unavailable rather than calling the whole day both cheap and expensive.

**Start and end sensors:**

- **State:** a full, timezone-aware **timestamp** (`device_class: timestamp`) — directly usable in an automation trigger, with no string parsing.
- **Attributes:** `time` (the familiar `"HH:MM"` rendering), `zone_start`, `zone_end`, `margin_percent`, `threshold_eur_kwh`, `day_min_price`, `day_max_price`, `zone_duration_minutes`, `quarter_count`.

**Binary sensors** `binary_sensor.frank_cheap_period` and `binary_sensor.frank_expensive_period`:

- **On** while the current moment falls inside the zone, following `start <= now < end` — so the zone ends precisely at its end boundary. The comparison is between absolute instants, so your Home Assistant timezone plays no part.
- **Unavailable** when no zone can be determined for today. They never show a stale zone from yesterday.
- **Attributes:** `zone_start`, `zone_end`, `threshold_eur_kwh`, `margin_percent`.

Example:

```text
sensor.frank_cheap_zone_start_today = 2026-08-06T12:30:00+02:00
  attributes:
    time: "12:30"
    zone_start: "2026-08-06T12:30:00+02:00"
    zone_end: "2026-08-06T15:15:00+02:00"
    margin_percent: 15.0
    threshold_eur_kwh: 0.148
    zone_duration_minutes: 165
    quarter_count: 11

binary_sensor.frank_cheap_period = on
```

The zones are derived **locally** from the price series that has already been fetched. They cost not a single extra API request and use the same quarter-boundary refresh as the rest of the integration.

### Optimal periods (cheap / expensive)

This is an **optional** feature, **off** by default. Enable it and each feature adds three entities.

#### Price zone or optimal period — what's the difference?

The two answer a different question, which is exactly why both exist:

| | Question answered | Length of the result | Configured with |
| --- | --- | --- | --- |
| **Price zone** | *Which contiguous part of the day falls inside my cheap/expensive threshold?* | Variable — whatever the day happens to produce | **Margin** in % |
| **Optimal period** | *Which contiguous period of exactly X minutes has the lowest/highest average price?* | Always exactly the duration you set | **Duration** in minutes |

The two features are completely **independent**. An optimal period looks only at the actual prices and the configured duration; it does **not** use the zone margin. Move the cheap-zone margin from 15% to 40% and your 120-minute optimal period does not shift by a single minute. The same holds in reverse: changing a duration never moves a zone boundary.

The practical consequence: an optimal period may lie partly or even entirely **outside** the price zone. Ask for 4 contiguous hours while the cheap zone only lasts 2, and the integration searches the whole day for the cheapest 4 hours — the only honest way to answer that question.

#### How the period is determined

1. The integration considers **every** contiguous run of price blocks whose real duration equals the configured duration **exactly**.
2. Each candidate is scored on the duration-**weighted average** of `total_price_eur_kwh`. With the usual quarter-hour blocks that is simply the arithmetic mean; the weighting makes hourly data score correctly too.
3. The **cheap** period is the candidate with the lowest average, the **expensive** one the highest.
4. If two candidates score exactly the same, the **earliest** always wins — for both variants.

A few deliberate choices:

- **Genuinely contiguous.** Price blocks are never split, merged or skipped. An expensive quarter in the middle of a cheap period counts in full; it is not left out to flatter the average.
- **Exactly the requested duration.** Ask for 120 minutes and you never get 105. If the duration does not fit the day's blocks — 90 minutes on a day where Frank publishes only **hourly** prices, for instance — the sensors stay **unavailable**. The integration would rather invent no prices at all than fill in half an hour that was never published. On quarter-hour data every configurable value works, since they are all multiples of 15 minutes.
- **An unusable configured duration is never silently replaced.** The setting only accepts a whole number of minutes from 15 to 720 in steps of 15; anything else is refused by the form. If an unusable value ends up stored anyway by hand-editing the configuration (`0`, `-15` or `17`, say), the matching entities stay **unavailable** and a warning appears in the log — once per distinct offending value, so the log does not fill up every quarter while a corrected but still unusable value is reported again. The integration deliberately plans nothing rather than quietly carrying on with the 120-minute default — an automation would otherwise run on a duration you never set and cannot see anywhere. A *missing* setting is a different matter: that simply falls back to the 120-minute default.
- **Negative prices count normally.** The cheapest period naturally picks the most negative average; if the whole day is negative, the most expensive period is the least negative one. Nothing is clamped and no absolute values are used.
- **A flat day does yield a period.** Unlike the price zones: when every price is exactly equal there is no cheap-versus-expensive distinction and the zones stay unavailable — but "the cheapest contiguous 2 hours" still has a valid answer, and that is the earliest one.
- **Complete days only.** As with the zones, nothing is published while the day is incomplete; the 92- and 100-quarter daylight-saving days work just as well as an ordinary day.

#### Entities

These entities are **only created once you enable the feature**. Leave it off and they do not exist at all — you never see a trace of them.

Switch a feature back **off** later and the entities stay, becoming `unavailable`. That is deliberate: it keeps every customization of your own — a changed entity ID, name, icon, area, labels, or a hidden/disabled entity — completely intact, and it leaves an automation referring to the entity with a state it can actually react to instead of silently doing nothing. Switch the feature on again and exactly the same entity comes back: same entity ID, same unique ID, same customizations, and never a `_2` suffix, however often you toggle it.

If you want such a leftover entity gone for good, delete it **while the feature is switched off**, via **Settings → Devices & Services → Frank Quarter Prices → entity → delete**. It then stays gone. Deleting it while the feature is *on* achieves nothing: the integration simply recreates it on the next restart or option change. And if you enable the feature again later, the entity naturally comes back too.

| Entity | Description | State |
| --- | --- | --- |
| `sensor.frank_optimal_cheap_period_today` | Today's cheapest period | timestamp (start) |
| `sensor.frank_optimal_cheap_period_tomorrow` | Tomorrow's cheapest period | timestamp (start) |
| `binary_sensor.frank_optimal_cheap_period` | Whether you are inside today's cheapest period right now | on/off |
| `sensor.frank_optimal_expensive_period_today` | Today's most expensive period | timestamp (start) |
| `sensor.frank_optimal_expensive_period_tomorrow` | Tomorrow's most expensive period | timestamp (start) |
| `binary_sensor.frank_optimal_expensive_period` | Whether you are inside today's most expensive period right now | on/off |

The sensors' **state** is the period's **start** as a full timestamp (`device_class: timestamp`), matching the zone boundaries — directly usable in an automation trigger, with no text to parse. The price rides along as an attribute.

**Period sensor attributes:** `start`, `end`, `start_time` and `end_time` (the familiar `"HH:MM"` rendering), `duration_minutes`, `average_price_eur_kwh`, `min_price_eur_kwh`, `max_price_eur_kwh`, `block_count` and `resolution_minutes`.

**The binary sensors** are **on** while `start <= now < end`, and **unavailable** when no period can be determined for today — never a stale period from yesterday, and never `off` where "unknown" is meant. Their attributes are `start`, `end`, `duration_minutes` and `average_price_eur_kwh`.

The `*_tomorrow` sensors stay unavailable until Frank publishes tomorrow's prices, then appear on their own. At midnight tomorrow's period becomes today's period without any extra request.

Example:

```text
sensor.frank_optimal_cheap_period_today = 2026-08-06T10:00:00+02:00
  attributes:
    start: "2026-08-06T10:00:00+02:00"
    end: "2026-08-06T12:00:00+02:00"
    start_time: "10:00"
    end_time: "12:00"
    duration_minutes: 120
    average_price_eur_kwh: 0.146
    min_price_eur_kwh: 0.146
    max_price_eur_kwh: 0.146
    block_count: 8
    resolution_minutes: 15

binary_sensor.frank_optimal_cheap_period = on
```

Automation example — start the washing machine when today's cheapest period begins:

```yaml
automation:
  - alias: "Washing machine during the cheapest period"
    trigger:
      - platform: state
        entity_id: binary_sensor.frank_optimal_cheap_period
        to: "on"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.washing_machine
```

Like the price zones, the optimal periods are derived **locally** from the price series that has already been fetched: the calculation costs **zero** extra API requests, and adds no second coordinator, no extra timer and no fetch of its own. Enabling one or changing a setting does still make Home Assistant reload the integration — as it does for any option change — after which today's prices (and tomorrow's, past 12:00 market-local time) are fetched once more.

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

The `sensor.frank_prices_today` and `sensor.frank_prices_tomorrow` sensors expose the **full series** of price blocks for the entire day in their `prices` attribute, together with `resolution_minutes`, `cheapest_block`, `most_expensive_block`, `average_price`, `min_price`, and `max_price`. That makes them the convenient single source an EMS can plan against. `sensor.frank_prices_tomorrow` adds `available` and `last_attempt` on top of those.

> **About the database (Recorder).** The full daily series is roughly 25 kB, which exceeded the 16384-byte limit Home Assistant applies to attributes stored in history. That produced the warning *"State attributes for sensor.frank_prices_today exceed maximum size of 16384 bytes"* on every state change, after which the Recorder skipped **all** attributes of that state. The `prices` attribute is therefore no longer stored in the database. Nothing changes for your dashboards, templates, automations or EMS: `state_attr('sensor.frank_prices_today', 'prices')` still returns the complete, live series. Only the historical storage of that one attribute is dropped — precisely the history the Recorder was already refusing to keep. The small summary attributes beside it are now stored properly again.

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
Use an entity with current rate
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

This sensor is used for the **cost of electricity you draw from the grid**. Its state holds the current **marktprijs+** (dynamic) purchase price — exactly what Frank Energie itself bills as **"the dynamic part"** ("het dynamische deel") in its app and on the invoice:

```text
marktprijs+ = market_price + market_price_tax + sourcing_markup_price
```

which is the all-in price **minus the energy tax**.

> **Why all three components?** The VAT basis differs per field. `market_price` is the raw market price **excluding** VAT; its 21% VAT arrives separately as `market_price_tax`. `sourcing_markup_price` (the sourcing markup) already **includes** VAT — in the Netherlands `0.01815`, which is `0.015` excluding VAT. Adding only the market price and the markup would therefore add a VAT-exclusive amount to a VAT-inclusive one and understate the result by the VAT on the market price. All three components come from the API per quarter-hour, so no VAT rate, markup or tax amount is hard-coded.

**The energy tax is not included**, so this is not a complete consumer price. The complete all-in price remains available on the same entity as `full_block.total_price_eur_kwh`, and the cheapest/most-expensive and daily-array sensors still use the all-in basis `total_price_eur_kwh`. With the correct metadata (`device_class: monetary`) the Home Assistant Energy Dashboard accepts it as a price entity. No `state_class` is deliberately set: this is a current price, not a cumulative total.

### Grid feed-in

This is the **current feed-in compensation** for electricity you **feed back into the grid**. In the same configuration, under **Export compensation**, choose:

```text
Use an entity with current rate
```

Then select the entity shown as **Current feed-in price**:

```text
sensor.frank_current_return_price
```

This sensor is used for the **compensation for electricity you feed back into the grid** and holds the estimated current **feed-in price** as a numeric value in **EUR/kWh**.

**How the value is derived:**

```text
feed_in_price = market_price + feed_in_adjustment
```

and with **Apply 21% VAT to feed-in price** enabled:

```text
feed_in_price = (market_price + feed_in_adjustment) x 1.21
```

So VAT is applied to the full compensation: the market price plus the configured adjustment. Both settings live under [Configuration -> Settings](#settings); by default the adjustment is `0.0` and the VAT option is off, so existing installations keep showing the exact same value without reconfiguration.

The sensor exposes a few stable attributes:

```yaml
market_price_source: market_price      # the verified price field used
market_price: 0.08000                  # the raw market price of the active block
feed_in_adjustment: 0.0                # the configured feed-in adjustment
apply_vat: false                       # whether the VAT option is enabled
vat_rate: 0.21                         # the VAT rate applied
calculation_method: market_price_plus_adjustment
```

`calculation_method` becomes `market_price_plus_adjustment_including_vat` as soon as the VAT option is enabled.

Important to know:

- This sensor is an **estimate**. The public Frank API offers no explicit feed-in-price field, so the value is calculated from the raw market price plus your configured adjustment. Verify it against your own Frank Energie contract; the correct adjustment depends on that contract.
- The adjustment can be **positive** (extra compensation), **negative** (a deduction or feed-in cost), or **zero**. A negative feed-in price is possible and is not clamped to zero.
- The sensor applies **no** energy tax, **no** sourcing markup and **no** net metering, and is not tied to the calendar year or to the phase-out of the Dutch net-metering scheme on January 1, 2027.

> **About the price field used:** the public `marketPrices` query returns `marketPrice`, `marketPriceTax`, `sourcingMarkupPrice`, and `energyTaxPrice`. Verification against the live API showed that `marketPriceTax` is exactly 21% VAT on `marketPrice`, and that `sourcingMarkupPrice` (the sourcing fee) is a fixed amount that adds into the all-in **purchase** price. There is no explicit feed-in field. That's why the integration deliberately uses only the raw `marketPrice` -- excluding VAT, energy tax and sourcing markup -- as the basis for the feed-in price.

---

## Price zone dashboard

A ready-made card showing today's cheap and expensive price zone. The integration calculates, the dashboard only displays — no price arithmetic is done in Jinja any more.

![Frank price zones — today's cheap and expensive period, with threshold price and configured margin](images/frank-price-zones-dashboard.png)

The percentages and thresholds shown come straight from the zone sensors' attributes. **The margin defaults to 15%**, but that is only the default: change it per zone under **Settings → Devices & Services → Frank Quarter Prices → Configure**. Set the cheap margin to 20% and the expensive one to 10%, and the card shows that automatically — nothing is hard-coded in the YAML.

> **`card-mod` is optional** and used purely for styling — the colours, the rounding and the font sizes. Without it the card still works and the times stay large (they are markdown headings); simply omit the `card_mod` blocks. The integration does the calculating either way; the dashboard only displays.

Add a new **Manual** dashboard card and paste:

```yaml
type: vertical-stack
cards:
  - type: heading
    heading: Frank Energie
    heading_style: title
    icon: mdi:information-outline

  - type: markdown
    content: |-
      {% set low_start = states('sensor.frank_cheapest_time_today') %}
      {% set low_end = state_attr('sensor.frank_cheapest_today', 'end_timestamp') %}
      {% set high_start = states('sensor.frank_most_expensive_time_today') %}
      {% set high_end = state_attr('sensor.frank_most_expensive_today', 'end_timestamp') %}
      {% set unusable = ['unknown', 'unavailable', 'none', ''] %}
      {% if low_start not in unusable and low_end and high_start not in unusable and high_end %}
      Today the price per kWh is lowest between **{{ low_start }}** and **{{ (low_end | as_datetime | as_local).strftime('%H:%M') }}**, and highest between **{{ high_start }}** and **{{ (high_end | as_datetime | as_local).strftime('%H:%M') }}**.
      {% else %}
      Today's prices are not available yet.
      {% endif %}

  - type: markdown
    content: |-
      {% set sensor = 'sensor.frank_cheap_zone_start_today' %}
      {% set start = state_attr(sensor, 'time') %}
      {% set end = state_attr('sensor.frank_cheap_zone_end_today', 'time') %}
      {% set threshold = state_attr(sensor, 'threshold_eur_kwh') %}
      {% set margin = state_attr(sensor, 'margin_percent') %}
      ### 🏷️ Cheap price zone today
      {% if start and end and threshold is not none %}
      # {{ start }} – {{ end }}
      ## ≤ € {{ '%.3f' | format(threshold | float(0)) }}/kWh

      Within {{ margin | float(0) | round(0) | int }}% of the daily price range above the cheapest quarter of the day.
      {% else %}
      Not available yet.
      {% endif %}
    card_mod:
      style:
        ha-markdown $: |
          h3 { font-size: 21px; font-weight: 600; margin: 0; }
          h1 { font-size: 38px; font-weight: 700; line-height: 1.15; margin: 6px 0 0 0; }
          h2 { font-size: 20px; font-weight: 500; margin: 2px 0 0 0; opacity: 0.9; }
          p  { font-size: 14px; margin: 6px 0 0 0; opacity: 0.7; }
        .: |
          ha-card {
            border-radius: 18px;
            padding: 12px 18px;
            background: rgba(50, 180, 90, 0.10);
            border: 1px solid rgba(50, 180, 90, 0.28);
          }

  - type: markdown
    content: |-
      {% set sensor = 'sensor.frank_expensive_zone_start_today' %}
      {% set start = state_attr(sensor, 'time') %}
      {% set end = state_attr('sensor.frank_expensive_zone_end_today', 'time') %}
      {% set threshold = state_attr(sensor, 'threshold_eur_kwh') %}
      {% set margin = state_attr(sensor, 'margin_percent') %}
      ### 📈 Expensive price zone today
      {% if start and end and threshold is not none %}
      # {{ start }} – {{ end }}
      ## ≥ € {{ '%.3f' | format(threshold | float(0)) }}/kWh

      Within {{ margin | float(0) | round(0) | int }}% of the daily price range below the most expensive quarter of the day.
      {% else %}
      Not available yet.
      {% endif %}
    card_mod:
      style:
        ha-markdown $: |
          h3 { font-size: 21px; font-weight: 600; margin: 0; }
          h1 { font-size: 38px; font-weight: 700; line-height: 1.15; margin: 6px 0 0 0; }
          h2 { font-size: 20px; font-weight: 500; margin: 2px 0 0 0; opacity: 0.9; }
          p  { font-size: 14px; margin: 6px 0 0 0; opacity: 0.7; }
        .: |
          ha-card {
            border-radius: 18px;
            padding: 12px 18px;
            background: rgba(220, 60, 60, 0.09);
            border: 1px solid rgba(220, 60, 60, 0.25);
          }
```

While the zone sensors are unavailable the cards show "Not available yet" instead of a template error.

---

## Handling tomorrow's prices

Frank Energie publishes the next day's prices in the early afternoon, shortly after the SDAC auction closes at 12:00 CET (in practice, **typically between 13:00 and 14:00 market-local time**). Every time below is **market-local** — `Europe/Amsterdam` for NL, `Europe/Brussels` for BE — and therefore independent of the timezone Home Assistant is configured for. The integration handles this gracefully:

- Tomorrow's prices are requested **from 12:00 market-local time** onward. Any request before that is a guaranteed miss, so it isn't made.
- If they are **not yet available**:
  - the integration keeps `binary_sensor.frank_tomorrow_prices_available` **off**,
  - it leaves the `*_tomorrow` sensors **unavailable**,
  - it only logs an **info** message — an `UpdateFailed` is never raised and the integration is never marked as failed just because tomorrow is missing.
- Once published, `binary_sensor.frank_tomorrow_prices_available` turns **on** and tomorrow's sensors populate at the next quarter-hour refresh.
- If requests keep failing with a genuine error (an API outage rather than simply not-published-yet), then from the second consecutive failure the retry is held off to at most once every **30 minutes** instead of every quarter. A single failed request is simply retried on the next quarter tick.
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

The integration requests `resolution: PT15M`, which returns **native quarter-hour prices** — without authentication. That is normally **96 blocks per market day**, and **92 or 100** on the daylight-saving transition days. The blocks are used exactly as returned and are never merged.

> **Important:** the `resolution: PriceResolution!` argument is what unlocks the quarter-hour data. Without it (or with `PT60M`), the same `marketPrices` query returns only hourly blocks — normally **24 per market day**, and 23 or 25 on the transition days — which is why the cheapest block used to jump to, for example, `14:00` instead of `13:45`. The `marketPricesElectricity(startDate, endDate)` query likewise only returns hourly data and is not used.

Requests use a 30-second timeout and are attempted at most 3 times (so two retries). Invalid records are validated and skipped. Belgium (BE) is supported by sending the `x-country: BE` header; the Netherlands (NL) is the default.

---

## ApexCharts dashboard

You can visualize the prices as a color-coded bar chart — **one bar per price block**. When Frank Energie returns native quarter-hour data you normally get **96 bars per day** (92 or 100 on the daylight-saving transition days); when only hourly data is available you normally get **24** (23 or 25 on those days). The data is never merged.

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
- The three **color thresholds** (green → orange → red) can be adjusted manually in the YAML, or driven by optional `input_number` helpers (`input_number.frank_green_threshold` / `input_number.frank_red_threshold`); you create those yourself — they are not part of this integration — and the examples fall back to `0.12` and `0.25 €/kWh` when those helpers don't exist.

Ready-to-use files are available in [examples/](examples/):

- [examples/apexcharts_frank_prices_today.yaml](examples/apexcharts_frank_prices_today.yaml)
- [examples/apexcharts_frank_prices_tomorrow.yaml](examples/apexcharts_frank_prices_tomorrow.yaml)

### Today's chart

Add a new **Manual** dashboard card and paste:

```yaml
type: custom:config-template-card
variables:
  GREEN: "states['input_number.frank_green_threshold'] ? states['input_number.frank_green_threshold'].state : 0.12"
  RED: "states['input_number.frank_red_threshold'] ? states['input_number.frank_red_threshold'].state : 0.25"
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
    # No `min` on purpose: Frank prices can go negative, and pinning the axis
    # to 0 would clamp those bars out of sight. ApexCharts scales to the data,
    # so a negative hour is drawn below the zero line where it belongs.
    yaxis:
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

Same style, but reads `sensor.frank_prices_tomorrow`. The card stays empty until Frank Energie publishes tomorrow's prices (typically between 13:00 and 14:00 market-local time).

> **Note on the span:** `apexcharts-card` has no reliable "tomorrow" span offset. The chart relies on the `data_generator`, which emits real timestamps from `attributes.prices`, so every bar is plotted at its correct absolute time regardless of the configured window. `span.offset: +24h` is added as a hint; if your version of the card ignores it, the bars are still shown at the correct times because every point carries its own `from` datetime.

```yaml
type: custom:config-template-card
variables:
  GREEN: "states['input_number.frank_green_threshold'] ? states['input_number.frank_green_threshold'].state : 0.12"
  RED: "states['input_number.frank_red_threshold'] ? states['input_number.frank_red_threshold'].state : 0.25"
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
    # No `min` on purpose: Frank prices can go negative, and pinning the axis
    # to 0 would clamp those bars out of sight. ApexCharts scales to the data,
    # so a negative hour is drawn below the zero line where it belongs.
    yaxis:
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

**Charge the home battery for the whole cheap price zone:**

```yaml
automation:
  - alias: "Charge battery during the cheap price zone"
    trigger:
      - platform: state
        entity_id: binary_sensor.frank_cheap_period
        to: "on"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.battery_charge
```

**Discharge the home battery as soon as the expensive price zone starts:**

```yaml
automation:
  - alias: "Discharge battery during the expensive price zone"
    trigger:
      - platform: state
        entity_id: binary_sensor.frank_expensive_period
        to: "on"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.battery_discharge
```

**Plan ahead against the exact moment the cheap zone starts:**

```yaml
automation:
  - alias: "Notify 15 minutes before the cheap price zone"
    trigger:
      - platform: time
        at:
          entity_id: sensor.frank_cheap_zone_start_today
          offset: "-00:15:00"
    action:
      - service: notify.persistent_notification
        data:
          message: "The cheap price zone starts in 15 minutes."
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

## Troubleshooting

- **Entities show `unavailable`:**
  - For the tomorrow / cheapest-tomorrow sensors, this is expected before Frank Energie publishes the next day (typically between 13:00 and 14:00 market-local time). Check `binary_sensor.frank_tomorrow_prices_available`.
  - For all sensors: check that the integration is loaded under **Settings → Devices & Services**.
- **Entity IDs don't match this README:** check which IDs your installation actually uses via **Developer Tools → States** and adjust your automations accordingly.
- **Zone entities show `unavailable`:** no *complete* price series is known for today yet. A zone describes the whole day, so it is deliberately not derived from half a day. Check `sensor.frank_prices_today`: if it holds less than a full day (normally 96 blocks, 92 or 100 around the daylight-saving change), the zones fill in as soon as the day completes.
- **Zone entities stay `unavailable` while the day is complete:** that only happens when every quarter of the day has exactly the same price, leaving no cheap-versus-expensive distinction.
- **Price zones look wrong:** the zone is the *longest contiguous* run of quarters within the configured margin, not every cheap quarter of the day. Check the `threshold_eur_kwh` and `margin_percent` attributes on the zone sensor to see which threshold was used.
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
Native quarter-hour prices (15 minutes): normally **96 blocks per market day**, and 92 or 100 on the daylight-saving transition days. The integration requests `resolution: PT15M` via the public `marketPrices` query. If Frank Energie has no quarter-hour data for a given day, hourly data is returned instead (60 minutes; normally 24 blocks, 23 or 25 on those transition days). The blocks are used exactly as returned and are never merged, so the cheapest/most-expensive times reflect the exact quarter-hour start (e.g. `13:45`).

**How often is it updated?**
Every quarter hour, synchronized with the real quarter-hour boundaries (`:00`/`:15`/`:30`/`:45`). The active quarter-hour price is recalculated locally from the cached daily series; a request to the API is only made for a day that's still missing.

**Why is tomorrow empty in the morning?**
Frank Energie publishes the next day's prices in the early afternoon (typically between 13:00 and 14:00 market-local time). The integration requests them starting at 12:00 market-local time. The `*_tomorrow` sensors stay unavailable until then, and the integration never raises an error in the meantime.

**Does it support Belgium?**
Yes — the Netherlands (NL) is the default; Belgian (BE) prices are requested via the `x-country` header.

**Can I use the quarter-hour prices for a home battery?**
Yes. The cheapest and most expensive price-window sensors (with `timestamp` and `end_timestamp`) and the price zones (with `binary_sensor.frank_cheap_period` / `binary_sensor.frank_expensive_period`) are designed to align a home battery's charge and discharge moments. See [EMS integration examples](#ems-integration-examples).

**What is the difference between "cheapest" and the "cheap price zone"?**
`sensor.frank_cheapest_today` points at the *single* cheapest quarter of the day. The cheap price zone is the longest *contiguous period* of quarters falling within the configured margin (15% of the daily price range by default) above that cheapest quarter — so usually a block of one or more hours. See [Price zones](#price-zones-cheap--expensive).

**Do the price zones cost extra API requests?**
No. They are derived locally from the price series the integration has already fetched and cached, once per quarter-hour refresh.

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
