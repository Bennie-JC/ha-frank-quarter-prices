"""Base entity for the Frank Quarter Prices integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_NAME, DOMAIN
from .coordinator import FrankQuarterPricesCoordinator


def unique_id_for(entry_id: str, key: str) -> str:
    """Return the unique id an entity with ``key`` gets on this entry.

    The single definition of the pattern, and the whole basis of the optional
    entities' lifecycle. It is what survives a rename, so an optional entity
    that is switched off and on again comes back on exactly this id — a
    different one would orphan the original and hand the user a duplicate with a
    ``_2`` suffix.

    Note what deliberately does **not** happen anywhere in this integration:
    a registry entry for a disabled optional feature is never removed. Not
    creating the entity is enough. Home Assistant then keeps the registry entry
    and publishes ``unavailable`` for it, which is both the conventional meaning
    ("this entity exists but has no value right now") and the only state an
    automation or template referencing it can actually detect. Removing the
    registry entry instead makes ``hass.states.get()`` return ``None``, so a
    template silently reads ``unknown`` and a state trigger silently never
    fires. Leaving the entry alone also keeps every user customization — custom
    entity id, name, icon, area, labels, hidden/disabled flags — in place by
    construction, rather than depending on Home Assistant's deleted-entity
    restore pool to hand them back.

    The cost is that a feature switched off leaves an unavailable entity behind
    until the user deletes it, which is the accepted trade: a user who never
    enables the feature never gets an entity at all, because none was ever
    created for them.
    """
    return f"{entry_id}_{key}"


class FrankQuarterPricesEntity(CoordinatorEntity[FrankQuarterPricesCoordinator]):
    """Base entity that ties all entities to a single device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: FrankQuarterPricesCoordinator, key: str, name: str
    ) -> None:
        """Initialize the base entity.

        The device is named "Frank" and each entity name slug equals ``key``,
        so entity ids resolve to ``<platform>.frank_<key>``
        (e.g. ``sensor.frank_current_price``).
        """
        super().__init__(coordinator)
        self._attr_unique_id = unique_id_for(coordinator.entry.entry_id, key)
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=DEVICE_NAME,
            manufacturer="Jouw Cloud B.V.",
            model="Frank Energie Market Prices",
            sw_version=coordinator.integration_version,
            entry_type=DeviceEntryType.SERVICE,
        )


