from __future__ import annotations

from enum import Enum

from aiogram.filters.callback_data import CallbackData


TELEGRAM_CALLBACK_LIMIT_BYTES = 64


class CallbackAction(str, Enum):
    HOME = "h"
    RESOURCES = "rs"
    REFRESH = "r"
    BACK = "b"
    PAGE = "p"
    SERVICE_LIST = "sl"
    SERVICE_OPEN = "so"
    CONTAINER_LIST = "cl"
    CONTAINER_OPEN = "co"
    LOGS = "lg"
    STATS = "st"
    BACKUP = "bk"
    BACKUP_LIST = "bl"
    BACKUP_OPEN = "bo"
    BACKUP_CREATE = "bc"
    BACKUP_DOWNLOAD = "bd"
    BACKUP_DELETE = "bx"
    SYSTEM = "sy"
    ABOUT = "ab"
    FAILED_LOGINS = "fl"
    CLEANUP = "cu"
    COMMAND = "cm"
    RESTART = "rr"
    CONFIRM = "cf"
    CANCEL = "cx"


class BotCallback(CallbackData, prefix="mb"):
    action: str
    token: str = "-"
    page: int = 0


def pack_callback(
    action: CallbackAction | str,
    *,
    token: str = "-",
    page: int = 0,
) -> str:
    """Упаковывает callback и проверяет ограничение Telegram в байтах."""

    action_value = action.value if isinstance(action, CallbackAction) else action
    packed = BotCallback(action=action_value, token=token or "-", page=max(page, 0)).pack()
    if len(packed.encode("utf-8")) > TELEGRAM_CALLBACK_LIMIT_BYTES:
        raise ValueError("Callback data превышает лимит Telegram 64 байта")
    return packed
