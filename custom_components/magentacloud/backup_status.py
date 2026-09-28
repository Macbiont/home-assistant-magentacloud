"""Persist upload completion independently of quota polling."""

import asyncio
from datetime import datetime, timezone
import logging

from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import DOMAIN

LOGGER = logging.getLogger(__name__)


def status_signal(entry_id):
    return f"{DOMAIN}_backup_completed_{entry_id}"


class BackupStatus:
    def __init__(self, hass, entry_id):
        self.hass = hass
        self.entry_id = entry_id
        self.completed_at = None
        self._loaded = False
        self._lock = asyncio.Lock()
        self._store = Store(hass, 1, f"{DOMAIN}_backup_status_{entry_id}")

    async def async_load(self):
        async with self._lock:
            if self._loaded:
                return
            try:
                data = await self._store.async_load()
                if data is not None:
                    value = datetime.fromisoformat(data["completed_at"])
                    if value.tzinfo is None:
                        raise ValueError("Timestamp must have a timezone")
                    self.completed_at = value
            except (OSError, ValueError, TypeError, KeyError):
                LOGGER.warning("Could not restore last backup timestamp")
            self._loaded = True

    async def async_completed(self):
        await self.async_load()
        async with self._lock:
            self.completed_at = datetime.now(timezone.utc)
            try:
                await self._store.async_save({"completed_at": self.completed_at.isoformat()})
            except OSError:
                # A local status-write failure must not turn a committed cloud
                # archive into a failed upload (which could cause unsafe retries).
                LOGGER.warning("Backup completed, but its timestamp could not be saved")
            async_dispatcher_send(self.hass, status_signal(self.entry_id))


def get_backup_status(hass, entry_id):
    statuses = hass.data.setdefault(f"{DOMAIN}_backup_status", {})
    if entry_id not in statuses:
        statuses[entry_id] = BackupStatus(hass, entry_id)
    return statuses[entry_id]
