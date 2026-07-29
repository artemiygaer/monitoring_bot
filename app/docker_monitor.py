from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import docker

from app.cache import TTLCache
from app.models import ContainerInfo, ContainerStats, ServiceInfo


class DockerMonitor:
    def __init__(
        self,
        base_url: str,
        project_name: str | None,
        excluded_services: Iterable[str],
        timezone_name: str,
        inventory_cache_seconds: int = 3,
        stats_cache_seconds: int = 10,
        client=None,
    ) -> None:
        self.client = client or docker.DockerClient(base_url=base_url)
        self.project_name = project_name
        self.excluded_services = set(excluded_services)
        self.timezone = self._load_timezone(timezone_name)
        self._inventory_cache: TTLCache[str, tuple[list[ServiceInfo], list[str]]] = TTLCache(
            inventory_cache_seconds
        )
        self._stats_cache: TTLCache[str, ContainerStats] = TTLCache(stats_cache_seconds)

    def close(self) -> None:
        self._inventory_cache.invalidate()
        self._stats_cache.invalidate()
        self.client.close()

    def ping(self) -> None:
        self.client.ping()

    def list_services(self) -> list[ServiceInfo]:
        services, _ = self._get_inventory()
        return list(services)

    def _get_inventory(self) -> tuple[list[ServiceInfo], list[str]]:
        return self._inventory_cache.get_or_create("inventory", self._load_inventory)

    def _load_inventory(self) -> tuple[list[ServiceInfo], list[str]]:
        services: dict[tuple[str | None, str], ServiceInfo] = {}
        project_names: set[str] = set()

        for container in self.client.api.containers(all=True, filters=self._container_filters()):
            labels = container.get("Labels") or {}
            names = container.get("Names") or []
            fallback_name = names[0].lstrip("/") if names else container.get("Id", "unknown")[:12]
            service_name = labels.get("com.docker.compose.service", fallback_name)
            if service_name in self.excluded_services:
                continue

            project_name = labels.get("com.docker.compose.project")
            if project_name:
                project_names.add(project_name)
            service_key = (project_name, service_name)
            service = services.setdefault(
                service_key,
                ServiceInfo(name=service_name, project_name=project_name),
            )
            service.containers.append(self._summary_to_container_info(container))

        result = sorted(services.values(), key=lambda item: ((item.project_name or ""), item.name))
        for service in result:
            service.containers.sort(key=lambda item: item.name)
        return result, sorted(project_names)

    def list_project_names(self) -> list[str]:
        _, project_names = self._get_inventory()
        return list(project_names)

    def get_service(self, service_name: str) -> ServiceInfo:
        normalized_query = service_name.strip().lower()
        matches = []

        for service in self.list_services():
            if service.name.lower() == normalized_query:
                matches.append(service)
                continue

            if any(container.name.lower() == normalized_query for container in service.containers):
                matches.append(service)

        if not matches:
            raise LookupError(f"Сервис '{service_name}' не найден")

        if len(matches) > 1:
            raise LookupError(
                f"Сервис '{service_name}' найден в нескольких проектах. "
                "Ограничь мониторинг одним Compose-проектом в настройках."
            )

        return matches[0]

    def get_service_by_ref(self, project_name: str | None, service_name: str) -> ServiceInfo:
        for service in self.list_services():
            if service.name != service_name:
                continue
            if service.project_name == project_name:
                return service

        if project_name:
            raise LookupError(f"Сервис '{service_name}' проекта '{project_name}' не найден")
        raise LookupError(f"Сервис '{service_name}' не найден")

    def get_service_logs(self, service_name: str, tail: int) -> tuple[ServiceInfo, str]:
        service = self.get_service(service_name)
        return service, self._collect_service_logs(service, min(tail, 500))

    def get_service_logs_by_ref(self, project_name: str | None, service_name: str, tail: int) -> tuple[ServiceInfo, str]:
        service = self.get_service_by_ref(project_name, service_name)
        return service, self._collect_service_logs(service, min(tail, 500))

    def get_all_logs(self, tail: int) -> str:
        services = self.list_services()
        sections: list[str] = []
        effective_tail = min(tail, 500)

        for service in services:
            for container_info in service.containers:
                raw_logs = self.client.api.logs(
                    container_info.id,
                    tail=effective_tail,
                    timestamps=True,
                )
                logs_text = raw_logs.decode("utf-8", errors="replace").strip() or "Логи пусты."
                title_parts = [service.project_name, service.name, container_info.name]
                title = "/".join(part for part in title_parts if part)
                sections.append(f"===== {title} =====\n{logs_text}")

        return "\n\n".join(sections).strip() or "Подходящие сервисы не найдены."

    def get_container_logs(self, container_id: str, tail: int) -> tuple[ContainerInfo, str]:
        container_info = self.get_container(container_id)
        raw_logs = self.client.api.logs(container_id, tail=tail, timestamps=True)
        logs_text = raw_logs.decode("utf-8", errors="replace").strip() or "Логи пусты."
        return container_info, logs_text

    def _collect_service_logs(self, service: ServiceInfo, tail: int) -> str:
        sections: list[str] = []

        for container_info in service.containers:
            raw_logs = self.client.api.logs(container_info.id, tail=tail, timestamps=True)
            logs_text = raw_logs.decode("utf-8", errors="replace").strip() or "Логи пусты."

            if len(service.containers) == 1:
                sections.append(logs_text)
                continue

            sections.append(f"===== {container_info.name} =====\n{logs_text}")

        return "\n\n".join(sections)

    def get_service_stats(self, service_name: str | None = None) -> list[ContainerStats]:
        services = [self.get_service(service_name)] if service_name else self.list_services()
        stats: list[ContainerStats] = []

        for service in services:
            for container_info in service.containers:
                stats.append(self._get_cached_stats(service.name, container_info))

        return sorted(stats, key=lambda item: (item.service_name, item.container_name))

    def get_service_stats_by_ref(self, project_name: str | None, service_name: str) -> list[ContainerStats]:
        service = self.get_service_by_ref(project_name, service_name)
        stats: list[ContainerStats] = []

        for container_info in service.containers:
            stats.append(self._get_cached_stats(service.name, container_info))

        return sorted(stats, key=lambda item: (item.service_name, item.container_name))

    def get_container_stats(self, container_id: str) -> ContainerStats:
        container_info = self.get_container(container_id)
        return self._get_cached_stats(container_info.service_name, container_info)

    def _get_cached_stats(self, service_name: str, container_info: ContainerInfo) -> ContainerStats:
        return self._stats_cache.get_or_create(
            container_info.id,
            lambda: self._build_container_stats(
                service_name,
                container_info.name,
                self.client.api.stats(container_info.id, stream=False),
            ),
        )

    def list_containers(self) -> list[ContainerInfo]:
        containers: list[ContainerInfo] = []
        for service in self.list_services():
            containers.extend(service.containers)
        return sorted(containers, key=lambda item: ((item.project_name or ""), item.service_name, item.name))

    def get_container(self, container_id: str) -> ContainerInfo:
        return self._inspect_to_container_info(self.client.api.inspect_container(container_id))

    def restart_container(self, container_id: str, timeout_seconds: int) -> ContainerInfo:
        self.client.api.restart(container_id, timeout=timeout_seconds)
        self._inventory_cache.invalidate()
        self._stats_cache.invalidate(container_id)
        return self.get_container(container_id)

    def _container_filters(self) -> dict[str, list[str]]:
        if self.project_name:
            return {"label": [f"com.docker.compose.project={self.project_name}"]}
        return {"label": ["com.docker.compose.project"]}

    def _summary_to_container_info(self, container: dict) -> ContainerInfo:
        labels = container.get("Labels") or {}
        names = container.get("Names") or []
        container_name = names[0].lstrip("/") if names else container.get("Id", "unknown")[:12]
        service_name = labels.get("com.docker.compose.service", container_name)

        return ContainerInfo(
            id=container.get("Id", ""),
            name=container_name,
            service_name=service_name,
            project_name=labels.get("com.docker.compose.project"),
            image=container.get("Image") or "unknown",
            status=container.get("State") or "unknown",
            health=self._parse_summary_health(container.get("Status") or ""),
            started_at=None,
        )

    def _inspect_to_container_info(self, container: dict) -> ContainerInfo:
        config = container.get("Config") or {}
        labels = config.get("Labels") or {}
        state = container.get("State") or {}
        health = (state.get("Health") or {}).get("Status")
        name = str(container.get("Name") or container.get("Id") or "unknown").lstrip("/")
        image = config.get("Image") or container.get("Image") or "unknown"

        return ContainerInfo(
            id=container.get("Id", ""),
            name=name,
            service_name=labels.get("com.docker.compose.service", name),
            project_name=labels.get("com.docker.compose.project"),
            image=image,
            status=state.get("Status", "unknown"),
            health=health,
            started_at=self._parse_started_at(state.get("StartedAt")),
        )

    def _parse_started_at(self, raw_value: str | None) -> datetime | None:
        if not raw_value or raw_value.startswith("0001-01-01"):
            return None

        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        return parsed.astimezone(self.timezone)

    def _build_container_stats(self, service_name: str, container_name: str, raw_stats: dict) -> ContainerStats:
        cpu_stats = raw_stats.get("cpu_stats", {})
        precpu_stats = raw_stats.get("precpu_stats", {})

        cpu_delta = (
            cpu_stats.get("cpu_usage", {}).get("total_usage", 0)
            - precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
        )
        system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get("system_cpu_usage", 0)
        online_cpus = cpu_stats.get("online_cpus") or len(cpu_stats.get("cpu_usage", {}).get("percpu_usage", []) or [1])

        cpu_percent = 0.0
        if cpu_delta > 0 and system_delta > 0 and online_cpus > 0:
            cpu_percent = (cpu_delta / system_delta) * online_cpus * 100

        memory_stats = raw_stats.get("memory_stats", {})
        memory_usage = memory_stats.get("usage", 0)
        cache = self._detect_memory_cache(memory_stats)
        memory_usage = max(memory_usage - cache, 0)
        memory_limit = memory_stats.get("limit", 0)
        memory_percent = (memory_usage / memory_limit * 100) if memory_limit else 0.0

        networks = raw_stats.get("networks", {}) or {}
        network_rx = sum(item.get("rx_bytes", 0) for item in networks.values())
        network_tx = sum(item.get("tx_bytes", 0) for item in networks.values())

        return ContainerStats(
            service_name=service_name,
            container_name=container_name,
            cpu_percent=cpu_percent,
            memory_usage=memory_usage,
            memory_limit=memory_limit,
            memory_percent=memory_percent,
            network_rx=network_rx,
            network_tx=network_tx,
        )

    @staticmethod
    def _detect_memory_cache(memory_stats: dict) -> int:
        stats = memory_stats.get("stats", {}) or {}
        for field_name in ("cache", "inactive_file", "total_inactive_file"):
            if field_name in stats:
                return int(stats[field_name] or 0)
        return 0

    @staticmethod
    def _parse_summary_health(status_text: str) -> str | None:
        lowered = status_text.lower()
        if "(healthy)" in lowered:
            return "healthy"
        if "(unhealthy)" in lowered:
            return "unhealthy"
        if "(health: starting)" in lowered:
            return "starting"
        return None

    @staticmethod
    def _load_timezone(timezone_name: str) -> ZoneInfo | timezone:
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return timezone.utc
