from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.system_monitor import SystemMonitor


class SystemMonitorTests(unittest.TestCase):
    def test_snapshot_is_built_from_proc_values(self) -> None:
        values = {
            "stat": (
                "cpu  100 0 100 100 0 0 0 0 0 0\n"
                "cpu0 50 0 50 50 0 0 0 0 0 0\n"
                "cpu1 50 0 50 50 0 0 0 0 0 0\n"
            ),
            "meminfo": "\n".join(
                [
                    "MemTotal:       1048576 kB",
                    "MemAvailable:    524288 kB",
                    "SwapTotal:       262144 kB",
                    "SwapFree:        131072 kB",
                ]
            ),
            "loadavg": "0.42 0.35 0.30 1/100 12345",
            "uptime": "7200.00 1234.56",
            "sys/kernel/hostname": "test-host",
        }

        def read_text(_self: SystemMonitor, relative_path: str) -> str:
            return values[relative_path]

        with patch("pathlib.Path.exists", return_value=True):
            with patch.object(SystemMonitor, "_read_text", autospec=True, side_effect=read_text):
                with patch(
                    "app.system_monitor.os.statvfs",
                    return_value=SimpleNamespace(
                        f_blocks=1000,
                        f_frsize=4096,
                        f_bavail=400,
                    ),
                    create=True,
                ):
                    monitor = SystemMonitor(
                        proc_path="/host/proc",
                        disk_path="/hostfs",
                        disk_label="/",
                        cache_seconds=1,
                        average_window_seconds=300,
                        timezone_name="UTC",
                    )

                    values["stat"] = (
                        "cpu  130 0 160 210 0 0 0 0 0 0\n"
                        "cpu0 65 0 80 105 0 0 0 0 0 0\n"
                        "cpu1 65 0 80 105 0 0 0 0 0 0\n"
                    )

                    snapshot = monitor.get_snapshot()

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual("test-host", snapshot.hostname)
        self.assertEqual(2, snapshot.cpu_count)
        self.assertAlmostEqual(45.0, snapshot.cpu_percent, places=2)
        self.assertAlmostEqual(50.0, snapshot.memory_used_percent, places=2)
        self.assertAlmostEqual(50.0, snapshot.swap_used_percent, places=2)
        self.assertEqual(7200, snapshot.uptime_seconds)
        self.assertIsNotNone(snapshot.disk_usage)
        assert snapshot.disk_usage is not None
        self.assertEqual("/", snapshot.disk_usage.path_label)
        self.assertAlmostEqual(60.0, snapshot.disk_usage.used_percent, places=2)
        self.assertAlmostEqual(45.0, snapshot.cpu_percent_avg_5m, places=2)
        self.assertAlmostEqual(50.0, snapshot.memory_used_percent_avg_5m, places=2)
        self.assertEqual(300, snapshot.average_window_seconds)
        self.assertEqual(1, snapshot.average_sample_count)

    def test_snapshot_uses_cache_to_avoid_extra_proc_reads(self) -> None:
        values = {
            "stat": (
                "cpu  100 0 100 100 0 0 0 0 0 0\n"
                "cpu0 50 0 50 50 0 0 0 0 0 0\n"
                "cpu1 50 0 50 50 0 0 0 0 0 0\n"
            ),
            "meminfo": "\n".join(
                [
                    "MemTotal:       1048576 kB",
                    "MemAvailable:    524288 kB",
                    "SwapTotal:       262144 kB",
                    "SwapFree:        131072 kB",
                ]
            ),
            "loadavg": "0.42 0.35 0.30 1/100 12345",
            "uptime": "7200.00 1234.56",
            "sys/kernel/hostname": "test-host",
        }
        calls: list[str] = []

        def read_text(_self: SystemMonitor, relative_path: str) -> str:
            calls.append(relative_path)
            return values[relative_path]

        with patch("pathlib.Path.exists", return_value=True):
            with patch.object(SystemMonitor, "_read_text", autospec=True, side_effect=read_text):
                with patch(
                    "app.system_monitor.os.statvfs",
                    return_value=SimpleNamespace(
                        f_blocks=1000,
                        f_frsize=4096,
                        f_bavail=400,
                    ),
                    create=True,
                ):
                    with patch("app.system_monitor.monotonic", side_effect=[100.0, 103.0]):
                        monitor = SystemMonitor(
                            proc_path="/host/proc",
                            disk_path="/hostfs",
                            disk_label="/",
                            cache_seconds=10,
                            average_window_seconds=300,
                            timezone_name="UTC",
                        )

                        values["stat"] = (
                            "cpu  130 0 160 210 0 0 0 0 0 0\n"
                            "cpu0 65 0 80 105 0 0 0 0 0 0\n"
                            "cpu1 65 0 80 105 0 0 0 0 0 0\n"
                        )

                        first_snapshot = monitor.get_snapshot()
                        second_snapshot = monitor.get_snapshot()

        self.assertIs(first_snapshot, second_snapshot)
        self.assertEqual(2, calls.count("stat"))
        self.assertEqual(1, calls.count("meminfo"))
        self.assertEqual(1, calls.count("loadavg"))
        self.assertEqual(1, calls.count("uptime"))
        self.assertEqual(1, calls.count("sys/kernel/hostname"))


if __name__ == "__main__":
    unittest.main()
