from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


class FakeBaseMiddleware:
    pass


class FakeUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


class FakeMessage:
    def __init__(self) -> None:
        self.answers: list[tuple[str, bool]] = []

    async def answer(self, text: str, show_alert: bool = False) -> None:
        self.answers.append((text, show_alert))


class FakeCallbackQuery(FakeMessage):
    pass


def load_access_module():
    aiogram_module = types.ModuleType("aiogram")
    aiogram_module.BaseMiddleware = FakeBaseMiddleware
    aiogram_types = types.ModuleType("aiogram.types")
    aiogram_types.CallbackQuery = FakeCallbackQuery
    aiogram_types.Message = FakeMessage
    aiogram_types.TelegramObject = object

    module_name = "app._access_under_test"
    module_path = Path(__file__).parents[1] / "app" / "access.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Не удалось загрузить app/access.py")

    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(
        sys.modules,
        {"aiogram": aiogram_module, "aiogram.types": aiogram_types},
    ):
        spec.loader.exec_module(module)
    return module


class AccessMiddlewareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_access_module()

    def test_allowed_user_reaches_handler(self) -> None:
        middleware = self.module.AccessMiddleware(frozenset({42}))
        event = FakeMessage()
        calls: list[object] = []

        async def handler(current_event, data):
            calls.append(current_event)
            return "ok"

        result = asyncio.run(
            middleware(handler, event, {"event_from_user": FakeUser(42)})
        )

        self.assertEqual("ok", result)
        self.assertEqual([event], calls)
        self.assertEqual([], event.answers)

    def test_denied_message_gets_safe_error(self) -> None:
        middleware = self.module.AccessMiddleware(frozenset({42}))
        event = FakeMessage()

        async def handler(current_event, data):
            raise AssertionError("Обработчик не должен вызываться")

        result = asyncio.run(
            middleware(handler, event, {"event_from_user": FakeUser(7)})
        )

        self.assertIsNone(result)
        self.assertEqual(
            [("Доступ запрещён. Передай администратору свой Telegram ID: 7.", False)],
            event.answers,
        )

    def test_denied_callback_gets_alert(self) -> None:
        middleware = self.module.AccessMiddleware(frozenset({42}))
        event = FakeCallbackQuery()

        async def handler(current_event, data):
            raise AssertionError("Обработчик не должен вызываться")

        result = asyncio.run(
            middleware(handler, event, {"event_from_user": FakeUser(7)})
        )

        self.assertIsNone(result)
        self.assertEqual(
            [("Доступ запрещён. Обратись к администратору.", True)],
            event.answers,
        )
