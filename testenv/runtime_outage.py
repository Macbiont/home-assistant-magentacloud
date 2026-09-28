"""Real HA lifecycle with fake quota responses; run in a network-disabled container.

No production/test-UI config volume is mounted. Only the quota client is mocked;
HA setup, entities, coordinator, state events and history storage are real.
The DNS resolver uses aiohttp's threaded resolver because this container has
no multicast-capable interface. Network traffic is blocked by Docker.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import sys
import tempfile
from types import MappingProxyType
from unittest.mock import AsyncMock, patch

from aiohttp.resolver import ThreadedResolver

from homeassistant import bootstrap, loader
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from custom_components.magentacloud.api import (
    MagentaCloudClient, MagentaCloudData, MagentaCloudTemporaryError,
)


class IsolatedResolver(ThreadedResolver):
    """Match HA's shared resolver shutdown contract without multicast."""

    async def close(self):
        """HA owns the shared resolver lifetime, not individual sessions."""

    async def real_close(self):
        await super().close()


async def run():
    with tempfile.TemporaryDirectory(prefix="magentacloud-runtime-") as config:
        Path(config, "custom_components").symlink_to(
            Path(__file__).resolve().parents[1] / "custom_components",
            target_is_directory=True,
        )
        hass = HomeAssistant(config)
        loader.async_setup(hass)
        resolver_patch = patch(
            "homeassistant.helpers.aiohttp_client._async_make_resolver",
            side_effect=lambda hass: IsolatedResolver(),
        )
        resolver_patch.start()
        try:
            assert await bootstrap.async_from_config_dict({}, hass) is hass
            await hass.async_start()
            start = datetime.now(timezone.utc)
            first = MagentaCloudData(2_000_000_000, 1_000_000_000, start, 50)
            recovered = MagentaCloudData(
                2_100_000_000, 900_000_000, start + timedelta(minutes=30), 60,
            )
            entry = ConfigEntry(
                domain="magentacloud", title="Runtime test", version=1,
                minor_version=1, source="user", unique_id="runtime-test",
                data={"url": "https://example.invalid/webdav", "username": "test",
                      "password": "synthetic-not-a-real-password"},
                options={}, discovery_keys=MappingProxyType({}), subentries_data=[],
            )
            with patch.object(MagentaCloudClient, "async_get_quota", new_callable=AsyncMock) as fetch:
                fetch.return_value = first
                await hass.config_entries.async_add(entry)
                await hass.async_block_till_done()
                assert entry.state is ConfigEntryState.LOADED, entry.state
                registry = er.async_get(hass)
                entities = er.async_entries_for_config_entry(registry, entry.entry_id)
                assert len(entities) == 11, len(entities)
                ids = {item.unique_id.removeprefix("runtime-test_"): item.entity_id for item in entities}

                def state(key):
                    value = hass.states.get(ids[key])
                    assert value is not None, key
                    return value.state

                assert state("connection") == "on"
                expected_icons = {
                    "used": "mdi:database", "available": "mdi:database-plus-outline",
                    "total": "mdi:harddisk", "percent_used": "mdi:chart-donut",
                    "daily_change": "mdi:calendar-today", "monthly_change": "mdi:calendar-month",
                    "last_success": "mdi:clock-check-outline", "latency": "mdi:timer-outline",
                    "connection": "mdi:cloud-check-outline",
                }
                for key, icon in expected_icons.items():
                    assert hass.states.get(ids[key]).attributes.get("icon") == icon, key
                assert float(state("used")) == 2.0
                assert state("daily_change") == state("monthly_change") == "unknown"
                last_success = state("last_success")
                store = Store(hass, 1, f"magentacloud.{entry.entry_id}.history")
                history_before = await store.async_load()
                assert len(history_before) == 1
                assert state("backup_enabled") == "off"
                assert state("last_backup") == "unknown"
                from custom_components.magentacloud.backup_status import get_backup_status
                backup_status = get_backup_status(hass, entry.entry_id)
                await backup_status.async_completed()
                await hass.async_block_till_done()
                completed = state("last_backup")
                assert completed not in ("unknown", "unavailable")
                saved_status = await Store(hass, 1, f"magentacloud_backup_status_{entry.entry_id}").async_load()
                assert saved_status["completed_at"] == backup_status.completed_at.isoformat()
                assert datetime.fromisoformat(completed) == backup_status.completed_at.replace(microsecond=0)
                print("PASS: 11 entities, backup timestamp updated and persisted", flush=True)

                events = []
                unsubscribe = hass.bus.async_listen("state_changed", lambda event: events.append(event.data))
                fetch.side_effect = MagentaCloudTemporaryError("Simulated outage")
                await entry.runtime_data.async_refresh()
                await hass.async_block_till_done()
                assert state("connection") == "off"
                assert hass.states.get(ids["connection"]).attributes["icon"] == "mdi:cloud-alert-outline"
                assert state("last_success") == last_success
                assert state("last_backup") == completed
                for key in ("used", "available", "total", "percent_used", "latency", "daily_change", "monthly_change"):
                    assert state(key) == "unavailable", (key, state(key))
                assert await store.async_load() == history_before
                assert any(event["entity_id"] == ids["connection"] and event["new_state"].state == "off" for event in events)
                print("PASS: outage state events, retained timestamp, unchanged history", flush=True)

                fetch.side_effect = None
                fetch.return_value = recovered
                await entry.runtime_data.async_refresh()
                await hass.async_block_till_done()
                assert state("connection") == "on"
                assert float(state("used")) == 2.1
                assert hass.states.get(ids["connection"]).attributes["icon"] == "mdi:cloud-check-outline"
                assert state("last_success") != last_success
                assert len(await store.async_load()) == 2
                assert any(event["entity_id"] == ids["connection"] and event["new_state"].state == "on" for event in events)
                unsubscribe()
                print("PASS: recovery state events, fresh values, persisted history", flush=True)

                coordinator = entry.runtime_data
                assert await hass.config_entries.async_unload(entry.entry_id)
                await hass.async_block_till_done()
                assert not list(coordinator.async_contexts())
                hass.data.pop("magentacloud_backup_status")
                assert await hass.config_entries.async_setup(entry.entry_id)
                await hass.async_block_till_done()
                reloaded = er.async_entries_for_config_entry(registry, entry.entry_id)
                assert {item.entity_id for item in reloaded} == set(ids.values())
                assert state("connection") == "on"
                assert len(await store.async_load()) == 3
                assert state("last_backup") == completed
                print("PASS: unload/reload, stable entity IDs, history retained", flush=True)

                integration = await loader.async_get_integration(hass, "magentacloud")
                platform = await integration.async_get_platform("backup")
                assert await platform.async_get_backup_agents(hass) == []
                notifications = []
                remove_listener = platform.async_register_backup_agents_listener(
                    hass, listener=lambda: notifications.append(True),
                )
                result = await hass.config_entries.options.async_init(entry.entry_id)
                assert result["type"] == "form", result
                result = await hass.config_entries.options.async_configure(
                    result["flow_id"], user_input={"backup_enabled": True},
                )
                assert result["type"] == "create_entry", result
                await hass.async_block_till_done()
                agents = await platform.async_get_backup_agents(hass)
                assert [agent.agent_id for agent in agents] == [f"magentacloud.{entry.entry_id}"]
                assert notifications
                assert state("backup_enabled") == "on"
                result = await hass.config_entries.options.async_init(entry.entry_id)
                await hass.config_entries.options.async_configure(
                    result["flow_id"], user_input={"backup_enabled": False},
                )
                await hass.async_block_till_done()
                assert await platform.async_get_backup_agents(hass) == []
                assert state("backup_enabled") == "off"
                old_coordinator = entry.runtime_data
                fetches_before = fetch.await_count
                for service, expected in (("turn_on", "on"), ("turn_off", "off")):
                    await hass.services.async_call(
                        "switch", service, {"entity_id": ids["backup_enabled"]}, blocking=True,
                    )
                    await hass.async_block_till_done()
                    assert state("backup_enabled") == expected
                    assert bool(await platform.async_get_backup_agents(hass)) == (expected == "on")
                    assert entry.runtime_data is old_coordinator
                assert fetch.await_count == fetches_before
                print("PASS: switch and options stay synchronized without reload or cloud polling", flush=True)
                remove_listener()
                print("PASS: backup platform discovery, options opt-in/out and lifecycle listeners", flush=True)

                for enabled in (False, True):
                    flow = await hass.config_entries.flow.async_init("magentacloud", context={"source": "user"})
                    defaults = flow["data_schema"]({"url": "https://example.invalid/dav", "username": "user", "password": "synthetic"})
                    assert defaults["backup_enabled"] is False
                    result = await hass.config_entries.flow.async_configure(flow["flow_id"], user_input={
                        "url": "https://example.invalid/dav", "username": f"new-user-{enabled}",
                        "password": "synthetic", "backup_enabled": enabled,
                    })
                    assert result["type"] == "create_entry", result["type"]
                    assert result["result"].options["backup_enabled"] is enabled
                    assert "backup_enabled" not in result["result"].data
                    await hass.async_block_till_done()
                print("PASS: initial setup checkbox defaults off and persists both selections", flush=True)
        finally:
            await hass.async_stop(force=True)
            resolver_patch.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    asyncio.run(run())
