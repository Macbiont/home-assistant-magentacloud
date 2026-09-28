"""Dependency-free tests of the production entity properties.

Extract the real property implementations with AST, without importing Home
Assistant. The base-class double models CoordinatorEntity.available. These are
isolated unit tests, not tests of HA startup, entity registration or event delivery.
"""

import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "custom_components" / "magentacloud"


class CoordinatorDouble:
    @property
    def available(self):
        return self.coordinator.last_update_success


def load_properties(filename, class_name, properties):
    tree = ast.parse((SOURCE / filename).read_text(encoding="utf-8"))
    entity = next(node for node in tree.body
                  if isinstance(node, ast.ClassDef) and node.name == class_name)
    entity.bases = [ast.Name(id="CoordinatorDouble", ctx=ast.Load())]
    entity.body = [node for node in entity.body
                   if isinstance(node, ast.FunctionDef) and node.name in properties]
    assert {node.name for node in entity.body} == set(properties)
    module = ast.fix_missing_locations(ast.Module(body=[entity], type_ignores=[]))
    namespace = {"CoordinatorDouble": CoordinatorDouble}
    exec(compile(module, str(SOURCE / filename), "exec"), namespace)
    return namespace[class_name]


Connection = load_properties(
    "binary_sensor.py", "MagentaCloudConnectionSensor", {"available", "is_on", "icon"}
)
Sensor = load_properties(
    "sensor.py", "MagentaCloudSensor", {"available", "native_value"}
)


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.timestamp = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
        self.coordinator = SimpleNamespace(
            last_update_success=True,
            data=SimpleNamespace(last_success=self.timestamp, used=123),
        )

    def sensor(self, key):
        entity = Sensor()
        entity.coordinator = self.coordinator
        entity.entity_description = SimpleNamespace(
            key=key, value_fn=lambda data: getattr(data, key)
        )
        return entity

    def test_connection_success_failure_recovery(self):
        entity = Connection()
        entity.coordinator = self.coordinator
        for success in (True, False, False, True):
            self.coordinator.last_update_success = success
            self.assertTrue(entity.available)
            self.assertEqual(entity.is_on, success)

    def test_last_success_survives_failure(self):
        entity = self.sensor("last_success")
        self.coordinator.last_update_success = False
        self.assertTrue(entity.available)
        self.assertEqual(entity.native_value, self.timestamp)

    def test_connection_icon_tracks_failure_and_recovery(self):
        entity = Connection()
        entity.coordinator = self.coordinator
        for success, icon in (
            (True, "mdi:cloud-check-outline"),
            (False, "mdi:cloud-alert-outline"),
            (True, "mdi:cloud-check-outline"),
        ):
            self.coordinator.last_update_success = success
            self.assertEqual(entity.icon, icon)

    def test_last_success_changes_after_recovery(self):
        entity = self.sensor("last_success")
        self.coordinator.last_update_success = False
        self.coordinator.data = SimpleNamespace(
            last_success=datetime(2026, 8, 30, 13, tzinfo=timezone.utc)
        )
        self.coordinator.last_update_success = True
        self.assertTrue(entity.available)
        self.assertEqual(entity.native_value.hour, 13)

    def test_current_sensors_remain_unavailable_during_failure(self):
        for key in ("used", "available", "total", "percent_used",
                    "latency", "daily_change", "monthly_change"):
            with self.subTest(key=key):
                entity = self.sensor(key)
                self.coordinator.last_update_success = False
                self.assertFalse(entity.available)
                self.coordinator.last_update_success = True
                self.assertTrue(entity.available)

    def test_no_timestamp_is_invented_without_data(self):
        self.coordinator.data = None
        self.coordinator.last_update_success = False
        entity = self.sensor("last_success")
        self.assertFalse(entity.available)
        self.assertIsNone(entity.native_value)


if __name__ == "__main__":
    unittest.main()
