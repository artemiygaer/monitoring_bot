from __future__ import annotations

from collections import deque
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models import DiskUsage, SystemSnapshot


@dataclass(slots=True)
class CpuSample:
    total: int
    idle: int
    cpu_count: int


class SystemMonitor:
    def __init__(
        self,
        *,
        proc_path: str,
        disk_path: str | None,
        disk_label: str,
        cache_seconds: int,
        average_window_seconds: int,
        timezone_name: str,
        server_name: str | None = None,
    ) -> None:
        self.proc_path = Path(proc_path)
        self.disk_path = Path(disk_path) if disk_path else None
        self.disk_label = disk_label
        self.cache_seconds = max(1, cache_seconds)
        self.average_window_seconds = max(60, average_window_seconds)
        self.timezone = self._load_timezone(timezone_name)
        self.server_name = server_name
        self._cached_at: float | None = None
        self._cached_snapshot: SystemSnapshot | None = None
        self._last_cpu_sample = self._safe_read_cpu_sample()
        self._history: deque[tuple[datetime, float, float]] = deque()

    def get_snapshot(self) -> SystemSnapshot | None:
        if not self.is_available():
            return None

        now = monotonic()
        if (
            self._cached_snapshot is not None
            and self._cached_at is not None
            and now - self._cached_at < self.cache_seconds
        ):
            return self._cached_snapshot

        try:
            cpu_sample = self._read_cpu_sample()
            meminfo = self._read_meminfo()
            load1, load5, load15 = self._read_load_average()
            uptime_seconds = self._read_uptime_seconds()
            disk_usage = self._read_disk_usage()
            memory_total = meminfo.get("MemTotal", 0)
            memory_available = meminfo.get("MemAvailable", 0)
            memory_used = max(memory_total - memory_available, 0)
            memory_used_percent = (memory_used / memory_total * 100) if memory_total else 0.0
            swap_total = meminfo.get("SwapTotal", 0)
            swap_free = meminfo.get("SwapFree", 0)
            swap_used = max(swap_total - swap_free, 0)
            swap_used_percent = (swap_used / swap_total * 100) if swap_total else 0.0

            snapshot = SystemSnapshot(
                hostname=self._read_hostname(),
                cpu_percent=self._calculate_cpu_percent(cpu_sample),
                cpu_percent_avg_5m=0.0,
                cpu_count=cpu_sample.cpu_count,
                load_average_1m=load1,
                load_average_5m=load5,
                load_average_15m=load15,
                memory_total_bytes=memory_total,
                memory_available_bytes=memory_available,
                memory_used_bytes=memory_used,
                memory_used_percent=memory_used_percent,
                memory_used_percent_avg_5m=0.0,
                swap_total_bytes=swap_total,
                swap_free_bytes=swap_free,
                swap_used_bytes=swap_used,
                swap_used_percent=swap_used_percent,
                uptime_seconds=uptime_seconds,
                disk_usage=disk_usage,
                collected_at=datetime.now(self.timezone),
                average_window_seconds=self.average_window_seconds,
                average_sample_count=0,
            )
        except OSError:
            return None
        except RuntimeError:
            return None

        self._apply_averages(snapshot)
        self._cached_at = now
        self._cached_snapshot = snapshot
        return snapshot

    def is_available(self) -> bool:
        return (self.proc_path / "stat").exists()

    def _calculate_cpu_percent(self, current_sample: CpuSample) -> float:
        previous_sample = self._last_cpu_sample
        self._last_cpu_sample = current_sample
        if previous_sample is None:
            return 0.0

        total_delta = current_sample.total - previous_sample.total
        idle_delta = current_sample.idle - previous_sample.idle
        if total_delta <= 0:
            return 0.0

        busy_ratio = 1.0 - (idle_delta / total_delta)
        return max(0.0, min(busy_ratio * 100, 100.0))

    def _read_load_average(self) -> tuple[float, float, float]:
        raw_value = self._read_text("loadavg")
        parts = raw_value.split()
        if len(parts) < 3:
            return 0.0, 0.0, 0.0
        return float(parts[0]), float(parts[1]), float(parts[2])

    def _read_uptime_seconds(self) -> int:
        raw_value = self._read_text("uptime")
        return int(float(raw_value.split()[0]))

    def _read_hostname(self) -> str:
        if self.server_name:
            return self.server_name
        return self._read_text("sys/kernel/hostname").strip()

    def _read_meminfo(self) -> dict[str, int]:
        values: dict[str, int] = {}
        for line in self._read_text("meminfo").splitlines():
            if ":" not in line:
                continue
            field_name, raw_value = line.split(":", 1)
            parts = raw_value.strip().split()
            if not parts:
                continue
            multiplier = 1024 if len(parts) > 1 and parts[1].lower() == "kb" else 1
            values[field_name] = int(parts[0]) * multiplier

        if "MemAvailable" not in values:
            values["MemAvailable"] = (
                values.get("MemFree", 0) + values.get("Buffers", 0) + values.get("Cached", 0)
            )
        return values

    def _read_disk_usage(self) -> DiskUsage | None:
        if self.disk_path is None or not self.disk_path.exists():
            return None

        stats = os.statvfs(self.disk_path)
        total_bytes = stats.f_blocks * stats.f_frsize
        free_bytes = stats.f_bavail * stats.f_frsize
        used_bytes = max(total_bytes - free_bytes, 0)
        used_percent = (used_bytes / total_bytes * 100) if total_bytes else 0.0
        return DiskUsage(
            path_label=self.disk_label,
            total_bytes=total_bytes,
            used_bytes=used_bytes,
            free_bytes=free_bytes,
            used_percent=used_percent,
        )

    def _read_cpu_sample(self) -> CpuSample:
        stat_text = self._read_text("stat")
        cpu_lines = stat_text.splitlines()
        aggregate_line = next((line for line in cpu_lines if line.startswith("cpu ")), None)
        if aggregate_line is None:
            raise RuntimeError("Не удалось прочитать агрегированную статистику CPU")

        fields = [int(value) for value in aggregate_line.split()[1:]]
        total = sum(fields)
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        cpu_count = sum(1 for line in cpu_lines if line.startswith("cpu") and len(line) > 3 and line[3].isdigit())
        return CpuSample(total=total, idle=idle, cpu_count=max(cpu_count, 1))

    def _safe_read_cpu_sample(self) -> CpuSample | None:
        try:
            return self._read_cpu_sample()
        except OSError:
            return None
        except RuntimeError:
            return None

    def _apply_averages(self, snapshot: SystemSnapshot) -> None:
        self._history.append((snapshot.collected_at, snapshot.cpu_percent, snapshot.memory_used_percent))
        cutoff = snapshot.collected_at - timedelta(seconds=self.average_window_seconds)

        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()

        sample_count = len(self._history)
        if sample_count <= 0:
            snapshot.cpu_percent_avg_5m = snapshot.cpu_percent
            snapshot.memory_used_percent_avg_5m = snapshot.memory_used_percent
            snapshot.average_sample_count = 1
            return

        snapshot.cpu_percent_avg_5m = sum(item[1] for item in self._history) / sample_count
        snapshot.memory_used_percent_avg_5m = sum(item[2] for item in self._history) / sample_count
        snapshot.average_sample_count = sample_count

    def _read_text(self, relative_path: str) -> str:
        target_path = self.proc_path / relative_path
        return target_path.read_text(encoding="utf-8").strip()

    @staticmethod
    def _load_timezone(timezone_name: str) -> ZoneInfo | timezone:
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return timezone.utc
