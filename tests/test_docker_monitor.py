from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


class FakeDockerApi:
    def __init__(self) -> None:
        self.container_calls = 0
        self.stats_calls = 0
        self.restart_calls = 0

    def containers(self, **kwargs):
        self.container_calls += 1
        return [
            {
                "Id": "container-1",
                "Names": ["/api-1"],
                "Image": "example/api:latest",
                "State": "running",
                "Status": "Up 1 hour (healthy)",
                "Labels": {
                    "com.docker.compose.project": "demo",
                    "com.docker.compose.service": "api",
                },
            }
        ]

    def stats(self, container_id: str, stream: bool = False):
        self.stats_calls += 1
        return {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200},
                "system_cpu_usage": 1000,
                "online_cpus": 1,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 500,
            },
            "memory_stats": {"usage": 1024, "limit": 4096, "stats": {}},
            "networks": {},
        }

    def restart(self, container_id: str, timeout: int) -> None:
        self.restart_calls += 1

    def inspect_container(self, container_id: str):
        return {
            "Id": container_id,
            "Name": "/api-1",
            "Config": {
                "Image": "example/api:latest",
                "Labels": {
                    "com.docker.compose.project": "demo",
                    "com.docker.compose.service": "api",
                },
            },
            "State": {
                "Status": "running",
                "Health": {"Status": "healthy"},
                "StartedAt": "2026-07-29T10:00:00Z",
            },
        }

    def logs(self, container_id: str, **kwargs) -> bytes:
        return b"ok"


class FakeDockerClient:
    def __init__(self) -> None:
        self.api = FakeDockerApi()
        self.closed = False

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True


def load_docker_monitor_module():
    docker_module = types.ModuleType("docker")
    docker_module.DockerClient = object
    module_name = "app._docker_monitor_under_test"
    module_path = Path(__file__).parents[1] / "app" / "docker_monitor.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Не удалось загрузить app/docker_monitor.py")

    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"docker": docker_module}):
        spec.loader.exec_module(module)
    return module


class DockerMonitorCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_docker_monitor_module()

    def build_monitor(self):
        client = FakeDockerClient()
        monitor = self.module.DockerMonitor(
            base_url="unused",
            project_name=None,
            excluded_services=(),
            timezone_name="UTC",
            inventory_cache_seconds=60,
            stats_cache_seconds=60,
            client=client,
        )
        return monitor, client

    def test_inventory_is_shared_between_services_and_projects(self) -> None:
        monitor, client = self.build_monitor()

        self.assertEqual(1, len(monitor.list_services()))
        self.assertEqual(["demo"], monitor.list_project_names())
        self.assertEqual(1, client.api.container_calls)

    def test_stats_are_cached_per_container(self) -> None:
        monitor, client = self.build_monitor()

        first = monitor.get_service_stats()
        second = monitor.get_service_stats()

        self.assertEqual(first, second)
        self.assertEqual(1, client.api.stats_calls)

    def test_restart_invalidates_inventory_and_stats(self) -> None:
        monitor, client = self.build_monitor()
        monitor.get_service_stats()

        monitor.restart_container("container-1", 10)
        monitor.list_services()
        monitor.get_container_stats("container-1")

        self.assertEqual(1, client.api.restart_calls)
        self.assertEqual(2, client.api.container_calls)
        self.assertEqual(2, client.api.stats_calls)
