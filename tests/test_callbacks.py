from __future__ import annotations

import unittest

from app.callbacks import BotCallback, CallbackAction, pack_callback
from app.sessions import TokenRegistry


class CallbackTests(unittest.TestCase):
    def test_packed_callback_fits_telegram_limit(self) -> None:
        registry = TokenRegistry(ttl_seconds=60)
        long_name = "сервис-" + "очень-длинное-имя-" * 20
        token = registry.register(("service", long_name))

        packed = pack_callback(CallbackAction.SERVICE_OPEN, token=token, page=123)
        unpacked = BotCallback.unpack(packed)

        self.assertLessEqual(len(packed.encode("utf-8")), 64)
        self.assertNotIn(long_name, packed)
        self.assertEqual(token, unpacked.token)
        self.assertEqual(123, unpacked.page)

    def test_negative_page_is_normalized(self) -> None:
        packed = pack_callback(CallbackAction.SERVICE_LIST, page=-10)

        self.assertEqual(0, BotCallback.unpack(packed).page)
