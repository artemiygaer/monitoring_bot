from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models import ServiceInfo


@dataclass(slots=True, frozen=True)
class ContainerAlertState:
    project_name: str | None
    service_name: str
    container_name: str
    status: str
    health: str | None
    started_at: datetime | None

    @property
    def key(self) -> tuple[str | None, str, str]:
        return (self.project_name, self.service_name, self.container_name)

    @property
    def is_problem(self) -> bool:
        if self.status != "running":
            return True
        return self.health is not None and self.health != "healthy"


@dataclass(slots=True, frozen=True)
class AlertEvent:
    kind: str
    current: ContainerAlertState | None
    previous: ContainerAlertState | None


def build_container_snapshot(services: list[ServiceInfo]) -> dict[tuple[str | None, str, str], ContainerAlertState]:
    snapshot: dict[tuple[str | None, str, str], ContainerAlertState] = {}

    for service in services:
        for container in service.containers:
            state = ContainerAlertState(
                project_name=service.project_name,
                service_name=service.name,
                container_name=container.name,
                status=container.status,
                health=container.health,
                started_at=container.started_at,
            )
            snapshot[state.key] = state

    return snapshot


def detect_alert_events(
    previous_snapshot: dict[tuple[str | None, str, str], ContainerAlertState],
    current_snapshot: dict[tuple[str | None, str, str], ContainerAlertState],
) -> list[AlertEvent]:
    events: list[AlertEvent] = []
    all_keys = sorted(
        set(previous_snapshot) | set(current_snapshot),
        key=lambda item: ((item[0] or ""), item[1], item[2]),
    )

    for key in all_keys:
        previous = previous_snapshot.get(key)
        current = current_snapshot.get(key)

        if previous is None and current is not None:
            if current.is_problem:
                events.append(AlertEvent(kind="problem", current=current, previous=None))
            continue

        if previous is not None and current is None:
            events.append(AlertEvent(kind="missing", current=None, previous=previous))
            continue

        if previous is None or current is None:
            continue

        state_changed = previous.status != current.status or previous.health != current.health
        if not state_changed:
            continue

        if not previous.is_problem and current.is_problem:
            events.append(AlertEvent(kind="problem", current=current, previous=previous))
            continue

        if previous.is_problem and not current.is_problem:
            events.append(AlertEvent(kind="recovered", current=current, previous=previous))
            continue

        if current.is_problem:
            events.append(AlertEvent(kind="problem_update", current=current, previous=previous))

    return events
