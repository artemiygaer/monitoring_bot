from __future__ import annotations

import asyncio
import html
import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

try:
    from docker.errors import DockerException
except ModuleNotFoundError:  # pragma: no cover
    class DockerException(Exception):
        pass

from app.alert_rules import AlertEvent, ContainerAlertState, build_container_snapshot, detect_alert_events
from app.formatters import format_container_status, format_datetime, format_health_status
from app.login_monitor import LoginEvent, LoginLogMonitor
from app.models import ServiceInfo, SystemSnapshot
from app.system_monitor import SystemMonitor

if TYPE_CHECKING:
    from app.docker_monitor import DockerMonitor


logger = logging.getLogger(__name__)


@dataclass(slots=True, eq=True)
class SystemLoadEvent:
    resource_name: str
    kind: str
    average_percent: float
    current_percent: float


def detect_system_load_event(
    *,
    resource_name: str,
    average_percent: float,
    current_percent: float,
    threshold_percent: float,
    is_active: bool,
    sample_count: int,
    required_sample_count: int,
) -> tuple[SystemLoadEvent | None, bool]:
    is_hot = sample_count >= required_sample_count and average_percent >= threshold_percent

    if is_hot and not is_active:
        return (
            SystemLoadEvent(
                resource_name=resource_name,
                kind="problem",
                average_percent=average_percent,
                current_percent=current_percent,
            ),
            True,
        )

    if not is_hot and is_active:
        return (
            SystemLoadEvent(
                resource_name=resource_name,
                kind="recovered",
                average_percent=average_percent,
                current_percent=current_percent,
            ),
            False,
        )

    return None, is_active


class DockerAlertWatcher:
    def __init__(
        self,
        monitor: DockerMonitor,
        system_monitor: SystemMonitor,
        login_monitor: LoginLogMonitor | None,
        bot: Bot,
        chat_ids: frozenset[int],
        poll_interval_seconds: int,
        login_poll_interval_seconds: int,
        notify_on_startup: bool,
        system_alert_threshold_percent: float,
    ) -> None:
        self.monitor = monitor
        self.system_monitor = system_monitor
        self.login_monitor = login_monitor
        self.bot = bot
        self.chat_ids = chat_ids
        self.poll_interval_seconds = poll_interval_seconds
        self.login_poll_interval_seconds = login_poll_interval_seconds
        self.notify_on_startup = notify_on_startup
        self.system_alert_threshold_percent = system_alert_threshold_percent
        self.previous_snapshot: dict[tuple[str | None, str, str], ContainerAlertState] = {}
        self.initialized = False
        self.docker_error_active = False
        self.system_error_active = False
        self.login_error_active = False
        self.cpu_alert_active = False
        self.memory_alert_active = False

    async def run(self) -> None:
        tasks = [
            asyncio.create_task(self._run_docker_system_loop(), name="docker-system-alert-loop"),
        ]
        if self.login_monitor is not None:
            tasks.append(asyncio.create_task(self._run_login_loop(), name="login-alert-loop"))

        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task

    async def _run_docker_system_loop(self) -> None:
        while True:
            try:
                await self._poll_docker()
            except asyncio.CancelledError:
                raise
            except DockerException as error:
                logger.exception("Ошибка фонового мониторинга Docker")
                if not self.docker_error_active:
                    await self.broadcast_text(self._format_docker_error_message(error))
                    self.docker_error_active = True

            try:
                await self._poll_system()
            except asyncio.CancelledError:
                raise

            await asyncio.sleep(self.poll_interval_seconds)

    async def _run_login_loop(self) -> None:
        while True:
            try:
                await self._poll_logins()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.exception("Ошибка чтения журналов входа")
                if not self.login_error_active:
                    await self.broadcast_text(self._format_login_error_message(error))
                    self.login_error_active = True

            await asyncio.sleep(self.login_poll_interval_seconds)

    async def _poll_docker(self) -> None:
        current_services = self.monitor.list_services()
        current_snapshot = build_container_snapshot(current_services)

        if self.docker_error_active:
            await self.broadcast_text("<b>Связь с Docker восстановлена</b>")
            self.docker_error_active = False

        if not self.initialized:
            self.previous_snapshot = current_snapshot
            self.initialized = True
            if self.notify_on_startup:
                await self.broadcast_text(self._format_startup_message(current_services))
            return

        events = detect_alert_events(self.previous_snapshot, current_snapshot)
        for event in events:
            await self.broadcast_text(self.format_event(event))
        self.previous_snapshot = current_snapshot

    async def _poll_system(self) -> None:
        snapshot = self.system_monitor.get_snapshot()
        if snapshot is None:
            if not self.system_error_active:
                await self.broadcast_text(self._format_system_error_message())
                self.system_error_active = True
            return

        if self.system_error_active:
            await self.broadcast_text("<b>Связь с системным мониторингом восстановлена</b>")
            self.system_error_active = False

        required_sample_count = max(
            2,
            (self.system_monitor.average_window_seconds + self.poll_interval_seconds - 1)
            // self.poll_interval_seconds,
        )

        cpu_event, self.cpu_alert_active = detect_system_load_event(
            resource_name="CPU",
            average_percent=snapshot.cpu_percent_avg_5m,
            current_percent=snapshot.cpu_percent,
            threshold_percent=self.system_alert_threshold_percent,
            is_active=self.cpu_alert_active,
            sample_count=snapshot.average_sample_count,
            required_sample_count=required_sample_count,
        )
        if cpu_event is not None:
            await self.broadcast_text(self._format_system_load_message(snapshot, cpu_event))

        memory_event, self.memory_alert_active = detect_system_load_event(
            resource_name="RAM",
            average_percent=snapshot.memory_used_percent_avg_5m,
            current_percent=snapshot.memory_used_percent,
            threshold_percent=self.system_alert_threshold_percent,
            is_active=self.memory_alert_active,
            sample_count=snapshot.average_sample_count,
            required_sample_count=required_sample_count,
        )
        if memory_event is not None:
            await self.broadcast_text(self._format_system_load_message(snapshot, memory_event))

    async def _poll_logins(self) -> None:
        if self.login_monitor is None:
            return

        events = await asyncio.to_thread(self.login_monitor.poll_events)
        if self.login_error_active:
            await self.broadcast_text("<b>Мониторинг входов на сервер восстановлен</b>")
            self.login_error_active = False

        for event in events:
            await self.broadcast_text(self._format_login_message(event))

    async def broadcast_text(self, text: str) -> None:
        if not self.chat_ids:
            return

        for chat_id in self.chat_ids:
            try:
                await self.bot.send_message(chat_id=chat_id, text=text)
            except TelegramAPIError:
                logger.exception("Не удалось отправить уведомление в чат %s", chat_id)

    def format_event(self, event: AlertEvent) -> str:
        if event.kind == "problem":
            return self._format_problem_message(event.current, event.previous)
        if event.kind == "problem_update":
            return self._format_problem_update_message(event.current, event.previous)
        if event.kind == "recovered":
            return self._format_recovered_message(event.current, event.previous)
        if event.kind == "missing":
            return self._format_missing_message(event.previous)
        return "<b>Неизвестное событие мониторинга</b>"

    def _format_startup_message(self, services: list[ServiceInfo]) -> str:
        return "\n".join(
            [
                "<b>Бот мониторинга запущен</b>",
                f"<b>Проект:</b> {html.escape(self.monitor.project_name or 'все compose-проекты')}",
                f"<b>Сервисов под наблюдением:</b> {len(services)}",
                f"<b>Интервал проверки Docker/системы:</b> {self.poll_interval_seconds} сек.",
                f"<b>Интервал проверки входов:</b> {self.login_poll_interval_seconds} сек.",
            ]
        )

    def _format_docker_error_message(self, error: Exception) -> str:
        return "\n".join(
            [
                "<b>Ошибка доступа к Docker</b>",
                "Фоновый мониторинг временно не может получить состояние контейнеров.",
                f"<b>Причина:</b> {html.escape(str(error))}",
            ]
        )

    def _format_system_error_message(self) -> str:
        return "\n".join(
            [
                "<b>Ошибка системного мониторинга</b>",
                "Не удалось получить метрики хоста из смонтированных read-only путей.",
            ]
        )

    def _format_login_error_message(self, error: Exception) -> str:
        return "\n".join(
            [
                "<b>Ошибка мониторинга входов на сервер</b>",
                "Не удалось прочитать источники входов с хоста: журналы, wtmp или utmp-сессии.",
                f"<b>Причина:</b> {html.escape(str(error))}",
            ]
        )

    def _format_system_load_message(self, snapshot: SystemSnapshot, event: SystemLoadEvent) -> str:
        if event.kind == "problem":
            title = f"<b>Высокая средняя загрузка {html.escape(event.resource_name)} за 5 минут</b>"
        else:
            title = f"<b>Средняя загрузка {html.escape(event.resource_name)} вернулась в норму</b>"

        return "\n".join(
            [
                title,
                f"<b>Хост:</b> {html.escape(snapshot.hostname)}",
                f"<b>Среднее за 5 минут:</b> {event.average_percent:.1f}%",
                f"<b>Текущее значение:</b> {event.current_percent:.1f}%",
                f"<b>Порог:</b> {self.system_alert_threshold_percent:.1f}%",
                f"<b>Замеров в окне:</b> {snapshot.average_sample_count}",
            ]
        )

    def _format_login_message(self, event: LoginEvent) -> str:
        if event.event_type == "ssh":
            title = "<b>SSH-вход на сервер</b>"
            source_line = f"<b>Источник:</b> {html.escape(event.source or 'неизвестно')}"
        else:
            title = "<b>Локальный вход на сервер</b>"
            source_line = "<b>Источник:</b> локальная консоль"

        lines = [
            title,
            f"<b>Пользователь:</b> {html.escape(event.user_name)}",
            source_line,
            f"<b>Хост:</b> {html.escape(event.host_name or 'неизвестно')}",
            f"<b>Время:</b> {html.escape(format_datetime(event.happened_at))}",
        ]
        if event.terminal:
            lines.append(f"<b>Терминал:</b> {html.escape(event.terminal)}")
        return "\n".join(lines)

    def _format_problem_message(
        self,
        current: ContainerAlertState | None,
        previous: ContainerAlertState | None,
    ) -> str:
        if current is None:
            return "<b>Проблема с контейнером</b>"

        lines = [
            "<b>Обнаружена проблема с контейнером</b>",
            *self._format_container_lines(current),
        ]
        if previous is not None:
            lines.append(
                f"<b>Было:</b> {html.escape(self._format_state_pair(previous.status, previous.health))}"
            )
        return "\n".join(lines)

    def _format_problem_update_message(
        self,
        current: ContainerAlertState | None,
        previous: ContainerAlertState | None,
    ) -> str:
        if current is None:
            return "<b>Состояние контейнера изменилось</b>"

        lines = [
            "<b>Состояние проблемного контейнера изменилось</b>",
            *self._format_container_lines(current),
        ]
        if previous is not None:
            lines.append(
                f"<b>Было:</b> {html.escape(self._format_state_pair(previous.status, previous.health))}"
            )
        return "\n".join(lines)

    def _format_recovered_message(
        self,
        current: ContainerAlertState | None,
        previous: ContainerAlertState | None,
    ) -> str:
        if current is None:
            return "<b>Контейнер восстановился</b>"

        lines = [
            "<b>Контейнер восстановился</b>",
            *self._format_container_lines(current),
        ]
        if previous is not None:
            lines.append(
                f"<b>Было:</b> {html.escape(self._format_state_pair(previous.status, previous.health))}"
            )
        return "\n".join(lines)

    def _format_missing_message(self, previous: ContainerAlertState | None) -> str:
        if previous is None:
            return "<b>Контейнер пропал из Docker</b>"

        return "\n".join(
            [
                "<b>Контейнер пропал из Docker</b>",
                *self._format_container_lines(previous),
                "<b>Комментарий:</b> контейнер больше не найден. Это может означать удаление или пересоздание.",
            ]
        )

    def _format_container_lines(self, state: ContainerAlertState) -> list[str]:
        return [
            f"<b>Проект:</b> {html.escape(state.project_name or 'не указан')}",
            f"<b>Сервис:</b> {html.escape(state.service_name)}",
            f"<b>Контейнер:</b> {html.escape(state.container_name)}",
            f"<b>Состояние:</b> {html.escape(format_container_status(state.status))}",
            f"<b>Проверка:</b> {html.escape(format_health_status(state.health))}",
            f"<b>Запущен:</b> {html.escape(format_datetime(state.started_at))}",
        ]

    @staticmethod
    def _format_state_pair(status: str, health: str | None) -> str:
        return f"{format_container_status(status)} / {format_health_status(health)}"
