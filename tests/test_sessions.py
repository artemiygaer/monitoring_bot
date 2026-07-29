from __future__ import annotations

import unittest

from app.sessions import SessionStore, TokenRegistry


class MutableClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class SessionTests(unittest.TestCase):
    def test_users_in_same_chat_have_independent_sessions(self) -> None:
        store = SessionStore()

        first = store.get(chat_id=100, user_id=1)
        second = store.get(chat_id=100, user_id=2)
        first.screen = "containers"

        self.assertIsNot(first, second)
        self.assertEqual("home", second.screen)
        self.assertEqual(2, len(store))

    def test_session_and_tokens_expire_by_ttl(self) -> None:
        clock = MutableClock()
        store = SessionStore(
            ttl_seconds=10,
            token_ttl_seconds=5,
            clock=clock,
        )
        session = store.get(chat_id=100, user_id=1)
        token = session.tokens.register("payload")
        self.assertEqual("payload", session.tokens.resolve(token))

        clock.value = 6
        self.assertIsNone(session.tokens.resolve(token))
        clock.value = 11
        store.cleanup()
        self.assertEqual(0, len(store))

    def test_registry_has_hard_limit(self) -> None:
        registry = TokenRegistry(ttl_seconds=60, max_entries=2)

        registry.register("one")
        registry.register("two")
        registry.register("three")

        self.assertEqual(2, len(registry))

    def test_operation_lock_rejects_duplicate(self) -> None:
        session = SessionStore().get(chat_id=100, user_id=1)

        self.assertTrue(session.try_start_operation("backup"))
        self.assertFalse(session.try_start_operation("backup"))
        session.finish_operation("backup")
        self.assertTrue(session.try_start_operation("backup"))
