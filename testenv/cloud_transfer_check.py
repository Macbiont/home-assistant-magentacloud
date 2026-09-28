"""Explicitly authorized synthetic cloud transfer check, run inside the test HA.

Reads only the MagentaCLOUD config entry; never prints credentials. This tests
transport, not the Home Assistant backup encryption format or full restoration.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import secrets
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit
from uuid import uuid4

from aiohttp import ClientSession
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from homeassistant.components.backup import AgentBackup
from homeassistant.components.backup import BackupAgentError

sys.path.insert(0, "/config")
from custom_components.magentacloud.backup import MagentaCloudBackupAgent


async def main():
    config = json.loads(Path("/config/.storage/core.config_entries").read_text())
    entries = [entry for entry in config["data"]["entries"] if entry["domain"] == "magentacloud"]
    if len(entries) != 1:
        raise RuntimeError("Expected exactly one MagentaCLOUD test entry")
    data = entries[0]["data"]
    if urlsplit(data["url"]).hostname != "magentacloud.de":
        raise RuntimeError("Unexpected cloud destination; stopping")
    backup_id = "synthetic-transfer-" + uuid4().hex
    plaintext = b"Synthetic MagentaCLOUD transport test; no user data.\n" * 1024
    key = AESGCM.generate_key(bit_length=256)
    nonce = secrets.token_bytes(12)
    payload = nonce + AESGCM(key).encrypt(nonce, plaintext, None)
    backup = AgentBackup(
        backup_id=backup_id, name="Synthetic transport test - not a restorable HA backup",
        date=datetime.now(timezone.utc).isoformat(), addons=[], folders=[],
        database_included=False, extra_metadata={}, homeassistant_included=False,
        homeassistant_version="2026.9.3", protected=True, size=len(payload),
    )
    touched = set()

    class TrackedAgent(MagentaCloudBackupAgent):
        @asynccontextmanager
        async def _request(self, method, name="", **kwargs):
            # Only synthetic run-owned archive/metadata and unique staging files.
            if method in ("PUT", "MOVE"):
                assert name.startswith(self._key(backup_id) + ".")
                touched.add(name)
                if method == "MOVE":
                    destination = kwargs["headers"]["Destination"]
                    assert destination.startswith(self._base + self._key(backup_id) + ".")
                    touched.add(destination[len(self._base):])
            async with super()._request(method, name, **kwargs) as response:
                if method == "HEAD" and name.endswith(".partial") and response.status == 200:
                    print("Staging HEAD length: " + str(response.headers.get("Content-Length")), flush=True)
                yield response

    async with ClientSession() as session:
        with patch("custom_components.magentacloud.backup.async_get_clientsession", return_value=session):
            agent = TrackedAgent(None, SimpleNamespace(title="Synthetic test", entry_id="synthetic", data=data))
        prefix = agent._key(backup_id)
        for suffix in (".tar", ".metadata.json"):
            async with agent._request("HEAD", prefix + suffix, statuses=(200, 404)) as response:
                if response.status != 404:
                    raise RuntimeError("Test target already exists; stopping")

        print(f"Synthetic test ID: {backup_id}; encrypted bytes: {len(payload)}", flush=True)
        try:
            async def open_stream():
                async def chunks():
                    for offset in range(0, len(payload), 4096):
                        yield payload[offset:offset + 4096]
                return chunks()

            async with asyncio.timeout(180):
                # Synthetic transport test has no real HA instance/status store.
                with patch("custom_components.magentacloud.backup.get_backup_status",
                           return_value=SimpleNamespace(async_completed=AsyncMock())):
                    await agent.async_upload_backup(open_stream=open_stream, backup=backup, on_progress=lambda **kw: None)
                print("PASS: cloud upload, size verification and MOVE", flush=True)
                listed = await agent.async_list_backups()
                assert any(item.backup_id == backup_id for item in listed)
                print("PASS: synthetic backup listed", flush=True)
                stream = await agent.async_download_backup(backup_id)
                downloaded = b"".join([chunk async for chunk in stream])
                assert sha256(downloaded).digest() == sha256(payload).digest()
                assert AESGCM(key).decrypt(downloaded[:12], downloaded[12:], None) == plaintext
                print("PASS: download SHA-256 and synthetic decryption match", flush=True)
                await agent.async_delete_backup(backup_id)
                print("PASS: agent deleted synthetic archive and metadata", flush=True)
        finally:
            # Never delete the shared directory or files not created/attempted by this run.
            failures = []
            for name in sorted(touched):
                try:
                    async with agent._request("DELETE", name, statuses=(200, 204, 404)):
                        pass
                    async with agent._request("HEAD", name, statuses=(200, 404)) as response:
                        if response.status != 404:
                            failures.append(name)
                except Exception:
                    failures.append(name)
            if failures:
                print("CLEANUP INCOMPLETE for synthetic paths: " + ", ".join(failures), flush=True)
                raise RuntimeError("Synthetic file cleanup needs attention")
            print("PASS: all run-owned cloud files absent; shared folder retained", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        # No raw transport errors, request URLs, config data or tracebacks.
        print(f"FAIL: {type(error).__name__}", flush=True)
        if isinstance(error, BackupAgentError):
            print(str(error), flush=True)
        sys.exit(1)
