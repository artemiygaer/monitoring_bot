from __future__ import annotations

import asyncio
import gc
import logging
import os
import sys
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from time import monotonic

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, FSInputFile, Message, ReplyKeyboardMarkup
from docker.errors import DockerException

from app.access import AccessMiddleware
from app.backup import (
    BackupArchive,
    build_backup_command,
    build_delete_backup_command,
    find_backup_archive,
    list_backup_archives,
)
from app.config import Settings
from app.docker_monitor import DockerMonitor
from app.formatters import (
    format_bytes,
    format_container_details,
    format_datetime,
    format_duration,
    format_logs_caption,
    format_overview,
    format_resources,
    format_service_details,
    format_stats,
    format_system_details,
    service_level_emoji,
    status_emoji,
)
from app.host_command_executor import HostCommandExecutor
from app.keyboards import (
    ACTION_ALL_CONTAINERS,
    ACTION_BACK,
    ACTION_CANCEL,
    ACTION_CLEAR_CHAT,
    ACTION_CONTAINER_LOGS,
    ACTION_CONTAINER_STATS,
    ACTION_CONFIRM_DELETE_BACKUP,
    ACTION_CONFIRM_BACKUP,
    ACTION_CONFIRM_CLEANUP,
    ACTION_CONFIRM_COMMAND,
    ACTION_CONFIRM_RESTART,
    ACTION_CREATE_BACKUP,
    ACTION_DELETE_BACKUP,
    ACTION_DOWNLOAD_BACKUP,
    ACTION_RESTART_CONTAINER,
    ACTION_SERVICE_CONTAINERS,
    ACTION_SERVICE_LOGS,
    ACTION_SERVICE_STATS,
    LOG_TAIL_BUTTONS,
    MENU_ABOUT,
    MENU_BACKUP,
    MENU_CLEANUP,
    MENU_COMMANDS,
    MENU_CONTAINERS,
    MENU_FAILED_LOGINS,
    MENU_OVERVIEW,
    MENU_REFRESH,
    MENU_RESOURCES,
    MENU_SYSTEM,
    build_backup_archive_menu,
    build_backup_confirm_menu,
    build_backup_delete_confirm_menu,
    build_backup_menu,
    build_cleanup_confirm_menu,
    build_command_confirm_menu,
    build_commands_input_menu,
    build_container_detail_menu,
    build_container_menu,
    build_detail_menu,
    build_log_tail_menu,
    build_logs_source_menu,
    build_main_menu,
    build_restart_confirm_menu,
    build_service_detail_menu,
    build_service_menu,
    build_stats_menu,
    build_system_menu,
)
from app.login_monitor import FailedLoginEvent, LoginLogMonitor
from app.maintenance import build_cleanup_command, list_cleanup_candidates
from app.models import ContainerInfo, ServiceInfo
from app.system_monitor import SystemMonitor


logger = logging.getLogger(__name__)

MAX_TRACKED_MESSAGES = 50
SESSION_TTL_SECONDS = 3600


@dataclass(slots=True)
class ChatSession:
    screen: str = "home"
    option_map: dict[str, tuple[str, str]] = field(default_factory=dict)
    current_service_payload: str | None = None
    current_stats_payload: str | None = None
    current_stats_return_screen: str | None = None
    current_container_id: str | None = None
    current_container_filter_payload: str | None = None
    current_container_return_screen: str | None = None
    current_log_descriptor: str | None = None
    current_log_tail: int | None = None
    current_log_return_screen: str | None = None
    current_backup_name: str | None = None
    pending_command: str | None = None
    log_message_ids: list[int] = field(default_factory=list)
    command_message_ids: list[int] = field(default_factory=list)
    user_message_ids: list[int] = field(default_factory=list)
    bot_message_ids: list[int] = field(default_factory=list)
    last_activity: float = field(default_factory=monotonic)


def create_router(
    monitor: DockerMonitor,
    system_monitor: SystemMonitor,
    login_monitor: LoginLogMonitor | None,
    command_executor: HostCommandExecutor,
    settings: Settings,
) -> Router:
    router = Router(name="monitoring")
    router.message.middleware(AccessMiddleware(settings.allowed_user_ids))
    router.callback_query.middleware(AccessMiddleware(settings.allowed_user_ids))

    sessions: dict[int, ChatSession] = {}
    started_at = datetime.now(monitor.timezone)
    current_server: str | None = None

    def _cleanup_stale_sessions() -> None:
        now = monotonic()
        stale_keys = [
            chat_id for chat_id, session in sessions.items()
            if now - session.last_activity > SESSION_TTL_SECONDS
        ]
        if stale_keys:
            for chat_id in stale_keys:
                del sessions[chat_id]
            gc.collect()

    def get_session(chat_id: int) -> ChatSession:
        _cleanup_stale_sessions()
        session = sessions.setdefault(chat_id, ChatSession())
        session.last_activity = monotonic()
        return session

    def remember_message_id(storage: list[int], message_id: int) -> None:
        if message_id in storage:
            return
        storage.append(message_id)
        if len(storage) > MAX_TRACKED_MESSAGES:
            del storage[0]

    def remember_incoming(message: Message, session: ChatSession) -> None:
        remember_message_id(session.user_message_ids, message.message_id)

    async def send_text(
        message: Message,
        session: ChatSession,
        text: str,
        reply_markup: ReplyKeyboardMarkup | None = None,
        *,
        track: bool = True,
    ) -> Message:
        sent = await message.answer(text, reply_markup=reply_markup)
        if track:
            remember_message_id(session.bot_message_ids, sent.message_id)
        return sent

    async def send_chat_text(
        bot,
        chat_id: int,
        session: ChatSession,
        text: str,
        reply_markup: ReplyKeyboardMarkup | None = None,
        *,
        track: bool = True,
    ) -> Message:
        sent = await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        if track:
            remember_message_id(session.bot_message_ids, sent.message_id)
        return sent

    def encode_project_name(project_name: str | None) -> str:
        return project_name or "_"

    def decode_project_name(encoded_value: str) -> str | None:
        if encoded_value == "_":
            return None
        return encoded_value

    def parse_service_payload(payload: str) -> tuple[str | None, str]:
        parts = payload.split(":", 1)
        if len(parts) == 2:
            return decode_project_name(parts[0]), parts[1]
        return None, payload

    def parse_log_source_descriptor(descriptor: str) -> tuple[str, str | None, str | None]:
        if descriptor == "all":
            return "all", None, None

        if descriptor.startswith("svc:"):
            project_name, service_name = parse_service_payload(descriptor[4:])
            return "service", project_name, service_name

        if descriptor.startswith("ctr:"):
            return "container", None, descriptor[4:]

        project_name, service_name = parse_service_payload(descriptor)
        return "service", project_name, service_name

    def parse_stats_descriptor(descriptor: str) -> tuple[str, str]:
        if descriptor.startswith("svc:"):
            return "service", descriptor[4:]
        if descriptor.startswith("ctr:"):
            return "container", descriptor[4:]
        return "service", descriptor

    def get_active_monitor(session: ChatSession | None = None) -> DockerMonitor:
        return monitor

    def get_active_system_monitor(session: ChatSession | None = None) -> SystemMonitor | None:
        return system_monitor

    def list_services(session: ChatSession | None = None) -> list[ServiceInfo]:
        return get_active_monitor(session).list_services()

    def list_containers(session: ChatSession | None = None) -> list[ContainerInfo]:
        return get_active_monitor(session).list_containers()

    def service_name_duplicates(session: ChatSession | None = None) -> set[str]:
        counts: dict[str, int] = {}
        for service in list_services(session):
            counts[service.name] = counts.get(service.name, 0) + 1
        return {name for name, count in counts.items() if count > 1}

    def service_display_name(service: ServiceInfo, show_project: bool) -> str:
        if show_project and service.project_name:
            return f"{service.project_name}/{service.name}"
        return service.name

    def build_service_label(service: ServiceInfo, show_project: bool) -> str:
        return (
            f"{service_level_emoji(service)} "
            f"{service_display_name(service, show_project)} "
            f"{service.running_count}/{service.total_count}"
        )

    def build_container_label(container: ContainerInfo) -> str:
        title = f"{container.service_name}/{container.name}"
        if container.project_name:
            title = f"{container.project_name}/{title}"
        return f"{status_emoji(container.status)} {title}"

    def get_service_by_payload(payload: str, session: ChatSession | None = None) -> ServiceInfo:
        project_name, service_name = parse_service_payload(payload)
        if ":" in payload:
            return get_active_monitor(session).get_service_by_ref(project_name, service_name)
        return get_active_monitor(session).get_service(service_name)

    def get_container_by_id(container_id: str, session: ChatSession | None = None) -> ContainerInfo:
        return get_active_monitor(session).get_container(container_id)

    # get_server_display_name удален

    def build_overview_text(session: ChatSession | None = None) -> str:
        services = list_services(session)
        project_names = get_active_monitor(session).list_project_names()
        system_snapshot = get_active_system_monitor(session).get_snapshot() if get_active_system_monitor(session) else None
        return format_overview(
            services,
            settings.docker_project_name,
            available_project_names=project_names,
            system_snapshot=system_snapshot,
            updated_at=datetime.now(get_active_monitor(session).timezone),
        )

    def build_system_text(session: ChatSession | None = None) -> str:
        snapshot = get_active_system_monitor(session).get_snapshot()
        header = ""
        if snapshot is None:
            return header + (
                "🖥️ <b>Системный мониторинг недоступен</b>\n"
                "Проверь, что в контейнер смонтированы пути с хоста для <code>/proc</code> и корневой файловой системы."
            )
        return header + format_system_details(snapshot)

    def read_process_memory_kib() -> dict[str, int]:
        values: dict[str, int] = {}
        try:
            with open("/proc/self/status", "r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if not line.startswith(("VmRSS:", "VmSize:")):
                        continue
                    parts = line.split()
                    if len(parts) >= 2:
                        values[parts[0].rstrip(":")] = int(parts[1])
        except OSError:
            return {}
        return values

    def build_process_info_lines() -> list[str]:
        memory = read_process_memory_kib()
        rss_bytes = memory.get("VmRSS", 0) * 1024
        vms_bytes = memory.get("VmSize", 0) * 1024
        tracked_messages = sum(
            len(session.bot_message_ids)
            + len(session.user_message_ids)
            + len(session.log_message_ids)
            + len(session.command_message_ids)
            for session in sessions.values()
        )

        lines = [
            f"<b>PID:</b> {os.getpid()}",
            f"<b>Python:</b> {escape(sys.version.split()[0])}",
            f"<b>Активных сессий:</b> {len(sessions)}",
            f"<b>Сообщений в памяти:</b> {tracked_messages}",
        ]
        if rss_bytes:
            lines.append(f"<b>RSS процесса:</b> {format_bytes(rss_bytes)}")
        if vms_bytes:
            lines.append(f"<b>VmSize процесса:</b> {format_bytes(vms_bytes)}")
        return lines

    def build_service_option_map(action_name: str, session: ChatSession | None = None) -> dict[str, tuple[str, str]]:
        services = list_services(session)
        counts: dict[str, int] = {}
        for service in services:
            counts[service.name] = counts.get(service.name, 0) + 1
        duplicates = {name for name, count in counts.items() if count > 1}

        option_map: dict[str, tuple[str, str]] = {}
        for service in services:
            show_project = service.name in duplicates
            label = build_service_label(service, show_project)
            payload = f"{encode_project_name(service.project_name)}:{service.name}"
            option_map[label] = (action_name, payload)
        return option_map

    def build_container_option_map(service_payload: str | None = None, session: ChatSession | None = None) -> dict[str, tuple[str, str]]:
        option_map: dict[str, tuple[str, str]] = {}
        containers = list_containers(session)
        if service_payload is not None:
            service = get_service_by_payload(service_payload, session)
            containers = list(service.containers)

        for container in containers:
            option_map[build_container_label(container)] = ("container", container.id)
        return option_map

    def list_backups(session: ChatSession | None = None) -> list[BackupArchive]:
        return list_backup_archives(
            target_dir=settings.backup_target_dir,
            timezone_info=get_active_monitor(session).timezone,
        )

    def get_backup_by_name(archive_name: str, session: ChatSession | None = None) -> BackupArchive:
        return find_backup_archive(
            archive_name,
            target_dir=settings.backup_target_dir,
            timezone_info=get_active_monitor(session).timezone,
        )

    def build_backup_label(archive: BackupArchive) -> str:
        return f"{archive.name} · {format_bytes(archive.size_bytes)}"

    def build_backup_option_map(action_name: str, session: ChatSession | None = None) -> dict[str, tuple[str, str]]:
        return {
            build_backup_label(archive): (action_name, archive.name)
            for archive in list_backups(session)
        }

    def has_tracked_chat(session: ChatSession) -> bool:
        return bool(session.bot_message_ids or session.user_message_ids)

    def current_keyboard(session: ChatSession) -> ReplyKeyboardMarkup:
        include_clear_chat = has_tracked_chat(session)
        if session.screen == "services_menu":
            return build_service_menu(list(session.option_map), include_clear_chat=include_clear_chat)
        if session.screen == "service_detail":
            return build_service_detail_menu(include_clear_chat=include_clear_chat)
        if session.screen == "containers_menu":
            return build_container_menu(list(session.option_map), include_clear_chat=include_clear_chat)
        if session.screen == "container_detail":
            return build_container_detail_menu(include_clear_chat=include_clear_chat)
        if session.screen == "restart_confirm":
            return build_restart_confirm_menu(include_clear_chat=include_clear_chat)
        if session.screen == "stats_menu":
            return build_stats_menu(list(session.option_map), include_clear_chat=include_clear_chat)
        if session.screen == "stats_detail":
            return build_detail_menu(include_clear_chat=include_clear_chat)
        if session.screen == "resources":
            return build_detail_menu(include_clear_chat=include_clear_chat)
        if session.screen == "logs_source_menu":
            return build_logs_source_menu(list(session.option_map), include_clear_chat=include_clear_chat)
        if session.screen == "logs_tail_menu":
            return build_log_tail_menu(include_clear_chat=include_clear_chat)
        if session.screen == "system":
            return build_system_menu(include_clear_chat=include_clear_chat)
        if session.screen in {"about", "failed_logins"}:
            return build_system_menu(include_clear_chat=include_clear_chat)
        if session.screen == "command_confirm":
            return build_command_confirm_menu(include_clear_chat=include_clear_chat)
        if session.screen == "commands_input":
            return build_commands_input_menu(include_clear_chat=include_clear_chat)
        if session.screen == "backup_menu":
            return build_backup_menu(include_clear_chat=include_clear_chat)
        if session.screen in {"backup_download_menu", "backup_delete_menu"}:
            return build_backup_archive_menu(list(session.option_map), include_clear_chat=include_clear_chat)
        if session.screen == "backup_confirm":
            return build_backup_confirm_menu(include_clear_chat=include_clear_chat)
        if session.screen == "backup_delete_confirm":
            return build_backup_delete_confirm_menu(include_clear_chat=include_clear_chat)
        if session.screen == "cleanup_confirm":
            return build_cleanup_confirm_menu(include_clear_chat=include_clear_chat)
        return build_main_menu(include_clear_chat=include_clear_chat)

    async def send_docker_error(message: Message, session: ChatSession) -> None:
        logger.exception("Ошибка обращения к Docker")
        await send_text(
            message,
            session,
            (
                "Не удалось получить данные из Docker. "
                "Проверь доступ к /var/run/docker.sock и переменную MONITOR_DOCKER_PROJECT."
            ),
            reply_markup=current_keyboard(session),
        )

    async def send_system_error(message: Message, session: ChatSession) -> None:
        logger.exception("Ошибка чтения системных метрик")
        await send_text(
            message,
            session,
            (
                "Не удалось получить системные метрики. "
                "Проверь read-only mounts для MONITOR_SYSTEM_PROC_PATH и MONITOR_SYSTEM_DISK_PATH."
            ),
            reply_markup=current_keyboard(session),
        )

    async def send_lookup_error(message: Message, session: ChatSession, error: LookupError) -> None:
        available = ", ".join(service_display_name(service, show_project=True) for service in list_services(session)) or "сервисов нет"
        await send_text(
            message,
            session,
            f"{escape(str(error))}\n\nДоступные сервисы: {escape(available)}",
            reply_markup=current_keyboard(session),
        )

    async def delete_message_group(bot, chat_id: int, message_ids: list[int]) -> None:
        for message_id in dict.fromkeys(message_ids):
            with suppress(TelegramBadRequest):
                await bot.delete_message(chat_id=chat_id, message_id=message_id)

    async def delete_log_messages(bot, chat_id: int, session: ChatSession) -> None:
        if not session.log_message_ids:
            return
        await delete_message_group(bot, chat_id, session.log_message_ids)
        session.log_message_ids.clear()

    async def delete_command_messages(bot, chat_id: int, session: ChatSession) -> None:
        if not session.command_message_ids:
            return
        await delete_message_group(bot, chat_id, session.command_message_ids)
        session.command_message_ids.clear()

    def trim_output(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        shortened = max(limit - 80, 0)
        return f"{text[:shortened].rstrip()}\n\n[Вывод обрезан ботом из-за ограничения размера.]"

    def split_text(text: str, limit: int) -> list[str]:
        if not text:
            return ["Вывод отсутствует."]

        chunks: list[str] = []
        current = ""

        for line in text.splitlines():
            piece = f"{line}\n"
            if len(current) + len(piece) > limit and current:
                chunks.append(current.rstrip())
                current = piece
                continue

            if len(piece) > limit:
                if current:
                    chunks.append(current.rstrip())
                    current = ""
                start = 0
                while start < len(piece):
                    chunks.append(piece[start : start + limit].rstrip())
                    start += limit
                continue

            current += piece

        if current:
            chunks.append(current.rstrip())

        return chunks or ["Вывод отсутствует."]

    def build_log_title(source_kind: str, project_name: str | None, service_name: str | None, tail: int, session: ChatSession | None = None) -> str:
        if source_kind == "all":
            return f"Логи всех контейнеров, последние {tail} строк"

        if source_kind == "container":
            container = get_container_by_id(service_name or "", session)
            display_name = container.name
            if container.project_name:
                display_name = f"{container.project_name}/{container.service_name}/{container.name}"
            return f"Логи контейнера {display_name}, последние {tail} строк"

        display_name = service_name or "неизвестный сервис"
        if project_name:
            display_name = f"{project_name}/{display_name}"
        return format_logs_caption(display_name, tail)

    def build_service_stats_title(service: ServiceInfo) -> str:
        title = service_display_name(service, show_project=True)
        return f"Статистика сервиса {title}"

    def build_container_stats_title(container: ContainerInfo) -> str:
        title = container.name
        if container.project_name:
            title = f"{container.project_name}/{container.service_name}/{container.name}"
        return f"Статистика контейнера {title}"

    def build_restart_warning(container: ContainerInfo) -> str:
        title = container.name
        if container.project_name:
            title = f"{container.project_name}/{container.service_name}/{container.name}"
        return "\n".join(
            [
                "⚠️ <b>Подтверждение перезапуска</b>",
                f"<b>Контейнер:</b> {escape(title)}",
                "Перезапуск может временно прервать соединения и работу зависящих сервисов.",
                "Нажми `Подтвердить перезапуск`, если точно хочешь продолжить.",
            ]
        )

    def build_command_intro_text(session: ChatSession | None = None) -> str:
        return "\n".join(
            [
                "⚠️ <b>Команды на сервере</b>",
                "Пришли одной строкой команду для выполнения на хосте.",
                f"Команда будет выполнена без интерактивного режима и с таймаутом {settings.command_timeout_seconds} сек.",
                "После отправки бот попросит отдельное подтверждение.",
            ]
        )

    def build_command_confirm_text(command: str) -> str:
        return "\n".join(
            [
                "⚠️ <b>Подтверждение выполнения команды</b>",
                "Команда будет запущена на самом сервере.",
                "<b>Команда:</b>",
                f"<pre>{escape(command)}</pre>",
                "Нажми `Выполнить команду`, если хочешь продолжить.",
            ]
        )

    def build_command_result_header(exit_code: int, duration_seconds: float, timed_out: bool) -> str:
        status = "по таймауту" if timed_out else "завершена"
        return "\n".join(
            [
                f"<b>Команда {status}</b>",
                f"<b>Код выхода:</b> {exit_code}",
                f"<b>Длительность:</b> {duration_seconds:.2f} сек.",
            ]
        )

    def build_backup_confirm_text() -> str:
        return "\n".join(
            [
                "⚠️ <b>Подтверждение бекапа</b>",
                f"<b>Источник:</b> <code>{escape(settings.backup_source_dir)}</code>",
                f"<b>Куда сохранить:</b> <code>{escape(settings.backup_target_dir)}</code>",
                f"<b>Таймаут:</b> {settings.backup_timeout_seconds} сек.",
                "Будет создан tar-архив со всем содержимым директории.",
                "Нажми `Создать бекап`, если хочешь продолжить.",
            ]
        )

    def build_backup_menu_text(session: ChatSession | None = None) -> str:
        archives = list_backups(session)
        lines = [
            "🗄️ <b>Бекапы</b>",
            f"<b>Источник:</b> <code>{escape(settings.backup_source_dir)}</code>",
            f"<b>Каталог:</b> <code>{escape(settings.backup_target_dir)}</code>",
            f"<b>Архивов:</b> {len(archives)}",
        ]
        if not archives:
            lines.extend(["", "Архивов пока нет."])
            return "\n".join(lines)

        total_size = sum(archive.size_bytes for archive in archives)
        lines.append(f"<b>Общий размер:</b> {format_bytes(total_size)}")
        lines.append("")
        lines.append("<b>Последние архивы</b>")
        for archive in archives[:10]:
            lines.append(
                " · ".join(
                    [
                        f"<code>{escape(archive.name)}</code>",
                        escape(format_bytes(archive.size_bytes)),
                        escape(format_datetime(archive.modified_at)),
                    ]
                )
            )
        if len(archives) > 10:
            lines.append(f"И ещё: {len(archives) - 10}")
        return "\n".join(lines)

    def build_backup_archive_details(archive: BackupArchive) -> str:
        return "\n".join(
            [
                f"<b>Архив:</b> <code>{escape(archive.name)}</code>",
                f"<b>Путь на сервере:</b> <code>{escape(archive.host_path)}</code>",
                f"<b>Размер:</b> {escape(format_bytes(archive.size_bytes))}",
                f"<b>Изменён:</b> {escape(format_datetime(archive.modified_at))}",
            ]
        )

    def build_backup_select_text(action_title: str, session: ChatSession | None = None) -> str:
        archives = list_backups(session)
        if not archives:
            return (
                "🗄️ <b>Бекапы</b>\n"
                f"В каталоге <code>{escape(settings.backup_target_dir)}</code> архивов нет."
            )

        return "\n".join(
            [
                f"🗄️ <b>{escape(action_title)}</b>",
                f"<b>Каталог:</b> <code>{escape(settings.backup_target_dir)}</code>",
                "Выбери архив кнопкой ниже.",
            ]
        )

    def build_backup_delete_confirm_text(archive: BackupArchive) -> str:
        return "\n".join(
            [
                "⚠️ <b>Подтверждение удаления бекапа</b>",
                build_backup_archive_details(archive),
                "Файл будет удалён с сервера без восстановления.",
                "Нажми `Подтвердить удаление`, если точно хочешь продолжить.",
            ]
        )

    def build_backup_result_header(exit_code: int, duration_seconds: float, timed_out: bool) -> str:
        if timed_out:
            title = "❌ <b>Создание бекапа остановлено по таймауту</b>"
        elif exit_code == 0:
            title = "✅ <b>Бекап создан</b>"
        else:
            title = "❌ <b>Не удалось создать бекап</b>"

        return "\n".join(
            [
                title,
                f"<b>Код выхода:</b> {exit_code}",
                f"<b>Длительность:</b> {duration_seconds:.2f} сек.",
            ]
        )

    def build_backup_delete_result_header(exit_code: int, duration_seconds: float, timed_out: bool) -> str:
        if timed_out:
            title = "❌ <b>Удаление бекапа остановлено по таймауту</b>"
        elif exit_code == 0:
            title = "✅ <b>Бекап удалён</b>"
        else:
            title = "❌ <b>Не удалось удалить бекап</b>"

        return "\n".join(
            [
                title,
                f"<b>Код выхода:</b> {exit_code}",
                f"<b>Длительность:</b> {duration_seconds:.2f} сек.",
            ]
        )

    def build_about_text(session: ChatSession | None = None) -> str:
        uptime_seconds = int((datetime.now(get_active_monitor(session).timezone) - started_at).total_seconds())
        project_name = settings.docker_project_name or "все compose-проекты"
        excluded_services = ", ".join(sorted(settings.excluded_services)) or "нет"
        lines = [
                "ℹ️ <b>О боте</b>",
                f"<b>Версия:</b> {escape(settings.bot_version)}",
                f"<b>Дата сборки:</b> {escape(settings.bot_build_date)}",
                f"<b>Образ:</b> <code>{escape(settings.bot_image_name)}</code>",
                f"<b>Uptime:</b> {escape(format_duration(uptime_seconds))}",
                "",
                "<b>Процесс</b>",
                *build_process_info_lines(),
                "",
                "<b>Активные настройки</b>",
                f"<b>Docker project:</b> {escape(project_name)}",
                f"<b>Исключены сервисы:</b> {escape(excluded_services)}",
                f"<b>Docker/system poll:</b> {settings.alert_poll_seconds} сек.",
                f"<b>Login poll:</b> {settings.login_poll_seconds} сек.",
                f"<b>Login alerts:</b> {'включены' if settings.login_alerts_enabled else 'выключены'}",
                f"<b>Бекапы:</b> <code>{escape(settings.backup_source_dir)}</code> → <code>{escape(settings.backup_target_dir)}</code>",
                f"<b>Очистка:</b> <code>{escape(settings.cleanup_path)}</code>",
                f"<b>Команды timeout:</b> {settings.command_timeout_seconds} сек.",
            ]
        return "\n".join(lines)

    def format_failed_login_event(event: FailedLoginEvent) -> str:
        source = event.source or "неизвестно"
        host = event.host_name or "неизвестно"
        return "\n".join(
            [
                f"<b>Время:</b> {escape(format_datetime(event.happened_at))}",
                f"<b>Пользователь:</b> {escape(event.user_name)}",
                f"<b>Источник:</b> {escape(source)}",
                f"<b>Хост:</b> {escape(host)}",
                f"<b>Причина:</b> {escape(event.reason)}",
            ]
        )

    def build_failed_logins_text() -> str:
        if login_monitor is None:
            return "🔐 <b>Ошибки входа</b>\nМониторинг входов выключен."

        events = login_monitor.list_failed_login_events(limit=20)
        lines = [
            "🔐 <b>Ошибки входа</b>",
            f"<b>Источники:</b> {escape(', '.join(settings.login_log_paths) or 'не заданы')}",
            f"<b>Показано:</b> {len(events)}",
        ]
        if not events:
            lines.append("")
            lines.append("Свежих неудачных попыток входа не найдено.")
            return "\n".join(lines)

        for index, event in enumerate(events, start=1):
            lines.append("")
            lines.append(f"<b>#{index}</b>")
            lines.append(format_failed_login_event(event))
        return "\n".join(lines)

    def build_cleanup_confirm_text() -> str:
        candidates = list_cleanup_candidates(settings.cleanup_path)
        total_size = sum(candidate.size_bytes for candidate in candidates)
        lines = [
            "⚠️ <b>Подтверждение очистки</b>",
            f"<b>Каталог:</b> <code>{escape(settings.cleanup_path)}</code>",
            f"<b>Будет удалено:</b> {len(candidates)} элементов",
            f"<b>Очищаемый размер:</b> {escape(format_bytes(total_size))}",
        ]
        if candidates:
            lines.append("")
            lines.append("<b>К удалению</b>")
            for candidate in candidates[:10]:
                lines.append(f"<code>{escape(str(candidate.path))}</code> · {escape(format_bytes(candidate.size_bytes))}")
            if len(candidates) > 10:
                lines.append(f"И ещё: {len(candidates) - 10}")
        else:
            lines.append("")
            lines.append("Подходящих временных каталогов не найдено.")

        lines.extend(
            [
                "",
                "Удаляются каталоги <code>__pycache__</code>, <code>.pytest_cache</code> и директории <code>tmp*</code> внутри указанного пути.",
                "Нажми `Подтвердить очистку`, если хочешь продолжить.",
            ]
        )
        return "\n".join(lines)

    def build_cleanup_result_header(exit_code: int, duration_seconds: float, timed_out: bool) -> str:
        if timed_out:
            title = "❌ <b>Очистка остановлена по таймауту</b>"
        elif exit_code == 0:
            title = "✅ <b>Очистка завершена</b>"
        else:
            title = "❌ <b>Не удалось выполнить очистку</b>"

        return "\n".join(
            [
                title,
                f"<b>Код выхода:</b> {exit_code}",
                f"<b>Длительность:</b> {duration_seconds:.2f} сек.",
            ]
        )

    async def send_overview(message: Message, session: ChatSession) -> None:
        session.screen = "home"
        session.option_map.clear()
        session.current_service_payload = None
        session.current_stats_payload = None
        session.current_stats_return_screen = None
        session.current_container_id = None
        session.current_container_filter_payload = None
        session.current_container_return_screen = None
        session.current_log_descriptor = None
        session.current_log_tail = None
        session.current_log_return_screen = None
        session.current_backup_name = None
        session.pending_command = None
        await send_text(message, session, build_overview_text(session), reply_markup=current_keyboard(session))

    async def show_resources_page(message: Message, session: ChatSession) -> None:
        session.screen = "resources"
        session.option_map.clear()
        session.current_stats_payload = None
        session.current_stats_return_screen = None
        snapshot = get_active_system_monitor(session).get_snapshot()
        stats = await asyncio.to_thread(get_active_monitor(session).get_service_stats)
        await send_text(
            message,
            session,
            format_resources(snapshot, stats),
            reply_markup=current_keyboard(session),
        )

    async def show_services_menu(message: Message, session: ChatSession) -> None:
        session.screen = "services_menu"
        session.option_map = build_service_option_map("status", session)
        session.current_service_payload = None
        await send_text(
            message,
            session,
            "Выбери сервис, чтобы посмотреть детальный статус.",
            reply_markup=current_keyboard(session),
        )

    async def show_service_details(message: Message, session: ChatSession, payload: str) -> None:
        service = get_service_by_payload(payload, session)
        session.screen = "service_detail"
        session.option_map.clear()
        session.current_service_payload = payload
        await send_text(
            message,
            session,
            format_service_details(service),
            reply_markup=current_keyboard(session),
        )

    async def show_containers_menu(
        message: Message,
        session: ChatSession,
        service_payload: str | None = None,
        *,
        return_screen: str = "home",
    ) -> None:
        session.screen = "containers_menu"
        session.option_map = build_container_option_map(service_payload, session)
        session.current_container_id = None
        session.current_container_filter_payload = service_payload
        session.current_container_return_screen = return_screen

        text = "Выбери контейнер, чтобы посмотреть состояние и доступные действия."
        if service_payload is not None:
            service = get_service_by_payload(service_payload, session)
            text = (
                "Выбери контейнер сервиса "
                f"{escape(service_display_name(service, show_project=True))}, чтобы посмотреть состояние и действия."
            )

        await send_text(
            message,
            session,
            text,
            reply_markup=current_keyboard(session),
        )

    async def show_container_details(message: Message, session: ChatSession, container_id: str) -> None:
        container = get_container_by_id(container_id, session)
        session.screen = "container_detail"
        session.option_map.clear()
        session.current_container_id = container_id
        await send_text(
            message,
            session,
            format_container_details(container),
            reply_markup=current_keyboard(session),
        )

    async def show_restart_confirm(message: Message, session: ChatSession) -> None:
        if session.current_container_id is None:
            await show_services_menu(message, session)
            return

        container = get_container_by_id(session.current_container_id, session)
        session.screen = "restart_confirm"
        await send_text(
            message,
            session,
            build_restart_warning(container),
            reply_markup=current_keyboard(session),
        )

    async def restart_current_container(message: Message, session: ChatSession) -> None:
        if session.current_container_id is None:
            await show_services_menu(message, session)
            return

        container = get_active_monitor(session).restart_container(session.current_container_id, settings.restart_timeout_seconds)
        session.screen = "container_detail"
        await send_text(
            message,
            session,
            "\n".join(
                [
                    "✅ <b>Контейнер перезапущен</b>",
                    format_container_details(container),
                ]
            ),
            reply_markup=current_keyboard(session),
        )

    async def show_stats_menu(message: Message, session: ChatSession) -> None:
        session.screen = "stats_menu"
        session.option_map = build_service_option_map("stats", session)
        session.current_stats_payload = None
        session.current_stats_return_screen = None
        await send_text(
            message,
            session,
            "Выбери сервис, чтобы посмотреть статистику CPU, RAM и сети.",
            reply_markup=current_keyboard(session),
        )

    async def show_service_stats(message: Message, session: ChatSession, payload: str, return_screen: str) -> None:
        service = get_service_by_payload(payload, session)
        stats = await asyncio.to_thread(
            get_active_monitor(session).get_service_stats_by_ref,
            service.project_name,
            service.name,
        )
        session.screen = "stats_detail"
        session.option_map.clear()
        session.current_stats_payload = f"svc:{payload}"
        session.current_stats_return_screen = return_screen
        await send_text(
            message,
            session,
            format_stats(stats, service_name=service.name, title=build_service_stats_title(service)),
            reply_markup=current_keyboard(session),
        )

    async def show_container_stats(message: Message, session: ChatSession, container_id: str, return_screen: str) -> None:
        container = get_container_by_id(container_id, session)
        container_stats = await asyncio.to_thread(get_active_monitor(session).get_container_stats, container_id)
        stats = [container_stats]
        session.screen = "stats_detail"
        session.option_map.clear()
        session.current_stats_payload = f"ctr:{container_id}"
        session.current_stats_return_screen = return_screen
        await send_text(
            message,
            session,
            format_stats(stats, title=build_container_stats_title(container)),
            reply_markup=current_keyboard(session),
        )

    async def show_system_page(message: Message, session: ChatSession) -> None:
        session.screen = "system"
        session.option_map.clear()
        await send_text(message, session, build_system_text(session), reply_markup=current_keyboard(session))

    async def show_logs_source_menu(message: Message, session: ChatSession) -> None:
        session.screen = "logs_source_menu"
        session.option_map = build_service_option_map("logsrc", session)
        session.current_log_descriptor = None
        session.current_log_tail = None
        session.current_log_return_screen = None
        await send_text(
            message,
            session,
            "Выбери источник логов: конкретный сервис или все контейнеры.",
            reply_markup=current_keyboard(session),
        )

    async def show_log_tail_menu(
        message: Message,
        session: ChatSession,
        descriptor: str,
        *,
        return_screen: str,
    ) -> None:
        source_kind, project_name, service_name = parse_log_source_descriptor(descriptor)
        session.screen = "logs_tail_menu"
        session.option_map.clear()
        session.current_log_descriptor = descriptor
        session.current_log_tail = None
        session.current_log_return_screen = return_screen

        if source_kind == "all":
            text = "Сколько строк показать для всех контейнеров?"
        elif source_kind == "container":
            container = get_container_by_id(service_name or "", session)
            container_title = container.name
            if container.project_name:
                container_title = f"{container.project_name}/{container.service_name}/{container.name}"
            text = f"Сколько строк логов показать для контейнера {escape(container_title)}?"
        else:
            service = get_active_monitor(session).get_service_by_ref(project_name, service_name or "")
            text = (
                "Сколько строк логов показать для сервиса "
                f"{escape(service_display_name(service, show_project=True))}?"
            )

        await send_text(message, session, text, reply_markup=current_keyboard(session))

    async def send_log_bundle(message: Message, session: ChatSession, tail: int) -> None:
        descriptor = session.current_log_descriptor
        if descriptor is None:
            await show_logs_source_menu(message, session)
            return

        source_kind, project_name, service_name = parse_log_source_descriptor(descriptor)
        active_mon = get_active_monitor(session)
        if source_kind == "all":
            logs_text = active_mon.get_all_logs(tail)
        elif source_kind == "container":
            _, logs_text = active_mon.get_container_logs(service_name or "", tail)
        else:
            _, logs_text = active_mon.get_service_logs_by_ref(project_name, service_name or "", tail)

        await delete_log_messages(message.bot, message.chat.id, session)

        title = build_log_title(source_kind, project_name, service_name, tail)
        chunks = split_text(logs_text, max(800, min(settings.max_inline_log_chars, 2800)))
        session.screen = "logs_tail_menu"
        session.current_log_tail = tail

        for index, chunk in enumerate(chunks, start=1):
            header = f"<b>{escape(title)}</b>"
            if len(chunks) > 1:
                header = f"{header}\n<b>Часть {index}/{len(chunks)}</b>"

            sent = await send_text(
                message,
                session,
                f"{header}\n<pre>{escape(chunk)}</pre>",
                reply_markup=current_keyboard(session) if index == len(chunks) else None,
            )
            remember_message_id(session.log_message_ids, sent.message_id)

    async def show_commands_intro(message: Message, session: ChatSession) -> None:
        session.screen = "commands_input"
        session.option_map.clear()
        session.pending_command = None
        await send_text(message, session, build_command_intro_text(), reply_markup=current_keyboard(session))

    async def show_command_confirm(message: Message, session: ChatSession, command: str) -> None:
        session.screen = "command_confirm"
        session.pending_command = command
        await send_text(message, session, build_command_confirm_text(command), reply_markup=current_keyboard(session))

    async def run_pending_command(message: Message, session: ChatSession) -> None:
        command = session.pending_command
        if not command:
            await show_commands_intro(message, session)
            return

        await delete_command_messages(message.bot, message.chat.id, session)

        progress = await send_text(
            message,
            session,
            "⏳ <b>Выполняю команду на сервере...</b>",
            reply_markup=current_keyboard(session),
        )
        remember_message_id(session.command_message_ids, progress.message_id)

        result = await asyncio.to_thread(command_executor.run, command)
        header = build_command_result_header(result.exit_code, result.duration_seconds, result.timed_out)
        output = trim_output(result.output, settings.command_max_output_chars)
        chunks = split_text(output, min(settings.command_max_output_chars, 2800))

        session.screen = "commands_input"
        session.pending_command = None

        for index, chunk in enumerate(chunks, start=1):
            body = header
            if len(chunks) > 1:
                body = f"{body}\n<b>Часть {index}/{len(chunks)}</b>"
            sent = await send_text(
                message,
                session,
                f"{body}\n<pre>{escape(chunk)}</pre>",
                reply_markup=current_keyboard(session) if index == len(chunks) else None,
            )
            remember_message_id(session.command_message_ids, sent.message_id)

    async def show_backup_menu(message: Message, session: ChatSession) -> None:
        session.screen = "backup_menu"
        session.option_map.clear()
        session.current_backup_name = None
        session.pending_command = None
        await send_text(message, session, build_backup_menu_text(), reply_markup=current_keyboard(session))

    async def show_backup_archive_menu(message: Message, session: ChatSession, action_name: str) -> None:
        if action_name == "backup_download":
            session.screen = "backup_download_menu"
            title = "Скачать бекап"
        else:
            session.screen = "backup_delete_menu"
            title = "Удалить бекап"

        session.option_map = build_backup_option_map(action_name, session)
        session.current_backup_name = None
        await send_text(message, session, build_backup_select_text(title), reply_markup=current_keyboard(session))

    async def show_backup_confirm(message: Message, session: ChatSession) -> None:
        session.screen = "backup_confirm"
        session.option_map.clear()
        session.current_backup_name = None
        session.pending_command = None
        await send_text(message, session, build_backup_confirm_text(), reply_markup=current_keyboard(session))

    async def run_root_backup(message: Message, session: ChatSession) -> None:
        backup_command = build_backup_command(
            datetime.now(get_active_monitor(session).timezone),
            source_dir=settings.backup_source_dir,
            target_dir=settings.backup_target_dir,
        )

        await delete_command_messages(message.bot, message.chat.id, session)

        progress = await send_text(
            message,
            session,
            "⏳ <b>Создаю tar-архив директории root...</b>",
            reply_markup=current_keyboard(session),
        )
        remember_message_id(session.command_message_ids, progress.message_id)

        result = await asyncio.to_thread(
            command_executor.run,
            backup_command.command,
            timeout_seconds=settings.backup_timeout_seconds,
        )

        header = build_backup_result_header(result.exit_code, result.duration_seconds, result.timed_out)
        output = trim_output(result.output, settings.command_max_output_chars)
        chunks = split_text(output, min(settings.command_max_output_chars, 2800))

        session.screen = "backup_menu" if result.exit_code == 0 and not result.timed_out else "backup_confirm"

        for index, chunk in enumerate(chunks, start=1):
            body = "\n".join(
                [
                    header,
                    f"<b>Источник:</b> <code>{escape(backup_command.source_dir)}</code>",
                    f"<b>Архив:</b> <code>{escape(backup_command.archive_path)}</code>",
                ]
            )
            if len(chunks) > 1:
                body = f"{body}\n<b>Часть {index}/{len(chunks)}</b>"
            sent = await send_text(
                message,
                session,
                f"{body}\n<pre>{escape(chunk)}</pre>",
                reply_markup=current_keyboard(session) if index == len(chunks) else None,
            )
            remember_message_id(session.command_message_ids, sent.message_id)

    async def send_backup_archive(message: Message, session: ChatSession, archive_name: str) -> None:
        archive = get_backup_by_name(archive_name, session)
        session.screen = "backup_menu"
        session.option_map.clear()
        session.current_backup_name = None

        caption = "\n".join(
            [
                "📦 <b>Бекап</b>",
                build_backup_archive_details(archive),
            ]
        )

        if archive.size_bytes > 200 * 1024 * 1024:
            await send_text(
                message,
                session,
                (
                    "❌ <b>Файл слишком большой для Telegram</b> (лимит 50 МБ).\n\n"
                    f"Размер: <b>{format_bytes(archive.size_bytes)}</b>\n"
                    f"Путь на сервере: <code>{archive.host_path}</code>\n\n"
                    "Используй <code>scp</code> или <code>sftp</code> для скачивания этого файла."
                ),
                reply_markup=current_keyboard(session),
            )
            return

        try:
            sent = await message.answer_document(
                document=FSInputFile(str(archive.container_path), filename=archive.name),
                caption=caption,
                reply_markup=current_keyboard(session),
            )
        except Exception:
            await send_text(
                message,
                session,
                (
                    "Не удалось отправить архив в Telegram. "
                    "Проверь размер файла и доступность архива на сервере.\n\n"
                    f"{build_backup_archive_details(archive)}"
                ),
                reply_markup=current_keyboard(session),
            )
            return

        remember_message_id(session.bot_message_ids, sent.message_id)

    async def show_backup_delete_confirm(message: Message, session: ChatSession, archive_name: str) -> None:
        archive = get_backup_by_name(archive_name, session)
        session.screen = "backup_delete_confirm"
        session.option_map.clear()
        session.current_backup_name = archive.name
        await send_text(message, session, build_backup_delete_confirm_text(archive), reply_markup=current_keyboard(session))

    async def delete_selected_backup(message: Message, session: ChatSession) -> None:
        archive_name = session.current_backup_name
        if not archive_name:
            await show_backup_archive_menu(message, session, "backup_delete")
            return

        delete_command = build_delete_backup_command(
            archive_name,
            target_dir=settings.backup_target_dir,
        )

        await delete_command_messages(message.bot, message.chat.id, session)

        progress = await send_text(
            message,
            session,
            "⏳ <b>Удаляю бекап...</b>",
            reply_markup=current_keyboard(session),
        )
        remember_message_id(session.command_message_ids, progress.message_id)

        result = await asyncio.to_thread(
            command_executor.run,
            delete_command.command,
            timeout_seconds=settings.command_timeout_seconds,
        )

        header = build_backup_delete_result_header(result.exit_code, result.duration_seconds, result.timed_out)
        output = trim_output(result.output, settings.command_max_output_chars)
        chunks = split_text(output, min(settings.command_max_output_chars, 2800))

        session.screen = "backup_menu" if result.exit_code == 0 and not result.timed_out else "backup_delete_confirm"
        if result.exit_code == 0 and not result.timed_out:
            session.current_backup_name = None

        for index, chunk in enumerate(chunks, start=1):
            body = header
            if len(chunks) > 1:
                body = f"{body}\n<b>Часть {index}/{len(chunks)}</b>"
            sent = await send_text(
                message,
                session,
                f"{body}\n<pre>{escape(chunk)}</pre>",
                reply_markup=current_keyboard(session) if index == len(chunks) else None,
            )
            remember_message_id(session.command_message_ids, sent.message_id)

    async def show_about_page(message: Message, session: ChatSession) -> None:
        session.screen = "about"
        session.option_map.clear()
        await send_text(message, session, build_about_text(), reply_markup=current_keyboard(session))

    async def show_system_menu(message: Message, session: ChatSession) -> None:
        session.screen = "system"
        session.option_map.clear()
        await send_text(message, session, "⚙️ <b>Системные функции</b>", reply_markup=current_keyboard(session))

    # show_servers_menu и switch_server удалены

    async def show_failed_logins_page(message: Message, session: ChatSession) -> None:
        session.screen = "failed_logins"
        session.option_map.clear()
        await send_text(message, session, build_failed_logins_text(), reply_markup=current_keyboard(session))

    async def show_cleanup_confirm(message: Message, session: ChatSession) -> None:
        session.screen = "cleanup_confirm"
        session.option_map.clear()
        await send_text(message, session, build_cleanup_confirm_text(), reply_markup=current_keyboard(session))

    async def run_cleanup(message: Message, session: ChatSession) -> None:
        cleanup_command = build_cleanup_command(settings.cleanup_path)

        await delete_command_messages(message.bot, message.chat.id, session)

        progress = await send_text(
            message,
            session,
            "⏳ <b>Выполняю очистку...</b>",
            reply_markup=current_keyboard(session),
        )
        remember_message_id(session.command_message_ids, progress.message_id)

        result = await asyncio.to_thread(
            command_executor.run,
            cleanup_command.command,
            timeout_seconds=settings.cleanup_timeout_seconds,
        )

        header = build_cleanup_result_header(result.exit_code, result.duration_seconds, result.timed_out)
        output = trim_output(result.output, settings.command_max_output_chars)
        chunks = split_text(output, min(settings.command_max_output_chars, 2800))

        session.screen = "system" if result.exit_code == 0 and not result.timed_out else "cleanup_confirm"

        for index, chunk in enumerate(chunks, start=1):
            body = "\n".join(
                [
                    header,
                    f"<b>Каталог:</b> <code>{escape(cleanup_command.cleanup_path)}</code>",
                ]
            )
            if len(chunks) > 1:
                body = f"{body}\n<b>Часть {index}/{len(chunks)}</b>"
            sent = await send_text(
                message,
                session,
                f"{body}\n<pre>{escape(chunk)}</pre>",
                reply_markup=current_keyboard(session) if index == len(chunks) else None,
            )
            remember_message_id(session.command_message_ids, sent.message_id)

    async def clear_chat(message: Message, session: ChatSession) -> None:
        confirmation = await send_text(
            message,
            session,
            "🧹 <b>Очищаю сообщения этой сессии...</b>",
            reply_markup=build_main_menu(include_clear_chat=False),
            track=False,
        )

        old_bot_ids = list(session.bot_message_ids)
        old_user_ids = list(session.user_message_ids)
        session.log_message_ids.clear()
        session.command_message_ids.clear()
        session.bot_message_ids.clear()
        session.user_message_ids.clear()
        session.screen = "home"
        session.option_map.clear()
        session.current_service_payload = None
        session.current_stats_payload = None
        session.current_stats_return_screen = None
        session.current_container_id = None
        session.current_container_filter_payload = None
        session.current_container_return_screen = None
        session.current_log_descriptor = None
        session.current_log_tail = None
        session.current_log_return_screen = None
        session.current_backup_name = None
        session.pending_command = None

        await delete_message_group(message.bot, message.chat.id, old_bot_ids + old_user_ids)
        remember_message_id(session.bot_message_ids, confirmation.message_id)

    async def handle_refresh(message: Message, session: ChatSession) -> None:
        if session.screen == "services_menu":
            await show_services_menu(message, session)
            return
        if session.screen == "service_detail" and session.current_service_payload is not None:
            await show_service_details(message, session, session.current_service_payload)
            return
        if session.screen == "containers_menu":
            await show_containers_menu(
                message,
                session,
                session.current_container_filter_payload,
                return_screen=session.current_container_return_screen or "home",
            )
            return
        if session.screen == "container_detail" and session.current_container_id is not None:
            await show_container_details(message, session, session.current_container_id)
            return
        if session.screen == "restart_confirm":
            await show_restart_confirm(message, session)
            return
        if session.screen == "stats_menu":
            await show_stats_menu(message, session)
            return
        if session.screen == "stats_detail" and session.current_stats_payload is not None:
            stats_kind, stats_value = parse_stats_descriptor(session.current_stats_payload)
            stats_return_screen = session.current_stats_return_screen or "stats_menu"
            if stats_kind == "container":
                await show_container_stats(message, session, stats_value, stats_return_screen)
            else:
                await show_service_stats(message, session, stats_value, stats_return_screen)
            return
        if session.screen == "resources":
            await show_resources_page(message, session)
            return
        if session.screen == "logs_source_menu":
            await show_logs_source_menu(message, session)
            return
        if session.screen == "logs_tail_menu":
            if session.current_log_tail is not None:
                await send_log_bundle(message, session, session.current_log_tail)
            elif session.current_log_descriptor is not None:
                await show_log_tail_menu(
                    message,
                    session,
                    session.current_log_descriptor,
                    return_screen=session.current_log_return_screen or "logs_source_menu",
                )
            else:
                await show_logs_source_menu(message, session)
            return
        if session.screen == "about":
            await show_about_page(message, session)
            return
        if session.screen == "failed_logins":
            await show_failed_logins_page(message, session)
            return
        if session.screen == "commands_input":
            await show_commands_intro(message, session)
            return
        if session.screen == "command_confirm" and session.pending_command is not None:
            await show_command_confirm(message, session, session.pending_command)
            return
        if session.screen == "backup_confirm":
            await show_backup_confirm(message, session)
            return
        if session.screen == "backup_menu":
            await show_backup_menu(message, session)
            return
        if session.screen == "backup_download_menu":
            await show_backup_archive_menu(message, session, "backup_download")
            return
        if session.screen == "backup_delete_menu":
            await show_backup_archive_menu(message, session, "backup_delete")
            return
        if session.screen == "backup_delete_confirm" and session.current_backup_name is not None:
            await show_backup_delete_confirm(message, session, session.current_backup_name)
            return
        if session.screen == "cleanup_confirm":
            await show_cleanup_confirm(message, session)
            return
        await send_overview(message, session)

    async def handle_back(message: Message, session: ChatSession) -> None:
        if session.screen == "service_detail":
            await show_services_menu(message, session)
            return
        if session.screen == "containers_menu":
            if session.current_container_return_screen == "service_detail" and session.current_service_payload is not None:
                await show_service_details(message, session, session.current_service_payload)
                return
            await send_overview(message, session)
            return
        if session.screen == "container_detail":
            await show_containers_menu(
                message,
                session,
                session.current_container_filter_payload,
                return_screen=session.current_container_return_screen or "home",
            )
            return
        if session.screen == "restart_confirm":
            if session.current_container_id is not None:
                await show_container_details(message, session, session.current_container_id)
            else:
                await show_services_menu(message, session)
            return
        if session.screen == "stats_detail":
            if session.current_stats_return_screen == "service_detail" and session.current_service_payload is not None:
                await show_service_details(message, session, session.current_service_payload)
                return
            if session.current_stats_return_screen == "container_detail" and session.current_container_id is not None:
                await show_container_details(message, session, session.current_container_id)
                return
            await show_stats_menu(message, session)
            return
        if session.screen == "logs_tail_menu":
            if session.current_log_return_screen == "service_detail" and session.current_service_payload is not None:
                await show_service_details(message, session, session.current_service_payload)
                return
            if session.current_log_return_screen == "container_detail" and session.current_container_id is not None:
                await show_container_details(message, session, session.current_container_id)
                return
            await show_logs_source_menu(message, session)
            return
        if session.screen == "command_confirm":
            await show_commands_intro(message, session)
            return
        if session.screen == "backup_confirm":
            await show_backup_menu(message, session)
            return
        if session.screen in {"backup_download_menu", "backup_delete_menu"}:
            await show_backup_menu(message, session)
            return
        if session.screen == "backup_delete_confirm":
            await show_backup_archive_menu(message, session, "backup_delete")
            return
        if session.screen == "backup_menu":
            await send_overview(message, session)
            return
        if session.screen == "resources":
            await send_overview(message, session)
            return
        if session.screen == "system":
            await send_overview(message, session)
            return
        if session.screen == "cleanup_confirm":
            await show_system_menu(message, session)
            return
        await send_overview(message, session)

    @router.message(CommandStart())
    async def start_handler(message: Message) -> None:
        session = get_session(message.chat.id)
        remember_incoming(message, session)
        try:
            await send_text(
                message,
                session,
                "Бот мониторинга запущен. Управление находится в нижнем меню.",
                reply_markup=build_main_menu(include_clear_chat=has_tracked_chat(session)),
            )
            await send_overview(message, session)
        except DockerException:
            await send_docker_error(message, session)

    @router.callback_query()
    async def legacy_callback_handler(callback: CallbackQuery) -> None:
        if callback.message is None:
            await callback.answer("Используй нижнее меню.")
            return

        session = get_session(callback.message.chat.id)
        await callback.answer("Интерфейс обновлён. Используй нижнее меню.", show_alert=True)
        await send_chat_text(
            callback.bot,
            callback.message.chat.id,
            session,
            "Управление ботом теперь находится в нижнем меню.",
            reply_markup=current_keyboard(session),
        )

    @router.message()
    async def text_handler(message: Message) -> None:
        session = get_session(message.chat.id)
        remember_incoming(message, session)
        text = (message.text or "").strip()

        try:
            if text == MENU_OVERVIEW:
                await send_overview(message, session)
                return

            if text == MENU_RESOURCES:
                await show_resources_page(message, session)
                return

            if text == MENU_CONTAINERS:
                await show_containers_menu(message, session)
                return

            if text == MENU_COMMANDS:
                await show_commands_intro(message, session)
                return

            if text == MENU_BACKUP:
                await show_backup_menu(message, session)
                return

            if text == MENU_FAILED_LOGINS:
                await show_failed_logins_page(message, session)
                return

            if text == MENU_CLEANUP:
                await show_cleanup_confirm(message, session)
                return

            if text == MENU_SYSTEM:
                await show_system_menu(message, session)
                return

            if text == MENU_ABOUT:
                await show_about_page(message, session)
                return

            if text == MENU_REFRESH:
                await handle_refresh(message, session)
                return

            if text == ACTION_BACK:
                await handle_back(message, session)
                return

            if text == ACTION_CLEAR_CHAT:
                await clear_chat(message, session)
                return

            if text == ACTION_CANCEL:
                if session.screen == "restart_confirm" and session.current_container_id is not None:
                    await show_container_details(message, session, session.current_container_id)
                    return
                if session.screen == "command_confirm":
                    await show_commands_intro(message, session)
                    return
                if session.screen == "backup_confirm":
                    await show_backup_menu(message, session)
                    return
                if session.screen == "backup_delete_confirm":
                    await show_backup_archive_menu(message, session, "backup_delete")
                    return
                if session.screen == "cleanup_confirm":
                    await send_overview(message, session)
                    return
                await handle_back(message, session)
                return

            if text == ACTION_RESTART_CONTAINER and session.screen == "container_detail":
                await show_restart_confirm(message, session)
                return

            if text == ACTION_SERVICE_LOGS and session.screen == "service_detail" and session.current_service_payload is not None:
                await show_log_tail_menu(
                    message,
                    session,
                    f"svc:{session.current_service_payload}",
                    return_screen="service_detail",
                )
                return

            if text == ACTION_SERVICE_STATS and session.screen == "service_detail" and session.current_service_payload is not None:
                await show_service_stats(message, session, session.current_service_payload, "service_detail")
                return

            if text == ACTION_SERVICE_CONTAINERS and session.screen == "service_detail" and session.current_service_payload is not None:
                await show_containers_menu(
                    message,
                    session,
                    session.current_service_payload,
                    return_screen="service_detail",
                )
                return

            if text == ACTION_CONTAINER_LOGS and session.screen == "container_detail" and session.current_container_id is not None:
                await show_log_tail_menu(
                    message,
                    session,
                    f"ctr:{session.current_container_id}",
                    return_screen="container_detail",
                )
                return

            if text == ACTION_CONTAINER_STATS and session.screen == "container_detail" and session.current_container_id is not None:
                await show_container_stats(message, session, session.current_container_id, "container_detail")
                return

            if text == ACTION_CONFIRM_RESTART and session.screen == "restart_confirm":
                await restart_current_container(message, session)
                return

            if text == ACTION_CONFIRM_COMMAND and session.screen == "command_confirm":
                await run_pending_command(message, session)
                return

            if text == ACTION_CONFIRM_BACKUP and session.screen == "backup_confirm":
                await run_root_backup(message, session)
                return

            if text == ACTION_CREATE_BACKUP and session.screen == "backup_menu":
                await show_backup_confirm(message, session)
                return

            if text == ACTION_DOWNLOAD_BACKUP and session.screen == "backup_menu":
                await show_backup_archive_menu(message, session, "backup_download")
                return

            if text == ACTION_DELETE_BACKUP and session.screen == "backup_menu":
                await show_backup_archive_menu(message, session, "backup_delete")
                return

            if text == ACTION_CONFIRM_DELETE_BACKUP and session.screen == "backup_delete_confirm":
                await delete_selected_backup(message, session)
                return

            if text == ACTION_CONFIRM_CLEANUP and session.screen == "cleanup_confirm":
                await run_cleanup(message, session)
                return

            if text == ACTION_ALL_CONTAINERS and session.screen == "logs_source_menu":
                await show_log_tail_menu(message, session, "all", return_screen="logs_source_menu")
                return

            if text in LOG_TAIL_BUTTONS and session.screen == "logs_tail_menu":
                await send_log_bundle(message, session, LOG_TAIL_BUTTONS[text])
                return

            mapped_action = session.option_map.get(text)
            if mapped_action is not None:
                action_name, payload = mapped_action
                if action_name == "status":
                    await show_service_details(message, session, payload)
                    return
                if action_name == "stats":
                    await show_service_stats(message, session, payload, "stats_menu")
                    return
                if action_name == "logsrc":
                    await show_log_tail_menu(message, session, f"svc:{payload}", return_screen="logs_source_menu")
                    return
                if action_name == "container":
                    await show_container_details(message, session, payload)
                    return
                if action_name == "backup_download":
                    await send_backup_archive(message, session, payload)
                    return
                if action_name == "backup_delete":
                    await show_backup_delete_confirm(message, session, payload)
                    return

            if session.screen == "commands_input" and text:
                await show_command_confirm(message, session, text)
                return

            # Обработчики команд изменены

            await send_text(
                message,
                session,
                "Используй кнопки нижнего меню, чтобы открыть нужный раздел.",
                reply_markup=current_keyboard(session),
            )
        except LookupError as error:
            await send_lookup_error(message, session, error)
        except DockerException:
            await send_docker_error(message, session)
        except OSError:
            await send_system_error(message, session)
        except RuntimeError:
            await send_system_error(message, session)

    # Массовые задания удалены

    return router
