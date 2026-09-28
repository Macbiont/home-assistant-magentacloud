"""Binary sensors for MagentaCLOUD."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MagentaCloudConfigEntry
from .const import DOMAIN


async def async_setup_entry(
    hass, entry: MagentaCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the connection sensor."""
    async_add_entities([MagentaCloudConnectionSensor(entry)])


class MagentaCloudConnectionSensor(CoordinatorEntity, BinarySensorEntity):
    """Report whether the latest WebDAV request succeeded."""

    _attr_has_entity_name = True
    _attr_translation_key = "connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, entry: MagentaCloudConfigEntry) -> None:
        super().__init__(entry.runtime_data)
        self._attr_unique_id = f"{entry.unique_id}_connection"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name="MagentaCLOUD",
            manufacturer="Deutsche Telekom",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://magentacloud.de",
        )

    @property
    def icon(self) -> str:
        """Match the cloud symbol to the last request's outcome."""
        return (
            "mdi:cloud-check-outline"
            if self.coordinator.last_update_success
            else "mdi:cloud-alert-outline"
        )

    @property
    def available(self) -> bool:
        """Keep connection failures visible as off, not unavailable."""
        return True

    @property
    def is_on(self) -> bool:
        """Return whether the latest update succeeded."""
        return self.coordinator.last_update_success
