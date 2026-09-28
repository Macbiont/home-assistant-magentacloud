"""Real aiohttp streaming and real HA backup types against loopback WebDAV.

No cloud credentials. The test-only session adapter maps HTTPS to loopback HTTP;
TLS/provider compatibility must be checked separately before release.
"""

import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit

from aiohttp import ClientSession, web
from homeassistant.components.backup import AgentBackup, BackupAgentError, BackupNotFound

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from custom_components.magentacloud.backup import MagentaCloudBackupAgent, async_get_backup_agents


class BackupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.files = {}
        self.calls = []
        self.fail = None
        self.folder = "/dav/HomeAssistant-MagentaCloud/"
        app = web.Application(client_max_size=8 * 1024 * 1024)
        app.router.add_route("*", "/{path:.*}", self.handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = self.runner.addresses[0][1]
        self.session = ClientSession()
        session = self.session

        class LoopbackSession:
            def request(inner, method, url, **kwargs):
                self.assertFalse(kwargs["allow_redirects"])
                self.assertTrue(url.startswith("https://example.invalid/dav/"))
                return session.request(method, f"http://127.0.0.1:{port}" + urlsplit(url).path, **kwargs)

        self.entry = SimpleNamespace(
            title="Test", entry_id="test", options={"backup_enabled": True},
            data={"url": "https://example.invalid/dav", "username": "synthetic", "password": "synthetic"},
        )
        self.session_patch = patch("custom_components.magentacloud.backup.async_get_clientsession", return_value=LoopbackSession())
        self.session_patch.start()
        self.status = SimpleNamespace(async_completed=AsyncMock())
        status_patch = patch("custom_components.magentacloud.backup.get_backup_status", return_value=self.status)
        status_patch.start()
        self.addCleanup(status_patch.stop)
        self.agent = MagentaCloudBackupAgent(None, self.entry)
        self.payload = b"backup-content" * 10000
        self.backup = AgentBackup(
            backup_id="test-backup", name="Test", date="2026-08-30T12:00:00+00:00",
            addons=[], folders=[], database_included=True, extra_metadata={},
            homeassistant_included=True, homeassistant_version="2026.9.3",
            protected=True, size=len(self.payload),
        )

    async def asyncTearDown(self):
        self.session_patch.stop()
        await self.session.close()
        await self.runner.cleanup()

    async def handle(self, request):
        self.assertEqual(request.headers.get("Accept-Encoding"), "identity")
        self.assertTrue(request.headers.get("Authorization", "").startswith("Basic "))
        path, method = request.path, request.method
        self.calls.append((method, path))
        if self.fail and self.fail(method, path):
            return web.Response(status=503)
        if method == "MKCOL":
            return web.Response(status=201)
        if method == "PUT":
            if request.headers.get("Content-Type") == "application/octet-stream":
                self.assertIsNotNone(request.content_length)
                self.assertNotIn("Transfer-Encoding", request.headers)
            try:
                self.files[path] = await request.read()
            except ConnectionResetError:
                return web.Response(status=400)
            return web.Response(status=201)
        if method == "MOVE":
            destination = urlsplit(request.headers["Destination"]).path
            self.assertEqual(request.headers["Overwrite"], "F")
            if destination in self.files:
                return web.Response(status=412)
            self.files[destination] = self.files.pop(path)
            return web.Response(status=201)
        if method == "PROPFIND":
            self.assertEqual(request.headers["Depth"], "1")
            entries = "".join(f"<d:response><d:href>{p}</d:href></d:response>" for p in self.files)
            return web.Response(status=207, text=f'<d:multistatus xmlns:d="DAV:">{entries}</d:multistatus>')
        if method == "DELETE":
            self.files.pop(path, None)
            return web.Response(status=204)
        if path not in self.files:
            return web.Response(status=404)
        return web.Response(body=self.files[path])

    async def upload(self, backup=None, payload=None):
        data = self.payload if payload is None else payload
        async def stream():
            async def chunks():
                for offset in range(0, len(data), 4096):
                    yield data[offset:offset + 4096]
            return chunks()
        self.progress = []
        await self.agent.async_upload_backup(
            open_stream=stream, backup=backup or self.backup,
            on_progress=lambda **value: self.progress.append(value["bytes_uploaded"]),
        )

    async def test_roundtrip_and_scoped_delete(self):
        self.files["/unrelated.txt"] = b"keep"
        await self.upload()
        self.assertEqual(self.progress[-1], self.backup.size)
        self.status.async_completed.assert_awaited_once()
        self.assertEqual(await self.agent.async_list_backups(), [self.backup])
        iterator = await self.agent.async_download_backup(self.backup.backup_id)
        self.assertEqual(b"".join([chunk async for chunk in iterator]), self.payload)
        await self.agent.async_delete_backup(self.backup.backup_id)
        self.assertEqual(await self.agent.async_list_backups(), [])
        self.assertEqual(self.files, {"/unrelated.txt": b"keep"})

    async def test_unencrypted_rejected_before_network(self):
        with self.assertRaises(BackupAgentError):
            await self.upload(replace(self.backup, protected=False))
        self.assertEqual(self.calls, [])
        self.status.async_completed.assert_not_awaited()

    async def test_short_upload_never_committed(self):
        with self.assertRaises(BackupAgentError):
            await self.upload(payload=b"short")
        self.assertFalse(any(p.endswith(".metadata.json") for p in self.files))
        self.status.async_completed.assert_not_awaited()
        self.assertEqual(await self.agent.async_list_backups(), [])

    async def test_existing_backup_not_overwritten(self):
        await self.upload()
        before = dict(self.files)
        with self.assertRaises(BackupAgentError):
            await self.upload()
        self.assertEqual(self.files, before)

    async def test_metadata_failure_leaves_archive_unlisted(self):
        self.fail = lambda method, path: method == "MOVE" and any(p.endswith(".tar") for p in self.files)
        with self.assertRaises(BackupAgentError):
            await self.upload()
        self.fail = None
        self.status.async_completed.assert_not_awaited()
        self.assertEqual(await self.agent.async_list_backups(), [])
        self.assertTrue(any(p.endswith(".tar") for p in self.files))

    async def test_truncated_download_fails_during_iteration(self):
        await self.upload()
        name = self.folder + self.agent._key(self.backup.backup_id) + ".tar"
        self.files[name] = b"short"
        iterator = await self.agent.async_download_backup(self.backup.backup_id)
        with self.assertRaises(BackupAgentError):
            async for chunk in iterator:
                pass

    async def test_delete_failure_retains_metadata(self):
        await self.upload()
        before = dict(self.files)
        self.fail = lambda method, path: method == "DELETE"
        with self.assertRaises(BackupAgentError):
            await self.agent.async_delete_backup(self.backup.backup_id)
        self.assertEqual(self.files, before)

    async def test_missing_and_corrupt_metadata(self):
        with self.assertRaises(BackupNotFound):
            await self.agent.async_get_backup("missing")
        name = self.folder + self.agent._key("bad") + ".metadata.json"
        self.files[name] = b"invalid json"
        with self.assertRaises(BackupAgentError):
            await self.agent.async_list_backups()

    async def test_opt_in_discovery(self):
        hass = SimpleNamespace(config_entries=SimpleNamespace(async_loaded_entries=lambda domain: [self.entry]))
        self.entry.options = {}
        self.assertEqual(await async_get_backup_agents(hass), [])
        self.entry.options = {"backup_enabled": True}
        agents = await async_get_backup_agents(hass)
        self.assertEqual([agent.agent_id for agent in agents], ["magentacloud.test"])

    async def test_cancelled_upload_never_committed(self):
        started = asyncio.Event()
        hold = asyncio.Event()
        closed = asyncio.Event()
        async def stream():
            async def chunks():
                try:
                    yield b"start"
                    started.set()
                    await hold.wait()
                finally:
                    closed.set()
            return chunks()
        task = asyncio.create_task(self.agent.async_upload_backup(
            open_stream=stream, backup=self.backup, on_progress=lambda **kw: None,
        ))
        await asyncio.wait_for(started.wait(), 5)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(closed.wait(), 5)
        self.assertFalse(any(p.endswith(".metadata.json") for p in self.files))

    async def test_untrusted_ids_never_become_paths(self):
        backup = replace(self.backup, backup_id="../../private/config")
        await self.upload(backup)
        self.assertTrue(all(p.startswith(self.folder) for p in self.files))
        await self.agent.async_delete_backup(backup.backup_id)
        self.assertEqual(self.files, {})

    async def test_foreign_folder_metadata_ignored(self):
        self.files["/elsewhere/" + self.agent._key(self.backup.backup_id) + ".metadata.json"] = json.dumps(self.backup.as_dict()).encode()
        self.assertEqual(await self.agent.async_list_backups(), [])
        self.assertFalse(any(method == "GET" for method, path in self.calls))

    async def test_oversized_metadata_rejected(self):
        name = self.folder + self.agent._key(self.backup.backup_id) + ".metadata.json"
        self.files[name] = b" " * (1024 * 1024 + 1)
        with self.assertRaises(BackupAgentError):
            await self.agent.async_get_backup(self.backup.backup_id)

    async def test_unsafe_endpoints_rejected(self):
        for url in ("http://example.invalid", "https://u:p@example.invalid",
                    "https://example.invalid:99999", "https://[broken", "https://example.invalid?q=secret"):
            self.entry.data["url"] = url
            with self.assertRaises(BackupAgentError):
                MagentaCloudBackupAgent(None, self.entry)


if __name__ == "__main__":
    unittest.main(verbosity=2)
