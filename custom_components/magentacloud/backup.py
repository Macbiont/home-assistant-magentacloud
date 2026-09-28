"""Opt-in, streaming MagentaCLOUD backup agent.

An archive becomes visible only after its metadata is committed. File names are
derived from backup IDs, never from untrusted backup names or remote paths.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from hashlib import sha256
import asyncio
import json
import re
from urllib.parse import unquote, urlsplit
from uuid import uuid4
from xml.etree import ElementTree

from aiohttp import ClientError, ClientTimeout, encode_basic_auth

from homeassistant.components.backup import AgentBackup, BackupAgent, BackupAgentError, BackupNotFound
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .backup_status import get_backup_status

from .const import (
    BACKUP_FOLDER, CONF_BACKUP_ENABLED, CONF_PASSWORD, CONF_URL, CONF_USERNAME,
    DATA_BACKUP_LISTENERS, DOMAIN,
)

_TIMEOUT = ClientTimeout(total=43200, connect=15, sock_read=120)
_SMALL_TIMEOUT = ClientTimeout(total=60, connect=15, sock_read=30)
_METADATA_LIMIT = 1024 * 1024
_NAME = re.compile(r"[a-f0-9]{64}\.metadata\.json")


async def async_get_backup_agents(hass) -> list[BackupAgent]:
    return [
        MagentaCloudBackupAgent(hass, entry)
        for entry in hass.config_entries.async_loaded_entries(DOMAIN)
        if entry.options.get(CONF_BACKUP_ENABLED, False)
    ]


@callback
def async_register_backup_agents_listener(hass, *, listener: Callable[[], None], **kwargs):
    listeners = hass.data.setdefault(DATA_BACKUP_LISTENERS, [])
    listeners.append(listener)

    @callback
    def remove():
        listeners.remove(listener)

    return remove


class MagentaCloudBackupAgent(BackupAgent):
    domain = DOMAIN

    def __init__(self, hass, entry):
        super().__init__()
        self.name = f"MagentaCLOUD ({entry.title})"
        self.unique_id = entry.entry_id
        self._hass = hass
        self._entry_id = entry.entry_id
        self._session = async_get_clientsession(hass)
        self._authorization = encode_basic_auth(
            entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
        )
        endpoint = entry.data[CONF_URL].rstrip("/")
        try:
            parsed = urlsplit(endpoint)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                    or parsed.password is not None or parsed.query or parsed.fragment
                    or parsed.port == 0
                    or any(c.isspace() or ord(c) < 32 for c in endpoint)):
                raise ValueError
        except ValueError:
            raise BackupAgentError("Backup storage requires a valid HTTPS endpoint") from None
        self._base = f"{endpoint}/{BACKUP_FOLDER}/"
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(backup_id):
        if not isinstance(backup_id, str) or not backup_id:
            raise BackupAgentError("Invalid backup ID")
        return sha256(backup_id.encode()).hexdigest()

    @asynccontextmanager
    async def _request(self, method, name="", *, statuses=(200,), streaming=False, **kwargs):
        headers = {
            "Authorization": self._authorization,
            "Accept-Encoding": "identity",
            **kwargs.pop("headers", {}),
        }
        try:
            async with self._session.request(
                method, self._base + name, allow_redirects=False,
                auto_decompress=False,
                headers=headers,
                timeout=_TIMEOUT if streaming else _SMALL_TIMEOUT, **kwargs,
            ) as response:
                if response.status not in statuses:
                    # Never include response bodies, URLs or credentials in errors.
                    raise BackupAgentError(f"MagentaCLOUD backup {method} failed (HTTP {response.status})")
                yield response
        except (ClientError, TimeoutError):
            raise BackupAgentError("MagentaCLOUD backup connection failed or timed out") from None

    async def _read_small(self, response, limit):
        result = bytearray()
        async for chunk in response.content.iter_chunked(65536):
            result.extend(chunk)
            if len(result) > limit:
                raise BackupAgentError("Backup metadata or listing exceeds size limit")
        return bytes(result)

    async def async_get_backup(self, backup_id, **kwargs):
        key = self._key(backup_id)
        async with self._request("GET", f"{key}.metadata.json", statuses=(200, 404)) as response:
            if response.status == 404:
                raise BackupNotFound("Backup not found")
            payload = await self._read_small(response, _METADATA_LIMIT)
        backup = self._parse_metadata(payload, key)
        if backup.backup_id != backup_id:
            raise BackupAgentError("Backup metadata ID mismatch")
        return backup

    def _parse_metadata(self, payload, key):
        try:
            backup = AgentBackup.from_dict(json.loads(payload))
            if (self._key(backup.backup_id) != key or type(backup.size) is not int
                    or backup.size < 0 or type(backup.protected) is not bool):
                raise ValueError
            return backup
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
            raise BackupAgentError("Invalid MagentaCLOUD backup metadata") from None

    async def async_list_backups(self, **kwargs):
        body = '<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>'
        async with self._request("PROPFIND", statuses=(207, 404), data=body,
                                 headers={"Depth": "1", "Content-Type": "application/xml"}) as response:
            if response.status == 404:
                return []
            payload = await self._read_small(response, 4 * _METADATA_LIMIT)
        try:
            root = ElementTree.fromstring(payload)
        except ElementTree.ParseError:
            raise BackupAgentError("Invalid WebDAV backup listing") from None
        base_path = unquote(urlsplit(self._base).path)
        names = set()
        for item in root.findall("{DAV:}response"):
            href = urlsplit(item.findtext("{DAV:}href", ""))
            if href.netloc and href.netloc != urlsplit(self._base).netloc:
                continue
            path = unquote(href.path)
            if path.startswith(base_path) and _NAME.fullmatch(name := path[len(base_path):]):
                names.add(name)
        backups = []
        for name in sorted(names):
            async with self._request("GET", name, statuses=(200, 404)) as response:
                if response.status == 404:
                    continue
                payload = await self._read_small(response, _METADATA_LIMIT)
            # Fail visibly on corrupt metadata, never silently claim a complete list.
            backups.append(self._parse_metadata(payload, name.removesuffix(".metadata.json")))
        return backups

    async def async_upload_backup(self, *, open_stream, backup, on_progress, **kwargs):
        if not backup.protected:
            raise BackupAgentError("Enable backup encryption before uploading to MagentaCLOUD")
        key = self._key(backup.backup_id)
        metadata = json.dumps(backup.as_dict()).encode()
        self._parse_metadata(metadata, key)
        if len(metadata) > _METADATA_LIMIT:
            raise BackupAgentError("Backup metadata exceeds size limit")
        async with self._lock:
            async with self._request("MKCOL", statuses=(201, 405)):
                pass
            # Do not replace existing archives, even after a partially failed attempt.
            async with self._request("HEAD", f"{key}.tar", statuses=(200, 404)) as response:
                if response.status == 200:
                    raise BackupAgentError("Backup archive already exists; refusing to overwrite")
            staging = f"{key}.{uuid4().hex}.partial"
            transferred = 0

            async def chunks():
                nonlocal transferred
                source = await open_stream()
                try:
                    async for chunk in source:
                        transferred += len(chunk)
                        if transferred > backup.size:
                            raise BackupAgentError("Backup stream exceeds declared size")
                        yield chunk
                        on_progress(bytes_uploaded=transferred)
                    if transferred != backup.size:
                        raise BackupAgentError("Backup stream is shorter than declared size")
                finally:
                    if hasattr(source, "aclose"):
                        await source.aclose()

            async with self._request("PUT", staging, statuses=(201, 204), streaming=True,
                                     data=chunks(), headers={
                                         "Content-Type": "application/octet-stream",
                                         "Content-Length": str(backup.size),
                                     }):
                pass
            if transferred != backup.size:
                raise BackupAgentError("Incomplete backup upload")
            async with self._request("HEAD", staging) as response:
                if response.headers.get("Content-Length") != str(backup.size):
                    raise BackupAgentError("Uploaded backup size could not be verified")
            async with self._request("MOVE", staging, statuses=(201, 204),
                                     headers={"Destination": self._base + f"{key}.tar", "Overwrite": "F"}):
                pass
            # Commit marker is last: partial transfers never enter the backup list.
            meta_staging = f"{key}.{uuid4().hex}.partial"
            async with self._request("PUT", meta_staging, statuses=(201, 204), data=metadata,
                                     headers={"Content-Type": "application/json"}):
                pass
            async with self._request("MOVE", meta_staging, statuses=(201, 204),
                                     headers={"Destination": self._base + f"{key}.metadata.json", "Overwrite": "F"}):
                pass
            await get_backup_status(self._hass, self._entry_id).async_completed()

    async def async_download_backup(self, backup_id, **kwargs) -> AsyncIterator[bytes]:
        backup = await self.async_get_backup(backup_id)
        name = f"{self._key(backup_id)}.tar"

        async def chunks():
            received = 0
            async with self._request("GET", name, statuses=(200, 404), streaming=True) as response:
                if response.status == 404:
                    raise BackupNotFound("Backup archive not found")
                async for chunk in response.content.iter_chunked(1024 * 1024):
                    received += len(chunk)
                    if received > backup.size:
                        raise BackupAgentError("Downloaded backup exceeds declared size")
                    yield chunk
                if received != backup.size:
                    raise BackupAgentError("Downloaded backup is incomplete")

        return chunks()

    async def async_delete_backup(self, backup_id, **kwargs):
        async with self._lock:
            await self.async_get_backup(backup_id)
            key = self._key(backup_id)
            # Remove the archive first. If it fails, keep metadata for a retry.
            for name in (f"{key}.tar", f"{key}.metadata.json"):
                async with self._request("DELETE", name, statuses=(200, 204, 404)):
                    pass
