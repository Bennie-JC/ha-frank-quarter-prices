"""Base entity for the Frank Quarter Prices integration."""

from __future__ import annotations

from homeassistant.helpers.device_info import DeviceInfo
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_NAME, DOMAIN
from .coordinator import FrankQuarterPricesCoordinator


class FrankQuarterPricesEntity(CoordinatorEntity[FrankQuarterPricesCoordinator]):
    """Base entity that ties all entities to a single device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FrankQuarterPricesCoordinator, key: str) -> None:
        """Initialize the base entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=DEFAULT_NAME,
            manufacturer="Frank Energie",
            model="Quarter Prices",
            entry_type=DeviceEntryType.SERVICE,
        )
