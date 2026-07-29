from __future__ import annotations

import asyncio
import html
import logging
import os
import sys
from datetime import datetime
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.backup import (
    build_backup_command,
    build_delete_backup_command,
    find_backup_archive,
    list_backup_archives,
)
from app.callbacks import BotCallback, CallbackAction
from app.formatters import (
    format_bytes,
    format_container_details,
    format_datetime,
    format_logs_caption,
    format_overview,
    format_preformatted_message,
    format_resources,
    format_service_details,
    format_stats,
    limit_html_message,
    service_level_emoji,
    status_emoji,
)
from app.keyboards import (
    ACTION_BACK,
    ACTION_CANCEL,
    build_inline_actions,
    build_inline_confirm,
    build_paginated_inline_menu,
)
from app.maintenance import build_cleanup_command
from app.navigation import ViewState
from app.sessions import SessionState, SessionStore
from app.ui import answer_callback, edit_or_send

if TYPE_CHECKING:
    from app.config import Settings
    from app.docker_monitor import DockerMonitor
    from app.host_command_executor import HostCommandExecutor, HostCommandResult
    from app.login_monitor import LoginLogMonitor
    from app.system_monitor import SystemMonitor


logger = logging.getLogger(__name__)
TELEGRAM_DOCUMENT_LIMIT_BYTES = 50 * 1024 * 1024


class InlineController:
    """Управляет редактируемыми экранами Telegram и их навигацией."""

    def __init__(
        self,
        *,
        monitor: DockerMonitor,
        system_monitor: SystemMonitor,
        login_monitor: LoginLogMonitor | None,
        command_executor: HostCommandExecutor,
        settings: Settings,
    ) -> None:
        self.monitor = monitor
        self.system_monitor = system_monitor
        self.login_monitor = login_monitor
        self.command_executor = command_executor
        self.settings = settings
        self.sessions = SessionStore()

    def register(self, router: Router) -> None:
        router.callback_query(BotCallback.filter())(self.handle_callback)
        router.callback_query()(self.handle_unknown_callback)

    def get_session(self, message: Message) -> SessionState:
        user_id = message.from_user.id if message.from_user else message.chat.id
        return self.sessions.get(message.chat.id, user_id)

    async def show_home(self, message: Message) -> None:
        session = self.get_session(message)
        session.input_mode = None
        session.navigation.reset()
        await self._render(message.bot, session, session.navigation.current)

    async def show_resources(self, message: Message) -> None:
        await self._open_from_message(message, "resources")

    async def show_containers(self, message: Message) -> None:
        await self._open_from_message(message, "containers")

    async def show_backup(self, message: Message) -> None:
        await self._open_from_message(message, "backup")

    async def show_system(self, message: Message) -> None:
        await self._open_from_message(message, "system")

    async def show_about(self, message: Message) -> None:
        await self._open_from_message(message, "about")

    async def show_failed_logins(self, message: Message) -> None:
        await self._open_from_message(message, "failed_logins")

    async def show_cleanup_confirmation(self, message: Message) -> None:
        session = self.get_session(message)
        session.input_mode = None
        view = self._open_confirmation(session, ("cleanup",))
        await self._render(message.bot, session, view)

    async def show_command_input(self, message: Message) -> None:
        session = self.get_session(message)
        session.input_mode = "command"
        session.navigation.open("command")
        await self._render(message.bot, session, session.navigation.current)

    async def refresh_from_message(self, message: Message) -> None:
        session = self.get_session(message)
        await self._render(message.bot, session, session.navigation.refresh())

    async def back_from_message(self, message: Message) -> None:
        session = self.get_session(message)
        session.input_mode = None
        await self._render(message.bot, session, session.navigation.back())

    async def accept_command_text(self, message: Message) -> bool:
        session = self.get_session(message)
        if session.input_mode != "command":
            return False

        command = (message.text or "").strip()
        if not command:
            return True
        if len(command) > 1000:
            await message.bot.send_message(
                chat_id=message.chat.id,
                text="Команда слишком длинная. Сократи её до 1000 символов и повтори.",
            )
            return True

        session.input_mode = None
        token = session.tokens.register(("command", command))
        session.navigation.open("confirm", payload=token)
        text = (
            "⚠️ <b>Подтверждение команды</b>\n\n"
            f"<code>{html.escape(command)}</code>\n\n"
            "Команда будет выполнена на хосте и может изменить его состояние."
        )
        await edit_or_send(
            bot=message.bot,
            chat_id=message.chat.id,
            text=limit_html_message(text),
            reply_markup=build_inline_confirm(confirm_text="✅ Выполнить", token=token),
        )
        return True

    async def _open_from_message(self, message: Message, screen: str) -> None:
        session = self.get_session(message)
        session.input_mode = None
        view = session.navigation.open(screen)
        await self._render(message.bot, session, view)

    async def handle_callback(
        self,
        callback: CallbackQuery,
        callback_data: BotCallback,
    ) -> None:
        notice: str | None = None
        try:
            if callback.message is None or callback.from_user is None:
                notice = "Экран недоступен."
                return
            session = self.sessions.get(callback.message.chat.id, callback.from_user.id)
            notice = await self._dispatch(callback, callback_data, session)
        except (LookupError, ValueError):
            notice = "Кнопка устарела. Обнови экран."
        except Exception:
            logger.exception("Ошибка обработки inline-действия")
            notice = "Не удалось выполнить действие."
            if callback.message is not None and callback.from_user is not None:
                session = self.sessions.get(callback.message.chat.id, callback.from_user.id)
                try:
                    await self._render_error(callback, session)
                except Exception:
                    logger.exception("Не удалось показать сообщение об ошибке")
        finally:
            await answer_callback(callback, notice)

    async def handle_unknown_callback(self, callback: CallbackQuery) -> None:
        await answer_callback(callback, "Неизвестная кнопка. Обнови экран.")

    async def _dispatch(
        self,
        callback: CallbackQuery,
        data: BotCallback,
        session: SessionState,
    ) -> str | None:
        action = self._parse_action(data.action)
        if action is None:
            return "Неизвестная кнопка. Обнови экран."

        if action == CallbackAction.PAGE:
            return None
        if action == CallbackAction.HOME:
            session.input_mode = None
            view = session.navigation.reset()
        elif action == CallbackAction.REFRESH:
            view = session.navigation.refresh()
        elif action in {CallbackAction.BACK, CallbackAction.CANCEL}:
            session.input_mode = None
            view = session.navigation.back()
        elif action == CallbackAction.RESOURCES:
            view = session.navigation.open("resources")
        elif action == CallbackAction.SERVICE_LIST:
            view = session.navigation.open("services", page=data.page, remember=data.page == 0)
        elif action == CallbackAction.SERVICE_OPEN:
            self._require_payload(session, data.token, "service")
            view = session.navigation.open("service", page=data.page, payload=data.token)
        elif action == CallbackAction.CONTAINER_LIST:
            if data.token != "-":
                self._require_payload(session, data.token, "service")
            view = session.navigation.open(
                "containers",
                page=data.page,
                payload=None if data.token == "-" else data.token,
                remember=data.page == 0,
            )
        elif action == CallbackAction.CONTAINER_OPEN:
            self._require_payload(session, data.token, "container")
            view = session.navigation.open("container", page=data.page, payload=data.token)
        elif action == CallbackAction.STATS:
            self._require_entity_payload(session, data.token)
            view = session.navigation.open("stats", payload=data.token)
        elif action == CallbackAction.LOGS:
            self._require_entity_payload(session, data.token)
            view = session.navigation.open("logs", payload=data.token)
        elif action == CallbackAction.BACKUP:
            view = session.navigation.open("backup")
        elif action == CallbackAction.BACKUP_LIST:
            view = session.navigation.open("backups", page=data.page, remember=data.page == 0)
        elif action == CallbackAction.BACKUP_OPEN:
            self._require_payload(session, data.token, "backup")
            view = session.navigation.open("backup_detail", page=data.page, payload=data.token)
        elif action == CallbackAction.BACKUP_DOWNLOAD:
            return await self._download_backup(callback, session, data.token)
        elif action == CallbackAction.BACKUP_CREATE:
            view = self._open_confirmation(session, ("backup_create",))
        elif action == CallbackAction.BACKUP_DELETE:
            payload = self._require_payload(session, data.token, "backup")
            view = self._open_confirmation(session, ("backup_delete", payload[1]))
        elif action == CallbackAction.SYSTEM:
            view = session.navigation.open("system")
        elif action == CallbackAction.ABOUT:
            view = session.navigation.open("about")
        elif action == CallbackAction.FAILED_LOGINS:
            view = session.navigation.open("failed_logins")
        elif action == CallbackAction.CLEANUP:
            view = self._open_confirmation(session, ("cleanup",))
        elif action == CallbackAction.COMMAND:
            session.input_mode = "command"
            view = session.navigation.open("command")
        elif action == CallbackAction.RESTART:
            payload = self._require_payload(session, data.token, "container")
            view = self._open_confirmation(session, ("restart", payload[1]))
        elif action == CallbackAction.CONFIRM:
            return await self._execute_confirmation(callback, session, data.token)
        else:
            return "Неизвестная кнопка. Обнови экран."

        await self._render(callback.bot, session, view, message=callback.message)
        return None

    async def _render(
        self,
        bot,
        session: SessionState,
        view: ViewState,
        *,
        message: Message | None = None,
    ) -> None:
        renderer = getattr(self, f"_render_{view.screen}", None)
        if renderer is None:
            session.navigation.reset()
            renderer = self._render_home
            view = session.navigation.current
        text, keyboard = await renderer(session, view)
        rendered = await edit_or_send(
            bot=bot,
            chat_id=session.key.chat_id,
            text=limit_html_message(text),
            reply_markup=keyboard,
            message=message,
        )
        session.screen = view.screen
        session.page = view.page
        session.screen_message_id = rendered.message_id

    async def _render_home(self, session: SessionState, view: ViewState):
        services, projects, snapshot = await asyncio.gather(
            asyncio.to_thread(self.monitor.list_services),
            asyncio.to_thread(self.monitor.list_project_names),
            asyncio.to_thread(self.system_monitor.get_snapshot),
        )
        text = format_overview(
            services,
            self.monitor.project_name,
            projects,
            snapshot,
            datetime.now(self.monitor.timezone),
        )
        keyboard = build_inline_actions(
            [
                [
                    ("🧩 Сервисы", CallbackAction.SERVICE_LIST, "-"),
                    ("📈 Ресурсы", CallbackAction.RESOURCES, "-"),
                ],
                [
                    ("🐳 Контейнеры", CallbackAction.CONTAINER_LIST, "-"),
                    ("🗄️ Бекапы", CallbackAction.BACKUP, "-"),
                ],
                [
                    ("⌨️ Команда", CallbackAction.COMMAND, "-"),
                    ("⚙️ Система", CallbackAction.SYSTEM, "-"),
                ],
                [("🔄 Обновить данные", CallbackAction.REFRESH, "-")],
            ]
        )
        return text, keyboard

    async def _render_resources(self, session: SessionState, view: ViewState):
        snapshot, stats = await asyncio.gather(
            asyncio.to_thread(self.system_monitor.get_snapshot),
            asyncio.to_thread(self.monitor.get_service_stats),
        )
        return format_resources(snapshot, stats), self._refresh_back_keyboard()

    async def _render_services(self, session: SessionState, view: ViewState):
        services = await asyncio.to_thread(self.monitor.list_services)
        items = []
        for service in services:
            token = session.tokens.register(("service", service.project_name, service.name))
            items.append(
                (
                    f"{service_level_emoji(service)} {service.name} ({service.running_count}/{service.total_count})",
                    token,
                )
            )
        keyboard, page, total = build_paginated_inline_menu(
            items,
            item_action=CallbackAction.SERVICE_OPEN,
            list_action=CallbackAction.SERVICE_LIST,
            page=view.page,
        )
        session.navigation.open("services", page=page, remember=False)
        if items:
            text = f"🧩 <b>Сервисы</b>\n\nВсего: {len(items)} · Страница: {page + 1}/{total}"
        else:
            text = "🧩 <b>Сервисы</b>\n\nСервисы не найдены. Проверь Docker и нажми «Обновить данные»."
        return text, keyboard

    async def _render_service(self, session: SessionState, view: ViewState):
        payload = self._require_payload(session, view.payload, "service")
        service = await asyncio.to_thread(self.monitor.get_service_by_ref, payload[1], payload[2])
        entity_token = session.tokens.register(("service", service.project_name, service.name))
        return format_service_details(service), build_inline_actions(
            [
                [
                    ("📄 Логи", CallbackAction.LOGS, entity_token),
                    ("📊 Статистика", CallbackAction.STATS, entity_token),
                ],
                [("🐳 Контейнеры сервиса", CallbackAction.CONTAINER_LIST, entity_token)],
                [
                    ("🔄 Обновить данные", CallbackAction.REFRESH, "-"),
                    (ACTION_BACK, CallbackAction.BACK, "-"),
                ],
            ]
        )

    async def _render_containers(self, session: SessionState, view: ViewState):
        containers = await asyncio.to_thread(self.monitor.list_containers)
        if view.payload:
            service_ref = self._require_payload(session, view.payload, "service")
            containers = [
                item
                for item in containers
                if item.project_name == service_ref[1] and item.service_name == service_ref[2]
            ]
        items = []
        for container in containers:
            token = session.tokens.register(("container", container.id))
            items.append((f"{status_emoji(container.status)} {container.name}", token))
        keyboard, page, total = build_paginated_inline_menu(
            items,
            item_action=CallbackAction.CONTAINER_OPEN,
            list_action=CallbackAction.CONTAINER_LIST,
            page=view.page,
            list_token=view.payload or "-",
        )
        session.navigation.open("containers", page=page, payload=view.payload, remember=False)
        if items:
            text = f"🐳 <b>Контейнеры</b>\n\nВсего: {len(items)} · Страница: {page + 1}/{total}"
        else:
            text = "🐳 <b>Контейнеры</b>\n\nКонтейнеры не найдены. Проверь фильтр и обнови данные."
        return text, keyboard

    async def _render_container(self, session: SessionState, view: ViewState):
        payload = self._require_payload(session, view.payload, "container")
        container = await asyncio.to_thread(self.monitor.get_container, payload[1])
        entity_token = session.tokens.register(("container", container.id))
        return format_container_details(container), build_inline_actions(
            [
                [
                    ("📄 Логи", CallbackAction.LOGS, entity_token),
                    ("📊 Статистика", CallbackAction.STATS, entity_token),
                ],
                [("♻️ Перезапустить", CallbackAction.RESTART, entity_token)],
                [
                    ("🔄 Обновить данные", CallbackAction.REFRESH, "-"),
                    (ACTION_BACK, CallbackAction.BACK, "-"),
                ],
            ]
        )

    async def _render_stats(self, session: SessionState, view: ViewState):
        payload = self._require_entity_payload(session, view.payload)
        if payload[0] == "service":
            stats = await asyncio.to_thread(self.monitor.get_service_stats_by_ref, payload[1], payload[2])
            text = format_stats(stats, service_name=payload[2])
        else:
            stats = [await asyncio.to_thread(self.monitor.get_container_stats, payload[1])]
            text = format_stats(stats, title="Статистика контейнера")
        return text, self._refresh_back_keyboard()

    async def _render_logs(self, session: SessionState, view: ViewState):
        payload = self._require_entity_payload(session, view.payload)
        tail = min(self.settings.default_logs_tail, self.settings.max_logs_tail)
        if payload[0] == "service":
            service, logs = await asyncio.to_thread(
                self.monitor.get_service_logs_by_ref,
                payload[1],
                payload[2],
                tail,
            )
            title = format_logs_caption(service.name, tail)
        else:
            container, logs = await asyncio.to_thread(self.monitor.get_container_logs, payload[1], tail)
            title = f"Логи контейнера {container.name}, последние {tail} строк"
        message_limit = min(max(self.settings.max_inline_log_chars, 500), 4096)
        return format_preformatted_message(title, logs, limit=message_limit), self._refresh_back_keyboard()

    async def _render_backup(self, session: SessionState, view: ViewState):
        return "🗄️ <b>Бекапы</b>\n\nСоздание, скачивание и удаление архивов.", build_inline_actions(
            [
                [("➕ Создать бекап", CallbackAction.BACKUP_CREATE, "-")],
                [("📦 Список архивов", CallbackAction.BACKUP_LIST, "-")],
                [(ACTION_BACK, CallbackAction.BACK, "-")],
            ]
        )

    async def _render_backups(self, session: SessionState, view: ViewState):
        archives = await asyncio.to_thread(
            list_backup_archives,
            target_dir=self.settings.backup_target_dir,
            timezone_info=self.monitor.timezone,
        )
        items = []
        for archive in archives:
            token = session.tokens.register(("backup", archive.name))
            items.append((f"📦 {archive.name} · {format_bytes(archive.size_bytes)}", token))
        keyboard, page, total = build_paginated_inline_menu(
            items,
            item_action=CallbackAction.BACKUP_OPEN,
            list_action=CallbackAction.BACKUP_LIST,
            page=view.page,
        )
        session.navigation.open("backups", page=page, remember=False)
        if items:
            text = f"📦 <b>Архивы</b>\n\nВсего: {len(items)} · Страница: {page + 1}/{total}"
        else:
            text = "📦 <b>Архивы</b>\n\nБекапов пока нет. Вернись назад и создай первый архив."
        return text, keyboard

    async def _render_backup_detail(self, session: SessionState, view: ViewState):
        payload = self._require_payload(session, view.payload, "backup")
        archive = await asyncio.to_thread(
            find_backup_archive,
            payload[1],
            target_dir=self.settings.backup_target_dir,
            timezone_info=self.monitor.timezone,
        )
        token = session.tokens.register(("backup", archive.name))
        text = (
            "📦 <b>Архив</b>\n\n"
            f"<b>Имя:</b> <code>{html.escape(archive.name)}</code>\n"
            f"<b>Размер:</b> {format_bytes(archive.size_bytes)}\n"
            f"<b>Создан:</b> {html.escape(format_datetime(archive.modified_at))}"
        )
        return text, build_inline_actions(
            [
                [
                    ("⬇️ Скачать", CallbackAction.BACKUP_DOWNLOAD, token),
                    ("🗑️ Удалить", CallbackAction.BACKUP_DELETE, token),
                ],
                [
                    ("🔄 Обновить данные", CallbackAction.REFRESH, "-"),
                    (ACTION_BACK, CallbackAction.BACK, "-"),
                ],
            ]
        )

    async def _render_system(self, session: SessionState, view: ViewState):
        return "⚙️ <b>Система</b>\n\nДиагностика и обслуживание бота.", build_inline_actions(
            [
                [
                    ("ℹ️ О боте", CallbackAction.ABOUT, "-"),
                    ("🔐 Ошибки входа", CallbackAction.FAILED_LOGINS, "-"),
                ],
                [("🧹 Очистка", CallbackAction.CLEANUP, "-")],
                [(ACTION_BACK, CallbackAction.BACK, "-")],
            ]
        )

    async def _render_about(self, session: SessionState, view: ViewState):
        rss = self._read_process_rss()
        text = (
            "ℹ️ <b>О боте</b>\n\n"
            f"<b>Версия:</b> {html.escape(self.settings.bot_version)}\n"
            f"<b>Python:</b> {html.escape(sys.version.split()[0])}\n"
            f"<b>PID:</b> {os.getpid()}\n"
            f"<b>RSS:</b> {format_bytes(rss) if rss is not None else 'нет данных'}\n"
            f"<b>Активных сессий:</b> {len(self.sessions)}"
        )
        return text, self._refresh_back_keyboard()

    async def _render_failed_logins(self, session: SessionState, view: ViewState):
        if self.login_monitor is None:
            text = "🔐 <b>Ошибки входа</b>\n\nМониторинг входов отключён."
        else:
            events = await asyncio.to_thread(self.login_monitor.list_failed_login_events, limit=20)
            lines = ["🔐 <b>Ошибки входа</b>", ""]
            if not events:
                lines.append("События не найдены.")
            for event in events:
                lines.append(
                    f"• {html.escape(format_datetime(event.happened_at))} — "
                    f"{html.escape(event.user_name or 'неизвестно')} · {html.escape(event.source or 'без IP')}"
                )
            text = "\n".join(lines)
        return text, self._refresh_back_keyboard()

    async def _render_command(self, session: SessionState, view: ViewState):
        session.input_mode = "command"
        text = (
            "⌨️ <b>Команда на хосте</b>\n\n"
            "Отправь команду следующим сообщением. Выполнение начнётся только после подтверждения."
        )
        return text, build_inline_actions([[(ACTION_CANCEL, CallbackAction.CANCEL, "-")]])

    async def _render_confirm(self, session: SessionState, view: ViewState):
        payload = self._require_confirmation(session, view.payload)
        if payload[0] == "restart":
            container = await asyncio.to_thread(self.monitor.get_container, payload[1])
            question = (
                f"Перезапустить контейнер <code>{html.escape(container.name)}</code>?\n"
                "Сервис может быть кратковременно недоступен."
            )
            button = "✅ Перезапустить"
        elif payload[0] == "command":
            question = (
                f"Выполнить на хосте команду <code>{html.escape(payload[1])}</code>?\n"
                "Она может изменить состояние сервера."
            )
            button = "✅ Выполнить"
        elif payload[0] == "backup_create":
            question = (
                f"Создать бекап <code>{html.escape(self.settings.backup_source_dir)}</code> "
                f"в <code>{html.escape(self.settings.backup_target_dir)}</code>?\n"
                "Операция займёт место на диске."
            )
            button = "✅ Создать"
        elif payload[0] == "backup_delete":
            question = (
                f"Удалить архив <code>{html.escape(payload[1])}</code>?\n"
                "Отменить удаление после подтверждения нельзя."
            )
            button = "🗑️ Удалить"
        else:
            question = (
                f"Очистить временные каталоги в <code>{html.escape(self.settings.cleanup_path)}</code>?\n"
                "Кеши и tmp-каталоги будут удалены без возможности отмены."
            )
            button = "🧹 Очистить"
        return f"⚠️ <b>Подтверждение</b>\n\n{question}", build_inline_confirm(
            confirm_text=button,
            token=view.payload or "-",
        )

    async def _download_backup(
        self,
        callback: CallbackQuery,
        session: SessionState,
        token: str,
    ) -> str:
        payload = self._require_payload(session, token, "backup")
        archive = await asyncio.to_thread(
            find_backup_archive,
            payload[1],
            target_dir=self.settings.backup_target_dir,
            timezone_info=self.monitor.timezone,
        )
        if archive.size_bytes > TELEGRAM_DOCUMENT_LIMIT_BYTES:
            return "Архив больше 50 МиБ. Скачай его по SCP/SFTP."
        await callback.bot.send_document(
            chat_id=session.key.chat_id,
            document=FSInputFile(archive.container_path, filename=archive.name),
            caption="Архив отправлен отдельным сообщением. Управление осталось на текущем экране.",
        )
        return "Архив отправлен."

    async def _execute_confirmation(
        self,
        callback: CallbackQuery,
        session: SessionState,
        token: str,
    ) -> str:
        payload = self._require_confirmation(session, token)
        operation_key = f"{payload[0]}:{payload[1:]}"
        if not session.try_start_operation(operation_key):
            return "Операция уже выполняется."

        try:
            await self._show_progress(callback, session, payload[0])
            result_text = await self._run_dangerous_operation(payload)
            session.navigation.back()
            await edit_or_send(
                bot=callback.bot,
                chat_id=session.key.chat_id,
                message=callback.message,
                text=result_text,
                reply_markup=build_inline_actions(
                    [
                        [("↩️ Вернуться", CallbackAction.REFRESH, "-")],
                        [("🏠 Главная", CallbackAction.HOME, "-")],
                    ]
                ),
            )
            return "Готово."
        finally:
            session.finish_operation(operation_key)

    async def _run_dangerous_operation(self, payload: tuple) -> str:
        operation = payload[0]
        if operation == "restart":
            container = await asyncio.to_thread(
                self.monitor.restart_container,
                payload[1],
                self.settings.restart_timeout_seconds,
            )
            return f"✅ Контейнер <code>{html.escape(container.name)}</code> перезапущен."
        if operation == "command":
            result = await asyncio.to_thread(self.command_executor.run, payload[1])
            return self._format_command_result(result)
        if operation == "backup_create":
            command = build_backup_command(
                datetime.now(self.monitor.timezone),
                source_dir=self.settings.backup_source_dir,
                target_dir=self.settings.backup_target_dir,
            )
            result = await asyncio.to_thread(
                self.command_executor.run,
                command.command,
                timeout_seconds=self.settings.backup_timeout_seconds,
            )
            return self._format_command_result(result, title="Создание бекапа")
        if operation == "backup_delete":
            command = build_delete_backup_command(payload[1], target_dir=self.settings.backup_target_dir)
            result = await asyncio.to_thread(
                self.command_executor.run,
                command.command,
                timeout_seconds=self.settings.backup_timeout_seconds,
            )
            return self._format_command_result(result, title="Удаление бекапа")
        if operation == "cleanup":
            command = build_cleanup_command(self.settings.cleanup_path)
            result = await asyncio.to_thread(
                self.command_executor.run,
                command.command,
                timeout_seconds=self.settings.cleanup_timeout_seconds,
            )
            return self._format_command_result(result, title="Очистка")
        raise ValueError("Неизвестная операция")

    async def _show_progress(
        self,
        callback: CallbackQuery,
        session: SessionState,
        operation: str,
    ) -> None:
        labels = {
            "restart": "Перезапускаю контейнер…",
            "command": "Выполняю команду…",
            "backup_create": "Создаю бекап…",
            "backup_delete": "Удаляю бекап…",
            "cleanup": "Выполняю очистку…",
        }
        await edit_or_send(
            bot=callback.bot,
            chat_id=session.key.chat_id,
            message=callback.message,
            text=f"⏳ {labels[operation]}",
        )

    async def _render_error(self, callback: CallbackQuery, session: SessionState) -> None:
        await edit_or_send(
            bot=callback.bot,
            chat_id=session.key.chat_id,
            message=callback.message,
            text="❌ Не удалось обновить экран. Повтори попытку.",
            reply_markup=self._refresh_back_keyboard(),
        )

    def _open_confirmation(self, session: SessionState, payload: tuple) -> ViewState:
        token = session.tokens.register(payload)
        return session.navigation.open("confirm", payload=token)

    def _require_confirmation(self, session: SessionState, token: str | None) -> tuple:
        payload = session.tokens.resolve(token or "")
        allowed = {"restart", "command", "backup_create", "backup_delete", "cleanup"}
        if not isinstance(payload, tuple) or not payload or payload[0] not in allowed:
            raise LookupError("Подтверждение устарело")
        return payload

    def _require_entity_payload(self, session: SessionState, token: str | None) -> tuple:
        payload = session.tokens.resolve(token or "")
        if not isinstance(payload, tuple) or not payload or payload[0] not in {"service", "container"}:
            raise LookupError("Объект устарел")
        return payload

    def _require_payload(
        self,
        session: SessionState,
        token: str | None,
        expected_type: str,
    ) -> tuple:
        payload = session.tokens.resolve(token or "")
        if not isinstance(payload, tuple) or not payload or payload[0] != expected_type:
            raise LookupError("Объект устарел")
        return payload

    @staticmethod
    def _parse_action(value: str) -> CallbackAction | None:
        try:
            return CallbackAction(value)
        except ValueError:
            return None

    @staticmethod
    def _refresh_back_keyboard():
        return build_inline_actions(
            [
                [
                    ("🔄 Обновить данные", CallbackAction.REFRESH, "-"),
                    (ACTION_BACK, CallbackAction.BACK, "-"),
                ]
            ]
        )

    @staticmethod
    def _format_command_result(result: HostCommandResult, *, title: str = "Команда") -> str:
        state = "✅ Выполнено" if result.exit_code == 0 else f"❌ Код выхода: {result.exit_code}"
        return format_preformatted_message(
            f"{title} — {state}",
            f"Время: {result.duration_seconds:.1f} с\n\n{result.output}",
        )

    @staticmethod
    def _read_process_rss() -> int | None:
        try:
            with open("/proc/self/status", encoding="utf-8") as status_file:
                for line in status_file:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) * 1024
        except OSError:
            return None
        return None
