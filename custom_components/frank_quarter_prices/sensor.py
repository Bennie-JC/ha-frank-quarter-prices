"""Sensor platform for the Frank Quarter Prices integration."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import FEED_IN_VAT_RATE, PRICE_UNIT_EUR_KWH
from .coordinator import FrankQuarterPricesCoordinator
from .entity import FrankQuarterPricesEntity
from .price import (
    MARKET_PRICE_FIELD,
    calculate_feed_in_price,
    calculation_method,
    get_apply_feed_in_vat,
    get_feed_in_adjustment,
)

if TYPE_CHECKING:
    from . import FrankQuarterPricesConfigEntry

_LOGGER = logging.getLogger(__name__)

# Definitions for the cheapest / most expensive sensors.
# Each tuple is: (base, day, label, coordinator helper, is_tomorrow).
_EXTREMUM_DEFINITIONS: tuple[tuple[str, str, str, str, bool], ...] = (
    ("cheapest", "today", "Cheapest", "get_cheapest_today", False),
    ("most_expensive", "today", "Most expensive", "get_most_expensive_today", False),
    ("cheapest", "tomorrow", "Cheapest", "get_cheapest_tomorrow", True),
    (
        "most_expensive",
        "tomorrow",
        "Most expensive",
        "get_most_expensive_tomorrow",
        True,
    ),
)


def _hhmm(value: Any) -> str | None:
    """Format a datetime as a local ``HH:MM`` string."""
    if not isinstance(value, datetime):
        return None
    return dt_util.as_local(value).strftime("%H:%M")


def _local_iso(value: Any) -> str | None:
    """Return a local ISO datetime string for the given value."""
    if not isinstance(value, datetime):
        return None
    return dt_util.as_local(value).isoformat()


def _block_attributes(block: dict[str, Any] | None) -> dict[str, Any]:
    """Return the shared attributes for a single price block.

    ``time`` is the block's local start time (``HH:MM``); ``timestamp`` and
    ``end_timestamp`` are the local ISO start/end datetimes.
    """
    if block is None:
        return {}
    return {
        "time": _hhmm(block.get("from")),
        "timestamp": _local_iso(block.get("from")),
        "end_timestamp": _local_iso(block.get("till")),
        "duration_minutes": block.get("duration_minutes"),
        "full_block": _full_block(block),
    }


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
        FrankCurrentReturnPriceSensor(coordinator),
        FrankPricesTodaySensor(coordinator),
        FrankPricesTomorrowSensor(coordinator),
    ]

    for base, day, label, method_name, is_tomorrow in _EXTREMUM_DEFINITIONS:
        entities.append(
            FrankBlockPriceSensor(
                coordinator,
                f"{base}_{day}",
                f"{label} {day}",
                method_name,
                is_tomorrow,
            )
        )
        entities.append(
            FrankBlockTimeSensor(
                coordinator,
                f"{base}_time_{day}",
                f"{label} time {day}",
                method_name,
                is_tomorrow,
            )
        )

    async_add_entities(entities)


class FrankCurrentPriceSensor(FrankQuarterPricesEntity, SensorEntity):
    """Sensor exposing the current electricity purchase price.

    Suitable as the "current electricity price" entity for the Home Assistant
    Energy Dashboard: monetary device class, EUR/kWh. No ``state_class`` is set:
    this is an instantaneous price, not a cumulative total, and the Energy
    Dashboard current-price selector does not require one. The state stays
    numeric (``total_price_eur_kwh``) or unavailable.
    """

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = PRICE_UNIT_EUR_KWH

    def __init__(self, coordinator: FrankQuarterPricesCoordinator) -> None:
        """Initialize the current price sensor."""
        super().__init__(coordinator, "current_price", "Current price")

    @property
    def native_value(self) -> float | None:
        """Return the current electricity price."""
        return (self.coordinator.data or {}).get("current_price")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return time/timestamp/duration and the full active price block."""
        return _block_attributes(self._current_block())

    def _current_block(self) -> dict[str, Any] | None:
        """Return the price block matching the current time slot."""
        return (self.coordinator.data or {}).get("current_price_block")


class FrankCurrentReturnPriceSensor(FrankQuarterPricesEntity, SensorEntity):
    """Sensor exposing the estimated current electricity feed-in price.

    The value is the verified current market price plus the configured feed-in
    adjustment (see :mod:`.price`). It reuses the active price block selected by
    the coordinator and never performs its own API request. Suitable as the
    "return to grid" current-price entity for the Energy Dashboard.

    Like the purchase-price sensor, it uses the monetary device class and
    EUR/kWh but no ``state_class`` (an instantaneous price, not a total).
    """

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = PRICE_UNIT_EUR_KWH

    def __init__(self, coordinator: FrankQuarterPricesCoordinator) -> None:
        """Initialize the current feed-in price sensor."""
        super().__init__(coordinator, "current_return_price", "Current feed-in price")

    @property
    def suggested_object_id(self) -> str:
        """Force the entity id to ``sensor.frank_current_return_price``.

        The friendly name is "Current feed-in price", but the stable entity id
        uses the neutral "return price" wording that pairs with the Energy
        Dashboard's "return to grid" option. Home Assistant prepends the device
        name ("Frank"), so only the entity-name part is returned here.
        """
        return "Current return price"

    def _current_block(self) -> dict[str, Any] | None:
        """Return the active price block selected by the coordinator."""
        return (self.coordinator.data or {}).get("current_price_block")

    def _adjustment(self) -> float:
        """Return the configured feed-in adjustment (default 0.0)."""
        return get_feed_in_adjustment(self.coordinator.entry.options)

    def _apply_vat(self) -> bool:
        """Return whether 21% VAT should be applied (default False)."""
        return get_apply_feed_in_vat(self.coordinator.entry.options)

    @property
    def native_value(self) -> float | None:
        """Return the estimated current feed-in price, or None if unavailable."""
        return calculate_feed_in_price(
            self._current_block(), self._adjustment(), self._apply_vat()
        )

    @property
    def available(self) -> bool:
        """Available only when a feed-in price can be calculated."""
        if not super().available:
            return False
        return self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the source field, market price, adjustment, VAT and method."""
        block = self._current_block()
        if block is None:
            return {}
        apply_vat = self._apply_vat()
        return {
            "market_price_source": MARKET_PRICE_FIELD,
            "market_price": block.get(MARKET_PRICE_FIELD),
            "feed_in_adjustment": self._adjustment(),
            "apply_vat": apply_vat,
            "vat_rate": FEED_IN_VAT_RATE,
            "calculation_method": calculation_method(block, apply_vat),
        }


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
    """Base for sensors derived from the cheapest/most expensive day block.

    The block is the single cheapest or most expensive block of the full local
    day, compared at the raw resolution Frank returns.
    """

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


class FrankBlockPriceSensor(FrankBlockSensorBase):
    """Sensor exposing the price of the cheapest/most expensive day block.

    The state is the block's total price in EUR/kWh. The block's local start
    time and full price breakdown are exposed as attributes.
    """

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
        """Return time, timestamp, end_timestamp, duration and the full block."""
        return _block_attributes(self._block())


class FrankBlockTimeSensor(FrankBlockSensorBase):
    """Sensor exposing the start time of the cheapest/most expensive day block.

    The state is the block's local start time (``HH:MM``). The block's price
    and full breakdown are exposed as attributes.
    """

    @property
    def native_value(self) -> str | None:
        """Return the block's local start time as ``HH:MM``."""
        return _hhmm((self._block() or {}).get("from"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return price, timestamp, end_timestamp, duration and the full block."""
        block = self._block()
        if block is None:
            return {}
        return {
            "price": block.get("total_price_eur_kwh"),
            "timestamp": _local_iso(block.get("from")),
            "end_timestamp": _local_iso(block.get("till")),
            "duration_minutes": block.get("duration_minutes"),
            "full_block": _full_block(block),
        }
