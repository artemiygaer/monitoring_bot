from __future__ import annotations

import secrets
from dataclasses import dataclass
from time import monotonic

import docker
from requests.exceptions import ReadTimeout


@dataclass(slots=True)
class HostCommandResult:
    command: str
    exit_code: int
    output: str
    timed_out: bool
    duration_seconds: float


class HostCommandExecutor:
    def __init__(
        self,
        *,
        base_url: str,
        helper_image: str,
        timeout_seconds: int,
        max_output_chars: int,
    ) -> None:
        self.helper_image = helper_image
        self.timeout_seconds = timeout_seconds
        self.max_output_chars = max_output_chars
        self._client = docker.DockerClient(base_url=base_url)

    def close(self) -> None:
        self._client.close()

    def run(self, command: str, *, timeout_seconds: int | None = None) -> HostCommandResult:
        started_at = monotonic()
        actual_timeout_seconds = timeout_seconds or self.timeout_seconds
        client = self._client
        container_name = f"monitoring-bot-cmd-{secrets.token_hex(4)}"
        container = client.containers.create(
            image=self.helper_image,
            name=container_name,
            command=["python", "-m", "app.command_worker"],
            environment={
                "MONITOR_HOST_COMMAND": command,
                "MONITOR_HOST_COMMAND_TIMEOUT_SECONDS": str(actual_timeout_seconds),
            },
            detach=True,
            privileged=True,
            pid_mode="host",
            network_mode="host",
            volumes={
                "/": {"bind": "/hostfs", "mode": "rw"},
            },
        )

        timed_out = False
        exit_code = 0
        output = ""

        try:
            container.start()
            try:
                result = container.wait(timeout=actual_timeout_seconds + 10)
                exit_code = int(result.get("StatusCode", 0))
            except ReadTimeout:
                timed_out = True
                exit_code = 124
                container.kill()

            raw_output = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace").strip()
            output = self._truncate_output(raw_output)
        finally:
            try:
                container.remove(force=True)
            except docker.errors.DockerException:
                pass

        return HostCommandResult(
            command=command,
            exit_code=exit_code,
            output=output or "Вывод отсутствует.",
            timed_out=timed_out,
            duration_seconds=max(monotonic() - started_at, 0.0),
        )

    def _truncate_output(self, output: str) -> str:
        if len(output) <= self.max_output_chars:
            return output

        allowed_length = max(self.max_output_chars - 80, 0)
        return (
            f"{output[:allowed_length].rstrip()}\n\n"
            "[Вывод обрезан ботом из-за ограничения размера.]"
        )
