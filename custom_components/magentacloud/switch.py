"""Make backup opt-in discoverable on the existing device."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_BACKUP_ENABLED, DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([MagentaCloudBackupSwitch(entry)])


class MagentaCloudBackupSwitch(SwitchEntity):
    """Expose the same persisted option as the options dialog; never upload."""

    _attr_has_entity_name = True
    _attr_translation_key = "backup_enabled"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:cloud-upload-outline"
    _attr_should_poll = False

    def __init__(self, entry):
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_backup_enabled"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        )

    @property
    def is_on(self):
        return self._entry.options.get(CONF_BACKUP_ENABLED, False)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self._entry.add_update_listener(self._options_updated))

    async def _options_updated(self, hass, entry):
        self.async_write_ha_state()

    async def _set_enabled(self, enabled):
        self.hass.config_entries.async_update_entry(
            self._entry, options={**self._entry.options, CONF_BACKUP_ENABLED: enabled},
        )
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        await self._set_enabled(True)

    async def async_turn_off(self, **kwargs):
        await self._set_enabled(False)
