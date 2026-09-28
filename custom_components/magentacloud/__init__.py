"""The MagentaCLOUD integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    MagentaCloudAuthenticationError,
    MagentaCloudClient,
    MagentaCloudError,
    MagentaCloudData,
)
from .const import CONF_PASSWORD, CONF_URL, CONF_USERNAME, DEFAULT_SCAN_INTERVAL, DOMAIN, DATA_BACKUP_LISTENERS
from .history import UsageHistory

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]
LOGGER = logging.getLogger(__name__)

type MagentaCloudConfigEntry = ConfigEntry[DataUpdateCoordinator[MagentaCloudData]]


async def async_setup_entry(
    hass: HomeAssistant, entry: MagentaCloudConfigEntry
) -> bool:
    """Set up MagentaCLOUD from a config entry."""
    client = MagentaCloudClient(
        async_get_clientsession(hass),
        entry.data[CONF_URL],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    history = UsageHistory(hass, entry.entry_id)
    await history.async_load()

    async def async_update_data() -> MagentaCloudData:
        try:
            return await history.async_enrich(await client.async_get_quota())
        except MagentaCloudAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                "MagentaCLOUD rejected the WebDAV credentials"
            ) from err
        except MagentaCloudError as err:
            raise UpdateFailed(str(err) or err.__class__.__name__) from err

    coordinator = DataUpdateCoordinator(
        hass,
        logger=LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=DEFAULT_SCAN_INTERVAL,
        config_entry=entry,
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    def notify_backup_listeners() -> None:
        for listener in tuple(hass.data.get(DATA_BACKUP_LISTENERS, [])):
            listener()

    entry.async_on_unload(entry.async_on_state_change(notify_backup_listeners))
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_update_options(hass: HomeAssistant, entry: MagentaCloudConfigEntry) -> None:
    """Refresh backup discovery without interrupting polling or transfers."""
    for listener in tuple(hass.data.get(DATA_BACKUP_LISTENERS, [])):
        listener()


async def async_unload_entry(
    hass: HomeAssistant, entry: MagentaCloudConfigEntry
) -> bool:
    """Unload a MagentaCLOUD config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
