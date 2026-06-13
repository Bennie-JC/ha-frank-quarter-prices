"""Sensor platform for the Frank Quarter Prices integration."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import FrankQuarterPricesCoordinator
from .entity import FrankQuarterPricesEntity

if TYPE_CHECKING:
    from . import FrankQuarterPricesConfigEntry

_LOGGER = logging.getLogger(__name__)

# Definitions for the cheapest / most expensive sensors.
# Each tuple is: (base_key, label, coordinator helper, is_tomorrow).
_EXTREMUM_DEFINITIONS: tuple[tuple[str, str, str, bool], ...] = (
    ("cheapest", "Cheapest", "get_cheapest_today", False),
    ("most_expensive", "Most expensive", "get_most_expensive_today", False),
    ("cheapest", "Cheapest", "get_cheapest_tomorrow", True),
    ("most_expensive", "Most expensive", "get_most_expensive_tomorrow", True),
)


def _hhmm(value: Any) -> str | None:
    """Format a datetime as a local ``HH:MM`` string."""
    if not isinstance(value, datetime):
        return None
    return dt_util.as_local(value).strftime("%H:%M")


def _time_range(block: dict[str, Any] | None) -> str | None:
    """Return a human readable ``HH:MM - HH:MM`` local time range."""
    if block is None:
        return None
    start = _hhmm(block.get("from"))
    end = _hhmm(block.get("till"))
    if start is None or end is None:
        return None
    return f"{start} - {end}"


def _full_block(block: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a serializable copy of a price block with local ISO times."""
    if block is None:
        return None
    full = dict(block)
    start = block.get("from")
    till = block.get("till")
    if isinstance(start, datetime):
        full["from"] = dt_util.as_local(start).isoformat()
    if isinstance(till, datetime):
        full["till"] = dt_util.as_local(till).isoformat()
    return full


def _serialize_prices(prices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Serialize a list of price blocks for use in attributes."""
    return [b for b in (_full_block(p) for p in prices) if b is not None]


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

    for base_key, label, method_name, is_tomorrow in _EXTREMUM_DEFINITIONS:
        day = "tomorrow" if is_tomorrow else "today"
        price_key = f"{base_key}_price_{day}"
        time_key = f"{base_key}_time_{day}"
        entities.append(
            FrankBlockPriceSensor(
                coordinator,
                price_key,
                f"{label} price {day}",
                method_name,
                is_tomorrow,
            )
        )
        entities.append(
            FrankBlockTimeSensor(
                coordinator,
                time_key,
                f"{label} time {day}",
                method_name,
                is_tomorrow,
            )
        )

    async_add_entities(entities)


class FrankCurrentPriceSensor(FrankQuarterPricesEntity, SensorEntity):
    """Sensor exposing the current electricity price."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR/kWh"

    def __init__(self, coordinator: FrankQuarterPricesCoordinator) -> None:
        """Initialize the current price sensor."""
        super().__init__(coordinator, "current_price", "Current price")

    @property
    def native_value(self) -> float | None:
        """Return the current electricity price."""
        return (self.coordinator.data or {}).get("current_price")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return start/end/duration and the full active price block."""
        block = self._current_block()
        if block is None:
            return {}
        return {
            "start": _hhmm(block.get("from")),
            "end": _hhmm(block.get("till")),
            "duration_minutes": block.get("duration_minutes"),
            "full_block": _full_block(block),
        }

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

    _attr_native_unit_of_measurement = "blocks"

    def __init__(self, coordinator: FrankQuarterPricesCoordinator) -> None:
        """Initialize the prices-today sensor."""
        super().__init__(coordinator, "prices_today", "Prices today")

    @property
    def native_value(self) -> int:
        """Return the number of price blocks for today."""
        return len((self.coordinator.data or {}).get("today", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return today's prices, summary blocks and statistics."""
        data = self.coordinator.data or {}
        prices = data.get("today", [])
        return {
            "prices": _serialize_prices(prices),
            "resolution_minutes": data.get("resolution_minutes"),
            "cheapest_block": _full_block(self.coordinator.get_cheapest_today()),
            "most_expensive_block": _full_block(
                self.coordinator.get_most_expensive_today()
            ),
            "average_price": self.coordinator.average_price(prices),
            "min_price": self.coordinator.min_price(prices),
            "max_price": self.coordinator.max_price(prices),
        }


class FrankPricesTomorrowSensor(FrankQuarterPricesEntity, SensorEntity):
    """Sensor exposing the number of price blocks for tomorrow."""

    _attr_native_unit_of_measurement = "blocks"

    def __init__(self, coordinator: FrankQuarterPricesCoordinator) -> None:
        """Initialize the prices-tomorrow sensor."""
        super().__init__(coordinator, "prices_tomorrow", "Prices tomorrow")

    @property
    def available(self) -> bool:
        """Return availability; unavailable until tomorrow's prices are published."""
        if not super().available:
            return False
        return bool((self.coordinator.data or {}).get("tomorrow_available"))

    @property
    def native_value(self) -> int:
        """Return the number of price blocks for tomorrow."""
        return len((self.coordinator.data or {}).get("tomorrow", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return tomorrow's prices, summary blocks and statistics."""
        data = self.coordinator.data or {}
        prices = data.get("tomorrow", [])
        return {
            "prices": _serialize_prices(prices),
            "available": bool(data.get("tomorrow_available")),
            "resolution_minutes": data.get("resolution_minutes"),
            "cheapest_block": _full_block(self.coordinator.get_cheapest_tomorrow()),
            "most_expensive_block": _full_block(
                self.coordinator.get_most_expensive_tomorrow()
            ),
            "average_price": self.coordinator.average_price(prices),
            "min_price": self.coordinator.min_price(prices),
            "max_price": self.coordinator.max_price(prices),
            "last_attempt": data.get("last_attempt"),
        }


class FrankBlockSensorBase(FrankQuarterPricesEntity, SensorEntity):
    """Base for sensors derived from a single coordinator price block."""

    def __init__(
        self,
        coordinator: FrankQuarterPricesCoordinator,
        key: str,
        name: str,
        method_name: str,
        is_tomorrow: bool,
    ) -> None:
        """Initialize the block-based sensor."""
        super().__init__(coordinator, key, name)
        self._method_name = method_name
        self._is_tomorrow = is_tomorrow

    def _block(self) -> dict[str, Any] | None:
        """Resolve the price block via the coordinator helper method."""
        getter = getattr(self.coordinator, self._method_name)
        return getter()

    @property
    def available(self) -> bool:
        """Return True only when a price block is available."""
        if not super().available:
            return False
        # Tomorrow-based sensors are unavailable until tomorrow is published.
        if self._is_tomorrow and not (self.coordinator.data or {}).get(
            "tomorrow_available"
        ):
            return False
        return self._block() is not None

    def _block_attributes(self) -> dict[str, Any]:
        """Shared start/end/duration/full_block attributes for a block."""
        block = self._block()
        if block is None:
            return {}
        return {
            "start": _hhmm(block.get("from")),
            "end": _hhmm(block.get("till")),
            "duration_minutes": block.get("duration_minutes"),
            "full_block": _full_block(block),
        }


class FrankBlockPriceSensor(FrankBlockSensorBase):
    """Sensor exposing the total price of a price block."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR/kWh"

    @property
    def native_value(self) -> float | None:
        """Return the total price of the block."""
        block = self._block()
        if block is None:
            return None
        return block.get("total_price_eur_kwh")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return start, end, duration and the full price block."""
        return self._block_attributes()


class FrankBlockTimeSensor(FrankBlockSensorBase):
    """Sensor exposing the local time range of a price block."""

    @property
    def native_value(self) -> str | None:
        """Return the block's local time range as ``HH:MM - HH:MM``."""
        return _time_range(self._block())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return price, start, end, duration and the full price block."""
        block = self._block()
        if block is None:
            return {}
        return {
            "price": block.get("total_price_eur_kwh"),
            **self._block_attributes(),
        }
