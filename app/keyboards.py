from __future__ import annotations

from math import ceil

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.callbacks import CallbackAction, pack_callback


MENU_OVERVIEW = "📊 Сводка"
MENU_RESOURCES = "📈 Ресурсы"
MENU_CONTAINERS = "🐳 Контейнеры"
MENU_COMMANDS = "⌨️ Команды"
MENU_BACKUP = "🗄️ Бекап"
MENU_FAILED_LOGINS = "🔐 Ошибки входа"
MENU_CLEANUP = "🧹 Очистка"
MENU_ABOUT = "ℹ️ О боте"
MENU_SYSTEM = "⚙️ Система"
MENU_REFRESH = "🔄 Обновить данные"

ACTION_BACK = "⬅️ Назад"
ACTION_CANCEL = "❌ Отмена"
ACTION_CLEAR_CHAT = "🧹 Очистить чат"
ACTION_ALL_CONTAINERS = "Все контейнеры"
ACTION_SERVICE_CONTAINERS = "Контейнеры сервиса"
ACTION_SERVICE_LOGS = "Логи сервиса"
ACTION_SERVICE_STATS = "Статистика сервиса"
ACTION_CONTAINER_LOGS = "Логи контейнера"
ACTION_CONTAINER_STATS = "Статистика контейнера"
ACTION_RESTART_CONTAINER = "Перезапустить контейнер"
ACTION_CONFIRM_RESTART = "Подтвердить перезапуск"
ACTION_CONFIRM_COMMAND = "Выполнить команду"
ACTION_CREATE_BACKUP = "Создать новый бекап"
ACTION_DOWNLOAD_BACKUP = "Скачать бекап"
ACTION_DELETE_BACKUP = "Удалить бекап"
ACTION_CONFIRM_BACKUP = "Создать бекап"
ACTION_CONFIRM_DELETE_BACKUP = "Подтвердить удаление"
ACTION_CONFIRM_CLEANUP = "Подтвердить очистку"

ACTION_LOG_TAIL_10 = "10 строк"
ACTION_LOG_TAIL_20 = "20 строк"
ACTION_LOG_TAIL_40 = "40 строк"

LOG_TAIL_BUTTONS = {
    ACTION_LOG_TAIL_10: 10,
    ACTION_LOG_TAIL_20: 20,
    ACTION_LOG_TAIL_40: 40,
}

INLINE_PAGE_SIZE = 8


def build_reply_menu(rows: list[list[str]], placeholder: str = "Выбери действие") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=text) for text in row] for row in rows],
        resize_keyboard=True,
        input_field_placeholder=placeholder,
    )


def build_paginated_inline_menu(
    items: list[tuple[str, str]],
    *,
    item_action: CallbackAction | str,
    list_action: CallbackAction | str,
    page: int = 0,
    page_size: int = INLINE_PAGE_SIZE,
    back_action: CallbackAction | str = CallbackAction.BACK,
    list_token: str = "-",
) -> tuple[InlineKeyboardMarkup, int, int]:
    """Строит ограниченный постраничный список контекстных кнопок."""

    safe_page_size = max(page_size, 1)
    total_pages = max(ceil(len(items) / safe_page_size), 1)
    safe_page = min(max(page, 0), total_pages - 1)
    start = safe_page * safe_page_size
    page_items = items[start : start + safe_page_size]

    builder = InlineKeyboardBuilder()
    for text, token in page_items:
        builder.row(
            InlineKeyboardButton(
                text=text,
                callback_data=pack_callback(item_action, token=token, page=safe_page),
            )
        )

    navigation: list[InlineKeyboardButton] = []
    if safe_page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="◀️",
                callback_data=pack_callback(list_action, token=list_token, page=safe_page - 1),
            )
        )
    navigation.append(
        InlineKeyboardButton(
            text=f"{safe_page + 1}/{total_pages}",
            callback_data=pack_callback(CallbackAction.PAGE, page=safe_page),
        )
    )
    if safe_page + 1 < total_pages:
        navigation.append(
            InlineKeyboardButton(
                text="▶️",
                callback_data=pack_callback(list_action, token=list_token, page=safe_page + 1),
            )
        )
    builder.row(*navigation)
    builder.row(
        InlineKeyboardButton(
            text="🔄 Обновить данные",
            callback_data=pack_callback(list_action, token=list_token, page=safe_page),
        ),
        InlineKeyboardButton(
            text=ACTION_BACK,
            callback_data=pack_callback(back_action),
        ),
    )
    return builder.as_markup(), safe_page, total_pages


def build_inline_actions(
    rows: list[list[tuple[str, CallbackAction | str, str]]],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for row in rows:
        builder.row(
            *[
                InlineKeyboardButton(
                    text=text,
                    callback_data=pack_callback(action, token=token),
                )
                for text, action, token in row
            ]
        )
    return builder.as_markup()


def build_inline_confirm(
    *,
    confirm_text: str,
    token: str,
    cancel_action: CallbackAction | str = CallbackAction.CANCEL,
) -> InlineKeyboardMarkup:
    return build_inline_actions(
        [
            [(confirm_text, CallbackAction.CONFIRM, token)],
            [(ACTION_CANCEL, cancel_action, "-")],
        ]
    )


def build_main_menu(include_clear_chat: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [MENU_OVERVIEW, MENU_RESOURCES],
        [MENU_CONTAINERS, MENU_BACKUP],
        [MENU_COMMANDS, MENU_SYSTEM],
        [MENU_REFRESH],
    ]
    return build_reply_menu(rows)


def build_system_menu(include_clear_chat: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [MENU_CLEANUP, MENU_FAILED_LOGINS],
        [MENU_ABOUT],
    ]
    if include_clear_chat:
        rows.append([ACTION_CLEAR_CHAT])
    rows.append([ACTION_BACK])
    return build_reply_menu(rows, placeholder="Системные функции")


def build_service_menu(options: list[str], include_clear_chat: bool = False) -> ReplyKeyboardMarkup:
    rows = [[option] for option in options]
    if include_clear_chat:
        rows.append([ACTION_CLEAR_CHAT])
    rows.append([MENU_REFRESH, ACTION_BACK])
    return build_reply_menu(rows, placeholder="Выбери сервис")


def build_container_menu(options: list[str], include_clear_chat: bool = False) -> ReplyKeyboardMarkup:
    rows = [[option] for option in options]
    if include_clear_chat:
        rows.append([ACTION_CLEAR_CHAT])
    rows.append([MENU_REFRESH, ACTION_BACK])
    return build_reply_menu(rows, placeholder="Выбери контейнер")


def build_service_detail_menu(include_clear_chat: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [ACTION_SERVICE_LOGS, ACTION_SERVICE_STATS],
        [ACTION_SERVICE_CONTAINERS],
    ]
    if include_clear_chat:
        rows.append([ACTION_CLEAR_CHAT])
    rows.append([MENU_REFRESH, ACTION_BACK])
    return build_reply_menu(rows, placeholder="Действия с сервисом")


def build_container_detail_menu(include_clear_chat: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [ACTION_CONTAINER_LOGS, ACTION_CONTAINER_STATS],
        [ACTION_RESTART_CONTAINER],
    ]
    if include_clear_chat:
        rows.append([ACTION_CLEAR_CHAT])
    rows.append([MENU_REFRESH, ACTION_BACK])
    return build_reply_menu(rows, placeholder="Действия с контейнером")


def build_restart_confirm_menu(include_clear_chat: bool = False) -> ReplyKeyboardMarkup:
    rows = [[ACTION_CONFIRM_RESTART, ACTION_CANCEL]]
    if include_clear_chat:
        rows.append([ACTION_CLEAR_CHAT])
    rows.append([ACTION_BACK])
    return build_reply_menu(rows, placeholder="Подтверди перезапуск")


def build_stats_menu(options: list[str], include_clear_chat: bool = False) -> ReplyKeyboardMarkup:
    rows = [[option] for option in options]
    if include_clear_chat:
        rows.append([ACTION_CLEAR_CHAT])
    rows.append([MENU_REFRESH, ACTION_BACK])
    return build_reply_menu(rows, placeholder="Выбери сервис для статистики")


def build_logs_source_menu(options: list[str], include_clear_chat: bool = False) -> ReplyKeyboardMarkup:
    rows = [[ACTION_ALL_CONTAINERS]]
    rows.extend([[option] for option in options])
    if include_clear_chat:
        rows.append([ACTION_CLEAR_CHAT])
    rows.append([MENU_REFRESH, ACTION_BACK])
    return build_reply_menu(rows, placeholder="Выбери источник логов")


def build_log_tail_menu(include_clear_chat: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [ACTION_LOG_TAIL_10, ACTION_LOG_TAIL_20, ACTION_LOG_TAIL_40],
    ]
    if include_clear_chat:
        rows.append([ACTION_CLEAR_CHAT])
    rows.append([MENU_REFRESH, ACTION_BACK])
    return build_reply_menu(rows, placeholder="Выбери объём логов")


def build_detail_menu(include_clear_chat: bool = False) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_clear_chat:
        rows.append([ACTION_CLEAR_CHAT])
    rows.append([MENU_REFRESH, ACTION_BACK])
    return build_reply_menu(rows)


def build_commands_input_menu(include_clear_chat: bool = False) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if include_clear_chat:
        rows.append([ACTION_CLEAR_CHAT])
    rows.append([ACTION_BACK])
    return build_reply_menu(rows, placeholder="Введи команду для сервера")


def build_command_confirm_menu(include_clear_chat: bool = False) -> ReplyKeyboardMarkup:
    rows = [[ACTION_CONFIRM_COMMAND, ACTION_CANCEL]]
    if include_clear_chat:
        rows.append([ACTION_CLEAR_CHAT])
    rows.append([ACTION_BACK])
    return build_reply_menu(rows, placeholder="Подтверди выполнение команды")


def build_backup_menu(include_clear_chat: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [ACTION_CREATE_BACKUP],
        [ACTION_DOWNLOAD_BACKUP, ACTION_DELETE_BACKUP],
    ]
    if include_clear_chat:
        rows.append([ACTION_CLEAR_CHAT])
    rows.append([MENU_REFRESH, ACTION_BACK])
    return build_reply_menu(rows, placeholder="Выбери действие с бекапами")


def build_backup_archive_menu(options: list[str], include_clear_chat: bool = False) -> ReplyKeyboardMarkup:
    rows = [[option] for option in options]
    if include_clear_chat:
        rows.append([ACTION_CLEAR_CHAT])
    rows.append([MENU_REFRESH, ACTION_BACK])
    return build_reply_menu(rows, placeholder="Выбери архив")


def build_backup_confirm_menu(include_clear_chat: bool = False) -> ReplyKeyboardMarkup:
    rows = [[ACTION_CONFIRM_BACKUP, ACTION_CANCEL]]
    if include_clear_chat:
        rows.append([ACTION_CLEAR_CHAT])
    rows.append([ACTION_BACK])
    return build_reply_menu(rows, placeholder="Подтверди создание бекапа")


def build_backup_delete_confirm_menu(include_clear_chat: bool = False) -> ReplyKeyboardMarkup:
    rows = [[ACTION_CONFIRM_DELETE_BACKUP, ACTION_CANCEL]]
    if include_clear_chat:
        rows.append([ACTION_CLEAR_CHAT])
    rows.append([ACTION_BACK])
    return build_reply_menu(rows, placeholder="Подтверди удаление бекапа")


def build_cleanup_confirm_menu(include_clear_chat: bool = False) -> ReplyKeyboardMarkup:
    rows = [[ACTION_CONFIRM_CLEANUP, ACTION_CANCEL]]
    if include_clear_chat:
        rows.append([ACTION_CLEAR_CHAT])
    rows.append([ACTION_BACK])
    return build_reply_menu(rows, placeholder="Подтверди очистку")
