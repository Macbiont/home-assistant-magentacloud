"""Sensors for MagentaCLOUD."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfInformation
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.core import callback

from . import MagentaCloudConfigEntry
from .api import MagentaCloudData
from .const import DOMAIN
from .backup_status import get_backup_status, status_signal


@dataclass(frozen=True, kw_only=True)
class MagentaCloudSensorDescription(SensorEntityDescription):
    """Describe a MagentaCLOUD sensor."""

    value_fn: Callable[[MagentaCloudData], object]


SENSORS = (
    MagentaCloudSensorDescription(
        key="used", translation_key="used", device_class=SensorDeviceClass.DATA_SIZE,
        icon="mdi:database",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2, value_fn=lambda quota: quota.used / 10**9,
    ),
    MagentaCloudSensorDescription(
        key="available", translation_key="available",
        icon="mdi:database-plus-outline",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2, value_fn=lambda quota: quota.available / 10**9,
    ),
    MagentaCloudSensorDescription(
        key="total", translation_key="total", device_class=SensorDeviceClass.DATA_SIZE,
        icon="mdi:harddisk",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2, value_fn=lambda quota: quota.total / 10**9,
    ),
    MagentaCloudSensorDescription(
        key="percent_used", translation_key="percent_used",
        icon="mdi:chart-donut",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1, value_fn=lambda quota: quota.percent_used,
    ),
    MagentaCloudSensorDescription(
        key="daily_change", translation_key="daily_change",
        icon="mdi:calendar-today",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=lambda data: (
            data.daily_change / 10**9 if data.daily_change is not None else None
        ),
    ),
    MagentaCloudSensorDescription(
        key="monthly_change", translation_key="monthly_change",
        icon="mdi:calendar-month",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=lambda data: (
            data.monthly_change / 10**9 if data.monthly_change is not None else None
        ),
    ),
    MagentaCloudSensorDescription(
        key="last_success", translation_key="last_success",
        icon="mdi:clock-check-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.last_success,
    ),
    MagentaCloudSensorDescription(
        key="latency", translation_key="latency",
        native_unit_of_measurement="ms",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:timer-outline",
        value_fn=lambda data: data.latency_ms,
    ),
)


async def async_setup_entry(
    hass, entry: MagentaCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up MagentaCLOUD sensors."""
    async_add_entities(
        MagentaCloudSensor(entry, description) for description in SENSORS
    )
    status = get_backup_status(hass, entry.entry_id)
    await status.async_load()
    async_add_entities([MagentaCloudLastBackupSensor(entry, status)])


class MagentaCloudLastBackupSensor(SensorEntity):
    """Last completed upload, retained during outages and when backups are off."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "last_backup"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:cloud-check-outline"

    def __init__(self, entry, status):
        self._status = status
        self._attr_unique_id = f"{entry.unique_id}_last_backup"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        )

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(
            self.hass, status_signal(self._status.entry_id), self._updated,
        ))

    @callback
    def _updated(self):
        self.async_write_ha_state()

    @property
    def native_value(self):
        return self._status.completed_at


class MagentaCloudSensor(CoordinatorEntity, SensorEntity):
    """Representation of a MagentaCLOUD quota sensor."""

    _attr_has_entity_name = True

    def __init__(
        self, entry: MagentaCloudConfigEntry,
        description: MagentaCloudSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(entry.runtime_data)
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name="MagentaCLOUD",
            manufacturer="Deutsche Telekom",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://magentacloud.de",
        )

    @property
    def available(self) -> bool:
        """Retain the last success timestamp while current data is unavailable."""
        if self.entity_description.key == "last_success":
            return self.coordinator.data is not None
        return super().available

    @property
    def native_value(self):
        """Return the sensor value."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
