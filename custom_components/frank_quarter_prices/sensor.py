"""Sensor platform for the Frank Quarter Prices integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FrankQuarterPricesCoordinator
from .entity import FrankQuarterPricesEntity

if TYPE_CHECKING:
    from . import FrankQuarterPricesConfigEntry

_LOGGER = logging.getLogger(__name__)

# Attribute keys copied directly from a price block onto the current price sensor.
_PRICE_BLOCK_ATTRS = (
    "from",
    "till",
    "duration_minutes",
    "market_price",
    "market_price_tax",
    "sourcing_markup_price",
    "energy_tax_price",
    "total_price_eur_kwh",
    "per_unit",
)

# Definitions for the extremum (cheapest / most expensive) sensors.
# Each tuple is: (key, coordinator helper method name).
_EXTREMUM_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("cheapest_price_today", "get_cheapest_today"),
    ("most_expensive_price_today", "get_most_expensive_today"),
    ("cheapest_price_tomorrow", "get_cheapest_tomorrow"),
    ("most_expensive_price_tomorrow", "get_most_expensive_tomorrow"),
    ("cheapest_price_next_24h", "get_cheapest_next_24h"),
    ("most_expensive_price_next_24h", "get_most_expensive_next_24h"),
    ("cheapest_price_next_48h", "get_cheapest_next_48h"),
    ("most_expensive_price_next_48h", "get_most_expensive_next_48h"),
)

# Definitions for the ApexCharts series sensors.
# Each tuple is: (key, coordinator helper method name, span_hours, resolution).
# ``resolution`` is "source" to keep the original resolution, or "hourly".
_APEX_DEFINITIONS: tuple[tuple[str, str, int, str], ...] = (
    ("apex_24h_quarter", "get_apex_24h_quarter", 24, "source"),
    ("apex_48h_quarter", "get_apex_48h_quarter", 48, "source"),
    ("apex_24h_hourly", "get_apex_24h_hourly", 24, "hourly"),
    ("apex_48h_hourly", "get_apex_48h_hourly", 48, "hourly"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FrankQuarterPricesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor platform from a config entry."""
    coordinator = entry.runtime_data

    entities: list[SensorEntity] = [
        FrankCurrentPriceSensor(coordinator),
        FrankPricesTodaySensor(coordinator),
        FrankPricesTomorrowSensor(coordinator),
    ]

    for key, method_name in _EXTREMUM_DEFINITIONS:
        entities.append(FrankBlockPriceSensor(coordinator, key, method_name))
        entities.append(FrankBlockBoundarySensor(coordinator, key, method_name, "from"))
        entities.append(FrankBlockBoundarySensor(coordinator, key, method_name, "till"))

    for key, method_name, span_hours, resolution in _APEX_DEFINITIONS:
        entities.append(
            FrankApexSensor(coordinator, key, method_name, span_hours, resolution)
        )

    async_add_entities(entities)


class FrankCurrentPriceSensor(FrankQuarterPricesEntity, SensorEntity):
    """Sensor exposing the current electricity price."""

    _attr_translation_key = "current_electricity_price"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR/kWh"

    def __init__(self, coordinator: FrankQuarterPricesCoordinator) -> None:
        """Initialize the current price sensor."""
        super().__init__(coordinator, "current_electricity_price")

    @property
    def native_value(self) -> float | None:
        """Return the current electricity price."""
        return (self.coordinator.data or {}).get("current_price")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes from the currently active price block."""
        block = self._current_block()
        if block is None:
            return {}
        return {key: block.get(key) for key in _PRICE_BLOCK_ATTRS}

    def _current_block(self) -> dict[str, Any] | None:
        """Return the price block matching the current time slot."""
        data = self.coordinator.data or {}
        now = data.get("last_update")
        if now is None:
            return None
        for block in data.get("today", []):
            start = block.get("from")
            end = block.get("till")
            if start is not None and end is not None and start <= now < end:
                return block
        return None


class FrankPricesTodaySensor(FrankQuarterPricesEntity, SensorEntity):
    """Sensor exposing the number of price blocks for today."""

    _attr_translation_key = "prices_today"
    _attr_native_unit_of_measurement = "blocks"

    def __init__(self, coordinator: FrankQuarterPricesCoordinator) -> None:
        """Initialize the prices-today sensor."""
        super().__init__(coordinator, "prices_today")

    @property
    def native_value(self) -> int:
        """Return the number of price blocks for today."""
        return len((self.coordinator.data or {}).get("today", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return today's prices and summary blocks."""
        data = self.coordinator.data or {}
        return {
            "prices": data.get("today", []),
            "resolution_minutes": data.get("resolution_minutes"),
            "cheapest_block": self.coordinator.get_cheapest_today(),
            "most_expensive_block": self.coordinator.get_most_expensive_today(),
        }


class FrankPricesTomorrowSensor(FrankQuarterPricesEntity, SensorEntity):
    """Sensor exposing the number of price blocks for tomorrow."""

    _attr_translation_key = "prices_tomorrow"
    _attr_native_unit_of_measurement = "blocks"

    def __init__(self, coordinator: FrankQuarterPricesCoordinator) -> None:
        """Initialize the prices-tomorrow sensor."""
        super().__init__(coordinator, "prices_tomorrow")

    @property
    def available(self) -> bool:
        """Return availability.

        Unavailable when tomorrow's prices are not available and no cached
        tomorrow data exists.
        """
        if not super().available:
            return False
        data = self.coordinator.data or {}
        return bool(data.get("tomorrow_available")) or bool(data.get("tomorrow"))

    @property
    def native_value(self) -> int:
        """Return the number of price blocks for tomorrow."""
        return len((self.coordinator.data or {}).get("tomorrow", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return tomorrow's prices and summary blocks."""
        data = self.coordinator.data or {}
        return {
            "prices": data.get("tomorrow", []),
            "available": bool(data.get("tomorrow_available")),
            "resolution_minutes": data.get("resolution_minutes"),
            "cheapest_block": self.coordinator.get_cheapest_tomorrow(),
            "most_expensive_block": self.coordinator.get_most_expensive_tomorrow(),
        }


class FrankBlockSensorBase(FrankQuarterPricesEntity, SensorEntity):
    """Base for sensors derived from a single coordinator price block."""

    def __init__(
        self,
        coordinator: FrankQuarterPricesCoordinator,
        key: str,
        method_name: str,
    ) -> None:
        """Initialize the block-based sensor."""
        super().__init__(coordinator, key)
        self._method_name = method_name

    def _block(self) -> dict[str, Any] | None:
        """Resolve the price block via the coordinator helper method."""
        getter = getattr(self.coordinator, self._method_name)
        return getter()

    @property
    def available(self) -> bool:
        """Return True only when a price block is available."""
        return super().available and self._block() is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the full price block as attributes."""
        block = self._block()
        if block is None:
            return {}
        return {key: block.get(key) for key in _PRICE_BLOCK_ATTRS}


class FrankBlockPriceSensor(FrankBlockSensorBase):
    """Sensor exposing the total price of a price block."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR/kWh"

    def __init__(
        self,
        coordinator: FrankQuarterPricesCoordinator,
        key: str,
        method_name: str,
    ) -> None:
        """Initialize the price sensor."""
        super().__init__(coordinator, key, method_name)
        self._attr_translation_key = key

    @property
    def native_value(self) -> float | None:
        """Return the total price of the block."""
        block = self._block()
        if block is None:
            return None
        return block.get("total_price_eur_kwh")


class FrankBlockBoundarySensor(FrankBlockSensorBase):
    """Sensor exposing the start or end datetime of a price block."""

    def __init__(
        self,
        coordinator: FrankQuarterPricesCoordinator,
        key: str,
        method_name: str,
        boundary: str,
    ) -> None:
        """Initialize the boundary sensor.

        ``boundary`` is either ``"from"`` (start) or ``"till"`` (end).
        """
        suffix = "start" if boundary == "from" else "end"
        super().__init__(coordinator, f"{key}_{suffix}", method_name)
        self._boundary = boundary
        self._attr_translation_key = f"{key}_{suffix}"

    @property
    def native_value(self) -> str | None:
        """Return the boundary datetime as an ISO 8601 string."""
        block = self._block()
        if block is None:
            return None
        value = block.get(self._boundary)
        return value.isoformat() if value is not None else None


class FrankApexSensor(FrankQuarterPricesEntity, SensorEntity):
    """Sensor exposing an ApexCharts-ready price series.

    State is the number of datapoints. The ``data`` attribute holds the series
    as ``[[timestamp_ms, price], ...]``.
    """

    _attr_native_unit_of_measurement = "points"

    def __init__(
        self,
        coordinator: FrankQuarterPricesCoordinator,
        key: str,
        method_name: str,
        span_hours: int,
        resolution: str,
    ) -> None:
        """Initialize the ApexCharts sensor."""
        super().__init__(coordinator, key)
        self._method_name = method_name
        self._span_hours = span_hours
        self._resolution = resolution
        self._attr_translation_key = key

    def _series(self) -> list[list[Any]]:
        """Resolve the ApexCharts series via the coordinator helper method."""
        getter = getattr(self.coordinator, self._method_name)
        return getter()

    @property
    def native_value(self) -> int:
        """Return the number of datapoints in the series."""
        return len(self._series())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the ApexCharts series and metadata."""
        data = self.coordinator.data or {}
        # "hourly" resolution reflects the aggregated output; "source" keeps
        # the coordinator's detected resolution (15 or 60 minutes).
        if self._resolution == "hourly":
            resolution = 60
        else:
            resolution = data.get("resolution_minutes")
        return {
            "data": self._series(),
            "span_hours": self._span_hours,
            "resolution": resolution,
            "generated_at": data.get("last_update"),
            "tomorrow_available": bool(data.get("tomorrow_available")),
        }
