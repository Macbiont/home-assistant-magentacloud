"""Isolated tests for persisted upload completion (HA storage is doubled)."""

import ast
import asyncio
from datetime import datetime, timezone
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


SOURCE = Path(__file__).resolve().parents[1] / "custom_components/magentacloud"


class StatusTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tree = ast.parse((SOURCE / "backup_status.py").read_text())
        tree.body = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))]
        self.store = SimpleNamespace(async_load=AsyncMock(return_value=None), async_save=AsyncMock())
        self.send = Mock()
        self.ns = dict(asyncio=asyncio, datetime=datetime, timezone=timezone,
                       logging=logging, DOMAIN="magentacloud", __name__=__name__,
                       Store=Mock(return_value=self.store), async_dispatcher_send=self.send)
        exec(compile(tree, str(SOURCE / "backup_status.py"), "exec"), self.ns)
        self.hass = SimpleNamespace(data={})
        self.status = self.ns["get_backup_status"](self.hass, "test")

    async def test_unknown_then_persisted_completion(self):
        await self.status.async_load()
        self.assertIsNone(self.status.completed_at)
        await self.status.async_completed()
        value = self.status.completed_at
        self.assertIsNotNone(value.tzinfo)
        self.store.async_save.assert_awaited_once_with({"completed_at": value.isoformat()})
        self.send.assert_called_once_with(self.hass, "magentacloud_backup_completed_test")

    async def test_restore_and_cached_load(self):
        stamp = "2026-08-31T14:00:00+00:00"
        self.store.async_load.return_value = {"completed_at": stamp}
        await asyncio.gather(self.status.async_load(), self.status.async_load())
        self.assertEqual(self.status.completed_at.isoformat(), stamp)
        self.store.async_load.assert_awaited_once()
        self.assertIs(self.status, self.ns["get_backup_status"](self.hass, "test"))

    async def test_invalid_timestamp_is_unknown(self):
        for data in ({}, {"completed_at": "bad"}, {"completed_at": "2026-08-31T12:00:00"}, []):
            self.store.async_load.return_value = data
            status = self.ns["BackupStatus"](self.hass, "bad")
            with self.assertLogs(__name__, level="WARNING"):
                await status.async_load()
            self.assertIsNone(status.completed_at)

    async def test_save_failure_does_not_fail_committed_backup(self):
        self.store.async_save.side_effect = OSError("disk full")
        with self.assertLogs(__name__, level="WARNING"):
            await self.status.async_completed()
        self.assertIsNotNone(self.status.completed_at)
        self.send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
