"""Binary sensor platform for the Frank Quarter Prices integration."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import FrankQuarterPricesCoordinator
from .entity import FrankQuarterPricesEntity
from .optimal_period import (
    get_optimal_cheap_enabled,
    get_optimal_expensive_enabled,
    is_within_period,
)
from .price_zone import is_within_zone

if TYPE_CHECKING:
    from . import FrankQuarterPricesConfigEntry

_LOGGER = logging.getLogger(__name__)


def _local_iso(value: Any) -> str | None:
    """Return a local ISO datetime string, matching the sensor platform's format."""
    if not isinstance(value, datetime):
        return None
    return dt_util.as_local(value).isoformat()


# Definitions for the two price-zone period sensors.
# Each tuple is: (key, name, coordinator helper, icon).
_PERIOD_DEFINITIONS: tuple[tuple[str, str, str, str], ...] = (
    ("cheap_period", "Cheap period", "get_cheap_zone", "mdi:trending-down"),
    ("expensive_period", "Expensive period", "get_expensive_zone", "mdi:trending-up"),
)

# The optional "am I inside today's optimal period right now" sensors, one per
# optimal-period feature. Each tuple is:
# (feature key, entity key, name, coordinator helper, icon).
_OPTIMAL_PERIOD_DEFINITIONS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "cheap",
        "optimal_cheap_period",
        "Optimal cheap period",
        "get_optimal_cheap_today",
        "mdi:clock-check",
    ),
    (
        "expensive",
        "optimal_expensive_period",
        "Optimal expensive period",
        "get_optimal_expensive_today",
        "mdi:clock-alert",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FrankQuarterPricesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensor platform from a config entry."""
    coordinator = entry.runtime_data

    entities: list[BinarySensorEntity] = [
        FrankTomorrowPricesAvailableBinarySensor(coordinator)
    ]
    entities.extend(
        FrankPriceZonePeriodBinarySensor(coordinator, key, name, method_name, icon)
        for key, name, method_name, icon in _PERIOD_DEFINITIONS
    )

    # Same lifecycle as the optimal-period sensors, deliberately: created only
    # while the feature is enabled, and never removed from the registry when it
    # is switched off again. Solving the two platforms differently would give
    # the two halves of one feature different behaviour on the same toggle.
    enabled = {
        "cheap": get_optimal_cheap_enabled(entry.options),
        "expensive": get_optimal_expensive_enabled(entry.options),
    }
    entities.extend(
        FrankOptimalPeriodBinarySensor(coordinator, key, name, method_name, icon)
        for feature, key, name, method_name, icon in _OPTIMAL_PERIOD_DEFINITIONS
        if enabled[feature]
    )

    async_add_entities(entities)


class FrankTomorrowPricesAvailableBinarySensor(
    FrankQuarterPricesEntity, BinarySensorEntity
):
    """Binary sensor indicating whether tomorrow's prices are available."""

    def __init__(self, coordinator: FrankQuarterPricesCoordinator) -> None:
        """Initialize the binary sensor."""
        super().__init__(
            coordinator, "tomorrow_prices_available", "Tomorrow prices available"
        )

    @property
    def is_on(self) -> bool:
        """Return true when tomorrow's prices are available."""
        return bool((self.coordinator.data or {}).get("tomorrow_available"))


class FrankPriceZonePeriodBinarySensor(FrankQuarterPricesEntity, BinarySensorEntity):
    """Binary sensor indicating whether now falls inside a today price zone.

    It reuses the exact zone the corresponding start/end sensors publish — it
    never searches for qualifying quarters itself — so the three entities can
    never describe different windows. The boundary rule is ``start <= now <
    end``, evaluated between aware datetimes, so the zone ends precisely at its
    ``till`` boundary and the comparison is on absolute instants.

    The state follows the existing quarter-boundary scheduler: zone boundaries
    always fall on a block boundary, so the coordinator's :00/:15/:30/:45
    refresh flips this sensor at the right moment without a timer of its own.
    """

    def __init__(
        self,
        coordinator: FrankQuarterPricesCoordinator,
        key: str,
        name: str,
        method_name: str,
        icon: str,
    ) -> None:
        """Initialize the price-zone period binary sensor."""
        super().__init__(coordinator, key, name)
        self._method_name = method_name
        self._attr_icon = icon

    def _zone(self) -> dict[str, Any] | None:
        """Return the shared zone this sensor reports on."""
        return getattr(self.coordinator, self._method_name)()

    @property
    def available(self) -> bool:
        """Unavailable while today's data yields no zone.

        Reporting ``off`` would be indistinguishable from "outside the zone",
        so an unknown zone is surfaced as unavailable instead of as a state
        derived from yesterday's data.
        """
        if not super().available:
            return False
        return self._zone() is not None

    @property
    def is_on(self) -> bool | None:
        """Return true while the current local time is inside the zone."""
        return is_within_zone(self._zone(), dt_util.now())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the zone window, threshold and configured margin."""
        zone = self._zone()
        if zone is None:
            return {}
        return {
            "zone_start": _local_iso(zone.get("start")),
            "zone_end": _local_iso(zone.get("end")),
            "threshold_eur_kwh": zone.get("threshold_eur_kwh"),
            "margin_percent": zone.get("margin_percent"),
        }


class FrankOptimalPeriodBinarySensor(FrankQuarterPricesEntity, BinarySensorEntity):
    """Binary sensor: is now inside today's optimal cheap/expensive period?

    It reuses the exact period the matching ``*_today`` sensor publishes — it
    never searches for a window itself — so the two entities can never describe
    different periods. The boundary rule is ``start <= now < end``, evaluated on
    absolute instants, so the period ends precisely at its final block's ``till``
    and the repeated hour of the fall-back day is judged correctly.

    The state follows the existing quarter-boundary scheduler: a period boundary
    is always a block boundary, so the coordinator's :00/:15/:30/:45 refresh
    flips this sensor at the right moment without a timer of its own.

    Created only while its feature is enabled, and only ever for *today* — a
    "are we inside it now" question about tomorrow has no meaning, and the
    tomorrow sensor already carries the planned window.
    """

    def __init__(
        self,
        coordinator: FrankQuarterPricesCoordinator,
        key: str,
        name: str,
        method_name: str,
        icon: str,
    ) -> None:
        """Initialize the optimal-period binary sensor."""
        super().__init__(coordinator, key, name)
        self._method_name = method_name
        self._attr_icon = icon

    def _period(self) -> dict[str, Any] | None:
        """Return the shared period this sensor reports on."""
        return getattr(self.coordinator, self._method_name)()

    @property
    def available(self) -> bool:
        """Unavailable while today yields no optimal period.

        Reporting ``off`` would be indistinguishable from "outside the period",
        so an unknown period is surfaced as unavailable instead of as a state
        derived from an incomplete day.
        """
        if not super().available:
            return False
        return self._period() is not None

    @property
    def is_on(self) -> bool | None:
        """Return true while the current instant is inside the period."""
        return is_within_period(self._period(), dt_util.now())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the period window, its average price and its duration."""
        period = self._period()
        if period is None:
            return {}
        return {
            "start": _local_iso(period.get("start")),
            "end": _local_iso(period.get("end")),
            "duration_minutes": period.get("duration_minutes"),
            "average_price_eur_kwh": period.get("average_price_eur_kwh"),
        }
