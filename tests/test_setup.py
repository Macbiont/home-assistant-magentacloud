"""Isolated setup/coordinator boundary tests; no HA runtime is simulated."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from test_api import api


class ConfigEntryAuthFailed(Exception):
    pass


class UpdateFailed(Exception):
    pass


class SetupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = SimpleNamespace(async_get_quota=AsyncMock())
        self.history = SimpleNamespace(async_load=AsyncMock(), async_enrich=AsyncMock())
        self.entry = SimpleNamespace(entry_id="test", data={
            "url": "https://example.org/webdav", "username": "user", "password": "secret",
        })
        self.entry.async_on_unload = Mock()
        self.entry.async_on_state_change = Mock()
        self.entry.add_update_listener = Mock()
        self.hass = SimpleNamespace(config_entries=SimpleNamespace(
            async_forward_entry_setups=AsyncMock(),
            async_unload_platforms=AsyncMock(return_value=True),
        ))

        def coordinator_factory(*args, **kwargs):
            self.update = kwargs["update_method"]
            self.coordinator = SimpleNamespace(
                async_config_entry_first_refresh=AsyncMock(side_effect=self.update),
            )
            return self.coordinator

        path = Path(__file__).parents[1] / "custom_components/magentacloud/__init__.py"
        source = ast.parse(path.read_text())
        functions = [node for node in source.body if isinstance(node, ast.AsyncFunctionDef)]
        # Postpone HA type annotations while executing the unchanged functions.
        tree = ast.Module(body=[ast.ImportFrom(module="__future__", names=[
            ast.alias(name="annotations")], level=0), *functions], type_ignores=[])
        self.namespace = dict(
            MagentaCloudClient=Mock(return_value=self.client),
            UsageHistory=Mock(return_value=self.history),
            async_get_clientsession=Mock(return_value=object()),
            DataUpdateCoordinator=coordinator_factory,
            MagentaCloudAuthenticationError=api.MagentaCloudAuthenticationError,
            MagentaCloudError=api.MagentaCloudError,
            ConfigEntryAuthFailed=ConfigEntryAuthFailed, UpdateFailed=UpdateFailed,
            CONF_URL="url", CONF_USERNAME="username", CONF_PASSWORD="password",
            LOGGER=Mock(), DOMAIN="magentacloud", DEFAULT_SCAN_INTERVAL=1800,
            DATA_BACKUP_LISTENERS="magentacloud_backup_listeners",
            PLATFORMS=["binary_sensor", "sensor"],
        )
        exec(compile(ast.fix_missing_locations(tree), str(path), "exec"), self.namespace)

    async def setup_entry(self):
        return await self.namespace["async_setup_entry"](self.hass, self.entry)

    async def test_success_initializes_and_forwards_platforms(self):
        self.assertTrue(await self.setup_entry())
        self.history.async_load.assert_awaited_once()
        self.history.async_enrich.assert_awaited_once_with(self.client.async_get_quota.return_value)
        self.assertIs(self.entry.runtime_data, self.coordinator)
        self.hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
            self.entry, ["binary_sensor", "sensor"])

    async def test_auth_failure_requests_reauthentication(self):
        self.client.async_get_quota.side_effect = api.MagentaCloudAuthenticationError()
        with self.assertRaises(ConfigEntryAuthFailed):
            await self.setup_entry()
        self.history.async_enrich.assert_not_awaited()
        self.hass.config_entries.async_forward_entry_setups.assert_not_awaited()

    async def test_other_failures_do_not_request_reauthentication(self):
        for error in (api.MagentaCloudPermissionError, api.MagentaCloudTemporaryError,
                      api.MagentaCloudUrlError, api.MagentaCloudQuotaUnavailableError,
                      api.MagentaCloudError):
            with self.subTest(error=error.__name__):
                self.client.async_get_quota.side_effect = error()
                with self.assertRaises(UpdateFailed):
                    await self.setup_entry()
                self.history.async_enrich.assert_not_awaited()
                self.hass.config_entries.async_forward_entry_setups.assert_not_awaited()
                self.assertFalse(hasattr(self.entry, "runtime_data"))

    async def test_failed_refresh_then_recovery_preserves_history_boundary(self):
        await self.setup_entry()
        self.history.async_enrich.reset_mock()
        self.client.async_get_quota.side_effect = api.MagentaCloudTemporaryError()
        with self.assertRaises(UpdateFailed):
            await self.update()
        self.history.async_enrich.assert_not_awaited()
        self.client.async_get_quota.side_effect = None
        self.assertIs(await self.update(), self.history.async_enrich.return_value)
        self.history.async_enrich.assert_awaited_once()

    async def test_cancel_is_not_converted_to_connection_error(self):
        self.client.async_get_quota.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.setup_entry()
        self.hass.config_entries.async_forward_entry_setups.assert_not_awaited()

    async def test_unload_result_is_propagated(self):
        for result in (True, False):
            self.hass.config_entries.async_unload_platforms.return_value = result
            self.assertIs(await self.namespace["async_unload_entry"](self.hass, self.entry), result)
