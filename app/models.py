from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class ContainerInfo:
    id: str
    name: str
    service_name: str
    project_name: str | None
    image: str
    status: str
    health: str | None
    started_at: datetime | None


@dataclass(slots=True)
class ServiceInfo:
    name: str
    project_name: str | None
    containers: list[ContainerInfo] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        return len(self.containers)

    @property
    def running_count(self) -> int:
        return sum(1 for container in self.containers if container.status == "running")

    @property
    def unhealthy_count(self) -> int:
        return sum(1 for container in self.containers if container.health and container.health != "healthy")

    @property
    def stopped_count(self) -> int:
        return sum(1 for container in self.containers if container.status != "running")


@dataclass(slots=True)
class ContainerStats:
    service_name: str
    container_name: str
    cpu_percent: float
    memory_usage: int
    memory_limit: int
    memory_percent: float
    network_rx: int
    network_tx: int


@dataclass(slots=True)
class DiskUsage:
    path_label: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    used_percent: float


@dataclass(slots=True)
class SystemSnapshot:
    hostname: str
    cpu_percent: float
    cpu_percent_avg_5m: float
    cpu_count: int
    load_average_1m: float
    load_average_5m: float
    load_average_15m: float
    memory_total_bytes: int
    memory_available_bytes: int
    memory_used_bytes: int
    memory_used_percent: float
    memory_used_percent_avg_5m: float
    swap_total_bytes: int
    swap_free_bytes: int
    swap_used_bytes: int
    swap_used_percent: float
    uptime_seconds: int
    disk_usage: DiskUsage | None
    collected_at: datetime
    average_window_seconds: int
    average_sample_count: int
