from __future__ import annotations

import unittest

from app.alert_rules import AlertEvent, ContainerAlertState, detect_alert_events
from app.alerting import detect_system_load_event


def build_state(
    *,
    project_name: str = "monitoring",
    service_name: str = "xray",
    container_name: str = "xray",
    status: str = "running",
    health: str | None = "healthy",
) -> ContainerAlertState:
    return ContainerAlertState(
        project_name=project_name,
        service_name=service_name,
        container_name=container_name,
        status=status,
        health=health,
        started_at=None,
    )


class AlertingTests(unittest.TestCase):
    def test_problem_is_detected_when_container_stops(self) -> None:
        previous = {("monitoring", "xray", "xray"): build_state()}
        current = {("monitoring", "xray", "xray"): build_state(status="exited", health=None)}

        events = detect_alert_events(previous, current)

        self.assertEqual([AlertEvent(kind="problem", current=current[("monitoring", "xray", "xray")], previous=previous[("monitoring", "xray", "xray")])], events)

    def test_recovery_is_detected_when_container_returns(self) -> None:
        previous = {("monitoring", "xray", "xray"): build_state(status="exited", health=None)}
        current = {("monitoring", "xray", "xray"): build_state()}

        events = detect_alert_events(previous, current)

        self.assertEqual("recovered", events[0].kind)

    def test_problem_update_is_detected_when_health_changes_inside_problem_state(self) -> None:
        previous = {("monitoring", "xray", "xray"): build_state(status="running", health="unhealthy")}
        current = {("monitoring", "xray", "xray"): build_state(status="restarting", health="unhealthy")}

        events = detect_alert_events(previous, current)

        self.assertEqual("problem_update", events[0].kind)

    def test_missing_container_is_detected(self) -> None:
        previous = {("monitoring", "xray", "xray"): build_state()}
        current: dict[tuple[str | None, str, str], ContainerAlertState] = {}

        events = detect_alert_events(previous, current)

        self.assertEqual("missing", events[0].kind)

    def test_system_cpu_average_problem_is_detected(self) -> None:
        event, is_active = detect_system_load_event(
            resource_name="CPU",
            average_percent=91.5,
            current_percent=95.0,
            threshold_percent=90.0,
            is_active=False,
            sample_count=10,
            required_sample_count=10,
        )

        assert event is not None
        self.assertEqual("problem", event.kind)
        self.assertEqual("CPU", event.resource_name)
        self.assertTrue(is_active)

    def test_system_memory_average_recovery_is_detected(self) -> None:
        event, is_active = detect_system_load_event(
            resource_name="RAM",
            average_percent=72.0,
            current_percent=70.0,
            threshold_percent=90.0,
            is_active=True,
            sample_count=10,
            required_sample_count=10,
        )

        assert event is not None
        self.assertEqual("recovered", event.kind)
        self.assertEqual("RAM", event.resource_name)
        self.assertFalse(is_active)


if __name__ == "__main__":
    unittest.main()
