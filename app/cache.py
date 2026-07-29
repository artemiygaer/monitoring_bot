from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from time import monotonic
from typing import Generic, TypeVar


KeyT = TypeVar("KeyT")
ValueT = TypeVar("ValueT")


class TTLCache(Generic[KeyT, ValueT]):
    """Небольшой потокобезопасный кеш с монотонным TTL."""

    def __init__(self, ttl_seconds: float) -> None:
        self.ttl_seconds = max(float(ttl_seconds), 0.0)
        self._values: dict[KeyT, tuple[float, ValueT]] = {}
        self._lock = RLock()

    def get_or_create(self, key: KeyT, loader: Callable[[], ValueT]) -> ValueT:
        now = monotonic()
        with self._lock:
            cached = self._values.get(key)
            if cached is not None and cached[0] > now:
                return cached[1]

            value = loader()
            self._values[key] = (monotonic() + self.ttl_seconds, value)
            return value

    def invalidate(self, key: KeyT | None = None) -> None:
        with self._lock:
            if key is None:
                self._values.clear()
            else:
                self._values.pop(key, None)
