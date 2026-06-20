from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.formatters import (
    format_container_details,
    format_overview,
    format_resources,
    format_service_details,
    format_stats,
    format_system_details,
)
from app.models import ContainerInfo, ContainerStats, DiskUsage, ServiceInfo, SystemSnapshot


class FormatterTests(unittest.TestCase):
    def test_format_overview_contains_summary(self) -> None:
        service = ServiceInfo(
            name="xray",
            project_name="monitoring",
            containers=[
                ContainerInfo(
                    id="abc123",
                    name="xray",
                    service_name="xray",
                    project_name="monitoring",
                    image="teddysun/xray:latest",
                    status="running",
                    health="healthy",
                    started_at=datetime(2026, 4, 4, 12, 0, tzinfo=timezone.utc),
                )
            ],
        )
        system_snapshot = SystemSnapshot(
            hostname="debian-host",
            cpu_percent=12.5,
            cpu_percent_avg_5m=18.0,
            cpu_count=4,
            load_average_1m=0.42,
            load_average_5m=0.35,
            load_average_15m=0.30,
            memory_total_bytes=8 * 1024 * 1024 * 1024,
            memory_available_bytes=4 * 1024 * 1024 * 1024,
            memory_used_bytes=4 * 1024 * 1024 * 1024,
            memory_used_percent=50.0,
            memory_used_percent_avg_5m=48.0,
            swap_total_bytes=0,
            swap_free_bytes=0,
            swap_used_bytes=0,
            swap_used_percent=0.0,
            uptime_seconds=3600,
            disk_usage=DiskUsage(
                path_label="/",
                total_bytes=100 * 1024 * 1024 * 1024,
                used_bytes=40 * 1024 * 1024 * 1024,
                free_bytes=60 * 1024 * 1024 * 1024,
                used_percent=40.0,
            ),
            collected_at=datetime(2026, 4, 13, 12, 0, tzinfo=timezone.utc),
            average_window_seconds=300,
            average_sample_count=10,
        )

        rendered = format_overview([service], "monitoring", system_snapshot=system_snapshot)

        self.assertIn("Сводка по Docker Compose", rendered)
        self.assertIn("xray", rendered)
        self.assertIn("Статусы:", rendered)
        self.assertIn("🟢", rendered)
        self.assertIn("Все сервисы", rendered)
        self.assertIn("Система", rendered)
        self.assertIn("debian-host", rendered)
        self.assertIn("Среднее за 5 мин", rendered)

    def test_format_service_details_contains_container_data(self) -> None:
        service = ServiceInfo(
            name="mtg",
            project_name="monitoring",
            containers=[
                ContainerInfo(
                    id="def456",
                    name="mtg-proxy",
                    service_name="mtg",
                    project_name="monitoring",
                    image="nineseconds/mtg:latest",
                    status="running",
                    health=None,
                    started_at=datetime(2026, 4, 4, 12, 0, tzinfo=timezone.utc),
                )
            ],
        )

        rendered = format_service_details(service)

        self.assertIn("mtg-proxy", rendered)
        self.assertIn("nineseconds/mtg:latest", rendered)
        self.assertIn("работает", rendered)
        self.assertIn("🟢", rendered)

    def test_format_stats_contains_numbers(self) -> None:
        stats = [
            ContainerStats(
                service_name="hysteria",
                container_name="hysteria",
                cpu_percent=3.14,
                memory_usage=10 * 1024 * 1024,
                memory_limit=100 * 1024 * 1024,
                memory_percent=10.0,
                network_rx=5 * 1024,
                network_tx=8 * 1024,
            )
        ]

        rendered = format_stats(stats, service_name="hysteria")

        self.assertIn("3.14%", rendered)
        self.assertIn("10.00 MiB", rendered)
        self.assertIn("5.00 KiB", rendered)

    def test_format_resources_contains_host_and_top_containers(self) -> None:
        snapshot = SystemSnapshot(
            hostname="srv-01",
            cpu_percent=35.5,
            cpu_percent_avg_5m=30.0,
            cpu_count=4,
            load_average_1m=1.20,
            load_average_5m=1.10,
            load_average_15m=0.90,
            memory_total_bytes=8 * 1024 * 1024 * 1024,
            memory_available_bytes=5 * 1024 * 1024 * 1024,
            memory_used_bytes=3 * 1024 * 1024 * 1024,
            memory_used_percent=37.5,
            memory_used_percent_avg_5m=40.0,
            swap_total_bytes=0,
            swap_free_bytes=0,
            swap_used_bytes=0,
            swap_used_percent=0.0,
            uptime_seconds=3600,
            disk_usage=DiskUsage(
                path_label="/",
                total_bytes=100 * 1024 * 1024 * 1024,
                used_bytes=45 * 1024 * 1024 * 1024,
                free_bytes=55 * 1024 * 1024 * 1024,
                used_percent=45.0,
            ),
            collected_at=datetime(2026, 4, 13, 12, 0, tzinfo=timezone.utc),
            average_window_seconds=300,
            average_sample_count=10,
        )
        stats = [
            ContainerStats(
                service_name="api",
                container_name="api-1",
                cpu_percent=12.5,
                memory_usage=256 * 1024 * 1024,
                memory_limit=1024 * 1024 * 1024,
                memory_percent=25.0,
                network_rx=0,
                network_tx=0,
            )
        ]

        rendered = format_resources(snapshot, stats)

        self.assertIn("Ресурсы", rendered)
        self.assertIn("srv-01", rendered)
        self.assertIn("Топ CPU", rendered)
        self.assertIn("api/api-1", rendered)
        self.assertIn("Топ RAM", rendered)
        self.assertIn("RAM контейнеров суммарно", rendered)

    def test_format_container_details_contains_status_and_service(self) -> None:
        container = ContainerInfo(
            id="xyz789",
            name="xray-1",
            service_name="xray",
            project_name="monitoring",
            image="teddysun/xray:latest",
            status="running",
            health="healthy",
            started_at=datetime(2026, 4, 16, 10, 0, tzinfo=timezone.utc),
        )

        rendered = format_container_details(container)

        self.assertIn("monitoring/xray/xray-1", rendered)
        self.assertIn("teddysun/xray:latest", rendered)
        self.assertIn("работает", rendered)

    def test_format_system_details_contains_host_metrics(self) -> None:
        snapshot = SystemSnapshot(
            hostname="srv-01",
            cpu_percent=74.5,
            cpu_percent_avg_5m=91.2,
            cpu_count=8,
            load_average_1m=2.40,
            load_average_5m=1.80,
            load_average_15m=1.10,
            memory_total_bytes=16 * 1024 * 1024 * 1024,
            memory_available_bytes=6 * 1024 * 1024 * 1024,
            memory_used_bytes=10 * 1024 * 1024 * 1024,
            memory_used_percent=62.5,
            memory_used_percent_avg_5m=88.1,
            swap_total_bytes=2 * 1024 * 1024 * 1024,
            swap_free_bytes=1 * 1024 * 1024 * 1024,
            swap_used_bytes=1 * 1024 * 1024 * 1024,
            swap_used_percent=50.0,
            uptime_seconds=93784,
            disk_usage=DiskUsage(
                path_label="/",
                total_bytes=200 * 1024 * 1024 * 1024,
                used_bytes=150 * 1024 * 1024 * 1024,
                free_bytes=50 * 1024 * 1024 * 1024,
                used_percent=75.0,
            ),
            collected_at=datetime(2026, 4, 13, 12, 0, tzinfo=timezone.utc),
            average_window_seconds=300,
            average_sample_count=10,
        )

        rendered = format_system_details(snapshot)

        self.assertIn("srv-01", rendered)
        self.assertIn("74.5%", rendered)
        self.assertIn("91.2%", rendered)
        self.assertIn("10.00 GiB", rendered)
        self.assertIn("150.00 GiB", rendered)


if __name__ == "__main__":
    unittest.main()
