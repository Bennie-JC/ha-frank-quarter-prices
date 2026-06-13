"""Binary sensor platform for the Frank Quarter Prices integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FrankQuarterPricesCoordinator
from .entity import FrankQuarterPricesEntity

if TYPE_CHECKING:
    from . import FrankQuarterPricesConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FrankQuarterPricesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensor platform from a config entry."""
    coordinator = entry.runtime_data

    async_add_entities([FrankTomorrowPricesAvailableBinarySensor(coordinator)])


class FrankTomorrowPricesAvailableBinarySensor(
    FrankQuarterPricesEntity, BinarySensorEntity
):
    """Binary sensor indicating whether tomorrow's prices are available."""

    _attr_translation_key = "tomorrow_prices_available"

    def __init__(self, coordinator: FrankQuarterPricesCoordinator) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, "tomorrow_prices_available")

    @property
    def is_on(self) -> bool:
        """Return true when tomorrow's prices are available."""
        return bool((self.coordinator.data or {}).get("tomorrow_available"))
