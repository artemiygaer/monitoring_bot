from __future__ import annotations

import unittest

from app.cache import TTLCache


class TTLCacheTests(unittest.TestCase):
    def test_loader_runs_once_inside_ttl(self) -> None:
        cache: TTLCache[str, object] = TTLCache(60)
        calls = 0

        def loader() -> object:
            nonlocal calls
            calls += 1
            return object()

        first = cache.get_or_create("key", loader)
        second = cache.get_or_create("key", loader)

        self.assertIs(first, second)
        self.assertEqual(1, calls)

    def test_invalidate_forces_reload(self) -> None:
        cache: TTLCache[str, int] = TTLCache(60)
        calls = 0

        def loader() -> int:
            nonlocal calls
            calls += 1
            return calls

        self.assertEqual(1, cache.get_or_create("key", loader))
        cache.invalidate("key")
        self.assertEqual(2, cache.get_or_create("key", loader))
