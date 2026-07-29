from __future__ import annotations

import secrets
from collections import OrderedDict
from dataclasses import dataclass, field
from time import monotonic
from typing import Callable

from app.navigation import NavigationHistory


@dataclass(frozen=True, slots=True)
class SessionKey:
    chat_id: int
    user_id: int


@dataclass(slots=True)
class TokenEntry:
    expires_at: float
    payload: object


class TokenRegistry:
    def __init__(
        self,
        *,
        ttl_seconds: int = 3600,
        max_entries: int = 128,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.ttl_seconds = max(ttl_seconds, 1)
        self.max_entries = max(max_entries, 1)
        self.clock = clock
        self._entries: OrderedDict[str, TokenEntry] = OrderedDict()

    def register(self, payload: object) -> str:
        self.cleanup()
        while len(self._entries) >= self.max_entries:
            self._entries.popitem(last=False)

        token = secrets.token_urlsafe(6)[:8]
        while token in self._entries:
            token = secrets.token_urlsafe(6)[:8]
        self._entries[token] = TokenEntry(
            expires_at=self.clock() + self.ttl_seconds,
            payload=payload,
        )
        return token

    def resolve(self, token: str) -> object | None:
        self.cleanup()
        entry = self._entries.get(token)
        if entry is None:
            return None
        self._entries.move_to_end(token)
        return entry.payload

    def cleanup(self) -> None:
        now = self.clock()
        expired = [token for token, entry in self._entries.items() if entry.expires_at <= now]
        for token in expired:
            self._entries.pop(token, None)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        self.cleanup()
        return len(self._entries)


@dataclass(slots=True)
class SessionState:
    key: SessionKey
    screen: str = "home"
    page: int = 0
    parent_screen: str = "home"
    screen_message_id: int | None = None
    input_mode: str | None = None
    data: dict[str, object] = field(default_factory=dict)
    busy_operations: set[str] = field(default_factory=set)
    tokens: TokenRegistry = field(default_factory=TokenRegistry)
    navigation: NavigationHistory = field(default_factory=NavigationHistory)
    last_activity: float = field(default_factory=monotonic)

    def try_start_operation(self, operation: str) -> bool:
        if operation in self.busy_operations:
            return False
        self.busy_operations.add(operation)
        return True

    def finish_operation(self, operation: str) -> None:
        self.busy_operations.discard(operation)


class SessionStore:
    def __init__(
        self,
        *,
        ttl_seconds: int = 3600,
        max_sessions: int = 256,
        token_ttl_seconds: int = 3600,
        token_limit: int = 128,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.ttl_seconds = max(ttl_seconds, 1)
        self.max_sessions = max(max_sessions, 1)
        self.token_ttl_seconds = token_ttl_seconds
        self.token_limit = token_limit
        self.clock = clock
        self._sessions: OrderedDict[SessionKey, SessionState] = OrderedDict()

    def get(self, chat_id: int, user_id: int) -> SessionState:
        self.cleanup()
        key = SessionKey(chat_id=chat_id, user_id=user_id)
        session = self._sessions.get(key)
        if session is None:
            while len(self._sessions) >= self.max_sessions:
                self._sessions.popitem(last=False)
            session = SessionState(
                key=key,
                tokens=TokenRegistry(
                    ttl_seconds=self.token_ttl_seconds,
                    max_entries=self.token_limit,
                    clock=self.clock,
                ),
            )
            self._sessions[key] = session
        session.last_activity = self.clock()
        self._sessions.move_to_end(key)
        return session

    def cleanup(self) -> None:
        now = self.clock()
        expired = [
            key
            for key, session in self._sessions.items()
            if now - session.last_activity >= self.ttl_seconds
        ]
        for key in expired:
            self._sessions.pop(key, None)

    def __len__(self) -> int:
        self.cleanup()
        return len(self._sessions)
