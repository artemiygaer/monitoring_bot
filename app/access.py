from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class AccessMiddleware(BaseMiddleware):
    def __init__(self, allowed_user_ids: frozenset[int]) -> None:
        self.allowed_user_ids = allowed_user_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.id in self.allowed_user_ids:
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer("Доступ запрещён. Обратись к администратору.", show_alert=True)
            return None

        if isinstance(event, Message):
            await event.answer(
                f"Доступ запрещён. Передай администратору свой Telegram ID: {user.id}."
            )
            return None

        return None
