from __future__ import annotations

import asyncio
import unittest

from aiogram.exceptions import TelegramBadRequest

from app.ui import answer_callback, edit_or_send


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str, object]] = []

    async def send_message(self, *, chat_id: int, text: str, reply_markup=None):
        message = FakeMessage()
        message.text = text
        self.sent.append((chat_id, text, reply_markup))
        return message


class FakeMessage:
    def __init__(self, error: str | None = None) -> None:
        self.error = error
        self.edits: list[tuple[str, object]] = []
        self.text = ""

    async def edit_text(self, text: str, reply_markup=None) -> None:
        if self.error is not None:
            raise TelegramBadRequest(method=None, message=self.error)
        self.edits.append((text, reply_markup))


class FakeCallback:
    def __init__(self, error: str | None = None) -> None:
        self.error = error
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(self, text: str | None = None, show_alert: bool = False) -> None:
        if self.error is not None:
            raise TelegramBadRequest(method=None, message=self.error)
        self.answers.append((text, show_alert))


class EditOrSendTests(unittest.TestCase):
    def test_successful_edit_reuses_message(self) -> None:
        bot = FakeBot()
        message = FakeMessage()

        result = asyncio.run(
            edit_or_send(bot=bot, chat_id=1, text="Экран", message=message)
        )

        self.assertIs(message, result)
        self.assertEqual([("Экран", None)], message.edits)
        self.assertEqual([], bot.sent)

    def test_not_modified_reuses_message(self) -> None:
        bot = FakeBot()
        message = FakeMessage("message is not modified")

        result = asyncio.run(
            edit_or_send(bot=bot, chat_id=1, text="Экран", message=message)
        )

        self.assertIs(message, result)
        self.assertEqual([], bot.sent)

    def test_stale_message_falls_back_to_send(self) -> None:
        bot = FakeBot()
        message = FakeMessage("message to edit not found")

        result = asyncio.run(
            edit_or_send(bot=bot, chat_id=1, text="Новый экран", message=message)
        )

        self.assertIsNot(message, result)
        self.assertEqual(1, len(bot.sent))

    def test_missing_message_sends_new(self) -> None:
        bot = FakeBot()

        asyncio.run(edit_or_send(bot=bot, chat_id=1, text="Новый экран"))

        self.assertEqual([(1, "Новый экран", None)], bot.sent)

    def test_callback_answer_is_always_attempted(self) -> None:
        callback = FakeCallback()

        asyncio.run(answer_callback(callback, "Готово"))

        self.assertEqual([("Готово", False)], callback.answers)

    def test_stale_callback_answer_is_safely_ignored(self) -> None:
        callback = FakeCallback("query is too old")

        asyncio.run(answer_callback(callback))
