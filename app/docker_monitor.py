from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import docker

from app.models import ContainerInfo, ContainerStats, ServiceInfo


class DockerMonitor:
    def __init__(
        self,
        base_url: str,
        project_name: str | None,
        excluded_services: Iterable[str],
        timezone_name: str,
    ) -> None:
        self.client = docker.DockerClient(base_url=base_url)
        self.project_name = project_name
        self.excluded_services = set(excluded_services)
        self.timezone = self._load_timezone(timezone_name)

    def close(self) -> None:
        self.client.close()

    def ping(self) -> None:
        self.client.ping()

    def list_services(self) -> list[ServiceInfo]:
        services: dict[tuple[str | None, str], ServiceInfo] = {}

        for container in self.client.api.containers(all=True, filters=self._container_filters()):
            labels = container.get("Labels") or {}
            names = container.get("Names") or []
            fallback_name = names[0].lstrip("/") if names else container.get("Id", "unknown")[:12]
            service_name = labels.get("com.docker.compose.service", fallback_name)
            if service_name in self.excluded_services:
                continue

            project_name = labels.get("com.docker.compose.project")
            service_key = (project_name, service_name)
            service = services.setdefault(
                service_key,
                ServiceInfo(name=service_name, project_name=project_name),
            )
            service.containers.append(self._summary_to_container_info(container))

        result = sorted(services.values(), key=lambda item: ((item.project_name or ""), item.name))
        for service in result:
            service.containers.sort(key=lambda item: item.name)
        return result

    def list_project_names(self) -> list[str]:
        project_names: set[str] = set()

        for container in self.client.api.containers(all=True, filters={"label": ["com.docker.compose.project"]}):
            labels = container.get("Labels") or {}
            project_name = labels.get("com.docker.compose.project")
            if project_name:
                project_names.add(project_name)

        return sorted(project_names)

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
                "Укажи MONITOR_DOCKER_PROJECT, чтобы сузить выбор."
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
                container = self.client.containers.get(container_info.id)
                raw_logs = container.logs(tail=effective_tail, timestamps=True)
                logs_text = raw_logs.decode("utf-8", errors="replace").strip() or "Логи пусты."
                title_parts = [service.project_name, service.name, container_info.name]
                title = "/".join(part for part in title_parts if part)
                sections.append(f"===== {title} =====\n{logs_text}")

        return "\n\n".join(sections).strip() or "Подходящие сервисы не найдены."

    def get_container_logs(self, container_id: str, tail: int) -> tuple[ContainerInfo, str]:
        container = self.client.containers.get(container_id)
        container_info = self._to_container_info(container)
        raw_logs = container.logs(tail=tail, timestamps=True)
        logs_text = raw_logs.decode("utf-8", errors="replace").strip() or "Логи пусты."
        return container_info, logs_text

    def _collect_service_logs(self, service: ServiceInfo, tail: int) -> str:
        sections: list[str] = []

        for container_info in service.containers:
            container = self.client.containers.get(container_info.id)
            raw_logs = container.logs(tail=tail, timestamps=True)
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
                container = self.client.containers.get(container_info.id)
                raw_stats = container.stats(stream=False)
                stats.append(self._build_container_stats(service.name, container_info.name, raw_stats))

        return sorted(stats, key=lambda item: (item.service_name, item.container_name))

    def get_service_stats_by_ref(self, project_name: str | None, service_name: str) -> list[ContainerStats]:
        service = self.get_service_by_ref(project_name, service_name)
        stats: list[ContainerStats] = []

        for container_info in service.containers:
            container = self.client.containers.get(container_info.id)
            raw_stats = container.stats(stream=False)
            stats.append(self._build_container_stats(service.name, container_info.name, raw_stats))

        return sorted(stats, key=lambda item: (item.service_name, item.container_name))

    def get_container_stats(self, container_id: str) -> ContainerStats:
        container = self.client.containers.get(container_id)
        container_info = self._to_container_info(container)
        raw_stats = container.stats(stream=False)
        return self._build_container_stats(container_info.service_name, container_info.name, raw_stats)

    def list_containers(self) -> list[ContainerInfo]:
        containers: list[ContainerInfo] = []
        for service in self.list_services():
            containers.extend(service.containers)
        return sorted(containers, key=lambda item: ((item.project_name or ""), item.service_name, item.name))

    def get_container(self, container_id: str) -> ContainerInfo:
        container = self.client.containers.get(container_id)
        return self._to_container_info(container)

    def restart_container(self, container_id: str, timeout_seconds: int) -> ContainerInfo:
        container = self.client.containers.get(container_id)
        container.restart(timeout=timeout_seconds)
        container.reload()
        return self._to_container_info(container)

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

    def _to_container_info(self, container: docker.models.containers.Container) -> ContainerInfo:
        labels = container.labels or {}
        state = container.attrs.get("State", {})
        health = (state.get("Health") or {}).get("Status")

        image_tags = container.image.tags if container.image else []
        if image_tags:
            image = image_tags[0]
        elif container.image:
            image = container.image.short_id
        else:
            image = "unknown"

        return ContainerInfo(
            id=container.id,
            name=container.name,
            service_name=labels.get("com.docker.compose.service", container.name),
            project_name=labels.get("com.docker.compose.project"),
            image=image,
            status=state.get("Status", container.status),
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
