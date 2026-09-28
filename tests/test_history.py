"""Isolated production-history tests with a fake Home Assistant Store.

Only the HA and API imports are replaced; the complete history implementation
runs unchanged. Real HA storage/event-loop integration tests are still required.
"""

import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock


SOURCE = (Path(__file__).resolve().parents[1] / "custom_components"
          / "magentacloud" / "history.py")
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
tree.body = [node for node in tree.body if not (
    isinstance(node, ast.ImportFrom)
    and (node.level or (node.module or "").startswith("homeassistant"))
)]


class FakeStore:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, *args):
        self.async_load = AsyncMock(return_value=None)
        self.async_save = AsyncMock()


namespace = {
    "__name__": "magentacloud_history_test",
    "HomeAssistant": object,
    "Store": FakeStore,
    "MagentaCloudData": SimpleNamespace,
}
exec(compile(tree, str(SOURCE), "exec"), namespace)
UsageHistory = namespace["UsageHistory"]
LOGGER = namespace["_LOGGER"].name


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.history = UsageHistory(None, "test-entry")
        self.store = self.history._store
        self.now = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
        self.data = SimpleNamespace(
            used=150, available=850, last_success=self.now, latency_ms=12.5
        )

    def sample(self, days=1, used=100):
        return {"timestamp": (self.now - timedelta(days=days)).isoformat(),
                "used": used}

    def assert_live_values(self, result):
        for field in ("used", "available", "last_success", "latency_ms"):
            self.assertEqual(getattr(result, field), getattr(self.data, field))

    async def test_empty_store_collects_and_saves(self):
        await self.history.async_load()
        result = await self.history.async_enrich(self.data)
        self.assert_live_values(result)
        self.assertIsNone(result.daily_change)
        self.store.async_save.assert_awaited_once()

    async def test_unreadable_store_preserved_and_live_values_continue(self):
        for error in (OSError("private path"), ValueError("private contents")):
            with self.subTest(error=type(error).__name__):
                history = UsageHistory(None, "test-entry")
                history._store.async_load.side_effect = error
                with self.assertLogs(LOGGER, level="WARNING") as logs:
                    await history.async_load()
                self.assertNotIn("private", " ".join(logs.output))
                result = await history.async_enrich(self.data)
                self.assert_live_values(result)
                history._store.async_save.assert_not_awaited()

    async def test_invalid_top_level_preserved(self):
        for value in ({}, "invalid", 42, False):
            with self.subTest(value=value):
                history = UsageHistory(None, "test-entry")
                history._store.async_load.return_value = value
                with self.assertLogs(LOGGER, level="WARNING"):
                    await history.async_load()
                self.assert_live_values(await history.async_enrich(self.data))
                history._store.async_save.assert_not_awaited()

    async def test_bad_entries_do_not_discard_valid_baseline(self):
        self.store.async_load.return_value = [
            self.sample(), None, {}, {"timestamp": "invalid", "used": 100},
            {"timestamp": "2026-08-29T12:00:00", "used": 100},
            {"timestamp": None, "used": 100},
            self.sample(used=-1), self.sample(used=True), self.sample(used="100"),
        ]
        with self.assertLogs(LOGGER, level="WARNING"):
            await self.history.async_load()
        result = await self.history.async_enrich(self.data)
        self.assert_live_values(result)
        self.assertEqual(result.daily_change, 50)
        self.store.async_save.assert_not_awaited()

    async def test_save_failure_retries_and_recovers_without_log_spam(self):
        self.store.async_load.return_value = [self.sample()]
        await self.history.async_load()
        self.store.async_save.side_effect = [OSError("disk full"), OSError(), None]
        with self.assertLogs(LOGGER, level="INFO") as logs:
            for _ in range(3):
                result = await self.history.async_enrich(self.data)
                self.assert_live_values(result)
                self.assertEqual(result.daily_change, 50)
        self.assertEqual(len(logs.output), 2)
        self.assertIn("WARNING", logs.output[0])
        self.assertIn("recovered", logs.output[1])
        self.assertEqual(len(self.store.async_save.call_args.args[0]), 4)

    async def test_save_cancellation_propagates(self):
        self.store.async_save.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.history.async_enrich(self.data)

    async def test_load_cancellation_propagates(self):
        self.store.async_load.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.history.async_load()

    async def test_future_and_expired_samples_are_excluded(self):
        self.store.async_load.return_value = [self.sample(-2), self.sample(33)]
        await self.history.async_load()
        result = await self.history.async_enrich(self.data)
        self.assertIsNone(result.daily_change)
        self.assertIsNone(result.monthly_change)
        self.assertEqual(len(self.history._samples), 1)

    async def test_valid_baseline_is_normalized_to_utc(self):
        self.store.async_load.return_value = [
            {"timestamp": "2026-08-29T14:00:00+02:00", "used": 100}
        ]
        await self.history.async_load()
        self.assertEqual(self.history._samples[0]["timestamp"],
                         "2026-08-29T12:00:00+00:00")
        self.assertEqual((await self.history.async_enrich(self.data)).daily_change, 50)

    async def test_baseline_tolerance_boundaries_for_both_windows(self):
        for days, field in ((1, "daily_change"), (30, "monthly_change")):
            for offset, expected in (
                (timedelta(), 50),
                (-timedelta(minutes=30), 50),
                (-timedelta(minutes=35), 50),
                (-timedelta(minutes=35, microseconds=1), None),
                (timedelta(microseconds=1), None),
            ):
                with self.subTest(days=days, offset=offset):
                    history = UsageHistory(None, "test-entry")
                    history._store.async_load.return_value = [{
                        "timestamp": (self.now - timedelta(days=days)
                                      + offset).isoformat(),
                        "used": 100,
                    }]
                    await history.async_load()
                    result = await history.async_enrich(self.data)
                    self.assertEqual(getattr(result, field), expected)

    async def test_old_baseline_does_not_expand_daily_window(self):
        self.store.async_load.return_value = [self.sample(days=3)]
        await self.history.async_load()
        self.assertIsNone((await self.history.async_enrich(self.data)).daily_change)

    async def test_latest_eligible_baseline_wins_regardless_of_order(self):
        target = self.now - timedelta(days=1)
        self.store.async_load.return_value = [
            {"timestamp": (target - timedelta(minutes=5)).isoformat(), "used": 120},
            {"timestamp": (target + timedelta(minutes=5)).isoformat(), "used": 999},
            {"timestamp": (target - timedelta(minutes=30)).isoformat(), "used": 100},
        ]
        await self.history.async_load()
        self.assertEqual((await self.history.async_enrich(self.data)).daily_change, 30)

    async def test_negative_and_zero_net_changes_are_valid(self):
        for baseline, expected in ((200, -50), (150, 0)):
            with self.subTest(baseline=baseline):
                history = UsageHistory(None, "test-entry")
                history._store.async_load.return_value = [
                    self.sample(1, baseline), self.sample(30, baseline)
                ]
                await history.async_load()
                result = await history.async_enrich(self.data)
                self.assertEqual(result.daily_change, expected)
                self.assertEqual(result.monthly_change, expected)

    async def test_missing_daily_baseline_does_not_hide_monthly_change(self):
        self.store.async_load.return_value = [self.sample(30)]
        await self.history.async_load()
        result = await self.history.async_enrich(self.data)
        self.assertIsNone(result.daily_change)
        self.assertEqual(result.monthly_change, 50)

    async def test_fixed_windows_across_dst_changes(self):
        for now_text, daily_text, monthly_text in (
            ("2026-03-29T12:00:00+02:00", "2026-03-28T11:00:00+01:00",
             "2026-02-27T11:00:00+01:00"),
            ("2026-10-25T12:00:00+01:00", "2026-10-24T13:00:00+02:00",
             "2026-09-25T13:00:00+02:00"),
        ):
            with self.subTest(now=now_text):
                history = UsageHistory(None, "test-entry")
                history._store.async_load.return_value = [
                    {"timestamp": daily_text, "used": 100},
                    {"timestamp": monthly_text, "used": 50},
                ]
                await history.async_load()
                data = SimpleNamespace(
                    used=150, available=850, latency_ms=10,
                    last_success=datetime.fromisoformat(now_text),
                )
                result = await history.async_enrich(data)
                self.assertEqual(result.daily_change, 50)
                self.assertEqual(result.monthly_change, 100)

    async def test_gap_recovers_when_valid_baseline_becomes_old_enough(self):
        self.store.async_load.return_value = [self.sample(3)]
        await self.history.async_load()
        result = await self.history.async_enrich(self.data)
        self.assertIsNone(result.daily_change)
        later = SimpleNamespace(
            used=175, available=825, latency_ms=10,
            last_success=self.now + timedelta(days=1, minutes=1),
        )
        result = await self.history.async_enrich(later)
        self.assertEqual(result.daily_change, 25)


if __name__ == "__main__":
    unittest.main()
