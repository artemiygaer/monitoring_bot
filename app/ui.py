from __future__ import annotations

from contextlib import suppress

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message


async def edit_or_send(
    *,
    bot,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    message: Message | None = None,
) -> Message:
    """Редактирует текущий экран или безопасно отправляет новый."""

    if message is not None:
        try:
            await message.edit_text(text, reply_markup=reply_markup)
            return message
        except TelegramBadRequest as error:
            if "message is not modified" in str(error).lower():
                return message

    return await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)


async def answer_callback(
    callback: CallbackQuery,
    text: str | None = None,
    *,
    show_alert: bool = False,
) -> None:
    """Всегда завершает индикатор callback, игнорируя устаревший запрос."""

    with suppress(TelegramBadRequest):
        await callback.answer(text=text, show_alert=show_alert)
