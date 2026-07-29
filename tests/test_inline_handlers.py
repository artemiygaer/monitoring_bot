from __future__ import annotations

import unittest
from datetime import timezone
from types import SimpleNamespace
from unittest import mock

from app.callbacks import BotCallback, CallbackAction
from app.inline_handlers import InlineController
from app.sessions import SessionStore


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return SimpleNamespace(message_id=10)


class InlineHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.controller = InlineController.__new__(InlineController)
        self.controller.sessions = SessionStore()
        self.bot = FakeBot()
        self.message = SimpleNamespace(
            chat=SimpleNamespace(id=100),
            from_user=SimpleNamespace(id=7),
            text="uname -a",
            bot=self.bot,
        )

    async def test_text_is_not_command_without_explicit_mode(self) -> None:
        accepted = await self.controller.accept_command_text(self.message)

        self.assertFalse(accepted)
        self.assertEqual([], self.bot.sent)

    async def test_empty_command_keeps_explicit_input_mode(self) -> None:
        session = self.controller.get_session(self.message)
        session.input_mode = "command"
        self.message.text = "   "

        accepted = await self.controller.accept_command_text(self.message)

        self.assertTrue(accepted)
        self.assertEqual("command", session.input_mode)
        self.assertEqual([], self.bot.sent)

    async def test_overlong_command_is_rejected_before_confirmation(self) -> None:
        session = self.controller.get_session(self.message)
        session.input_mode = "command"
        self.message.text = "x" * 1001

        accepted = await self.controller.accept_command_text(self.message)

        self.assertTrue(accepted)
        self.assertEqual("command", session.input_mode)
        self.assertIn("слишком длинная", self.bot.sent[0]["text"])
        self.assertEqual("home", session.navigation.current.screen)

    async def test_explicit_command_mode_opens_confirm_cancel_screen(self) -> None:
        session = self.controller.get_session(self.message)
        session.input_mode = "command"

        accepted = await self.controller.accept_command_text(self.message)

        self.assertTrue(accepted)
        self.assertIsNone(session.input_mode)
        self.assertEqual("confirm", session.navigation.current.screen)
        markup = self.bot.sent[0]["reply_markup"]
        actions = {
            BotCallback.unpack(button.callback_data).action
            for row in markup.inline_keyboard
            for button in row
        }
        self.assertEqual(
            {CallbackAction.CONFIRM.value, CallbackAction.CANCEL.value},
            actions,
        )
        confirmation_text = self.bot.sent[0]["text"]
        self.assertIn("uname -a", confirmation_text)
        self.assertIn("может изменить", confirmation_text)
        self.assertNotIn("`", confirmation_text)

    def test_route_table_contains_all_dangerous_operations(self) -> None:
        operations = {"restart", "command", "backup_create", "backup_delete", "cleanup"}
        session = self.controller.get_session(self.message)

        for operation in operations:
            token = session.tokens.register((operation,))
            self.assertEqual(operation, self.controller._require_confirmation(session, token)[0])

    async def test_large_backup_is_not_sent_to_telegram(self) -> None:
        session = self.controller.get_session(self.message)
        token = session.tokens.register(("backup", "root-backup-20260729-120000.tar.gz"))
        self.controller.settings = SimpleNamespace(backup_target_dir="/backup")
        self.controller.monitor = SimpleNamespace(timezone=timezone.utc)
        archive = SimpleNamespace(size_bytes=51 * 1024 * 1024)
        callback = SimpleNamespace(bot=self.bot)

        with mock.patch("app.inline_handlers.find_backup_archive", return_value=archive):
            notice = await self.controller._download_backup(callback, session, token)

        self.assertIn("больше 50 МиБ", notice)
        self.assertEqual([], self.bot.sent)
