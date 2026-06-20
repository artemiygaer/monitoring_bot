from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SSH_ACCEPTED_RE = re.compile(
    r"Accepted\s+(?P<method>[\w-]+)\s+for\s+(?:invalid user\s+)?(?P<user>[^\s]+)\s+from\s+(?P<source>[^\s]+)"
)
LOCAL_LOGIN_RE = re.compile(r"pam_unix\(login:session\): session opened for user (?P<user>[^\s(]+)")
FAILED_PASSWORD_RE = re.compile(
    r"Failed\s+(?P<method>[\w-]+)\s+for\s+(?:invalid user\s+)?(?P<user>[^\s]+)\s+from\s+(?P<source>[^\s]+)"
)
INVALID_USER_RE = re.compile(r"Invalid user (?P<user>[^\s]+) from (?P<source>[^\s]+)")
DEFAULT_WTMP_PATHS = ("/hostfs/var/log/wtmp",)
DEFAULT_UTMP_PATHS = ("/hostfs/run/utmp", "/hostfs/var/run/utmp")
HOSTNAME_PATHS = (Path("/hostfs/etc/hostname"), Path("/etc/hostname"))

USER_PROCESS = 7
WTMP_RECORD_STRUCT = struct.Struct("<hi32s4s32s256shhiii4i20s2x")


@dataclass(slots=True)
class LoginEvent:
    event_type: str
    user_name: str
    source: str | None
    host_name: str | None
    happened_at: datetime
    raw_line: str
    log_path: str
    terminal: str | None = None


@dataclass(slots=True)
class FailedLoginEvent:
    user_name: str
    source: str | None
    host_name: str | None
    happened_at: datetime
    raw_line: str
    log_path: str
    reason: str


@dataclass(slots=True)
class LoginFileState:
    inode: int
    position: int


class LoginLogMonitor:
    def __init__(
        self,
        *,
        log_paths: tuple[str, ...],
        wtmp_paths: tuple[str, ...] = DEFAULT_WTMP_PATHS,
        timezone_name: str,
        utmp_paths: tuple[str, ...] = DEFAULT_UTMP_PATHS,
    ) -> None:
        self.log_paths = tuple(Path(path) for path in log_paths if path.strip())
        self.wtmp_paths = tuple(Path(path) for path in wtmp_paths if path.strip())
        self.utmp_paths = tuple(Path(path) for path in utmp_paths if path.strip())
        self.timezone = self._load_timezone(timezone_name)
        self.host_name = self._detect_host_name()
        self._log_states: dict[str, LoginFileState] = {}
        self._wtmp_states: dict[str, LoginFileState] = {}
        self._logs_initialized = False
        self._wtmp_initialized = False
        self._sessions_initialized = False
        self._active_session_keys: set[tuple[str, str, str | None]] = set()

    def poll_events(self) -> list[LoginEvent]:
        events = [*self._poll_log_events(), *self._poll_wtmp_events(), *self._poll_session_events()]
        return self._deduplicate_events(events)

    def list_failed_login_events(self, *, limit: int = 20, max_lines_per_file: int = 2000) -> list[FailedLoginEvent]:
        events: list[FailedLoginEvent] = []

        for path in self.log_paths:
            if not path.exists() or not path.is_file():
                continue

            lines = self._read_recent_lines(path, max_lines=max_lines_per_file)
            for line in lines:
                event = self._parse_failed_log_line(path, line.rstrip("\n"))
                if event is not None:
                    events.append(event)

        events.sort(key=lambda item: item.happened_at, reverse=True)
        return events[: max(limit, 0)]

    def _poll_log_events(self) -> list[LoginEvent]:
        return self._poll_text_files(
            paths=self.log_paths,
            state_map=self._log_states,
            initialized=self._logs_initialized,
            parser=self._parse_log_line,
        )

    def _poll_wtmp_events(self) -> list[LoginEvent]:
        events = self._poll_binary_files(
            paths=self.wtmp_paths,
            state_map=self._wtmp_states,
            initialized=self._wtmp_initialized,
        )
        self._wtmp_initialized = True
        return events

    def _poll_text_files(
        self,
        *,
        paths: tuple[Path, ...],
        state_map: dict[str, LoginFileState],
        initialized: bool,
        parser,
    ) -> list[LoginEvent]:
        events: list[LoginEvent] = []
        first_poll = not initialized

        for path in paths:
            if not path.exists():
                continue

            file_stat = path.stat()
            key = str(path)
            state = state_map.get(key)

            if state is None:
                position = file_stat.st_size if first_poll else 0
                state_map[key] = LoginFileState(inode=file_stat.st_ino, position=position)
                if first_poll:
                    continue
                state = state_map[key]

            if state.inode != file_stat.st_ino or file_stat.st_size < state.position:
                state.inode = file_stat.st_ino
                state.position = 0

            if state.position >= file_stat.st_size:
                continue

            with path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(state.position)
                while True:
                    line = handle.readline()
                    if not line:
                        break
                    event = parser(path, line.rstrip("\n"))
                    if event is not None:
                        events.append(event)
                state.position = handle.tell()

        if paths is self.log_paths:
            self._logs_initialized = True

        return events

    def _poll_binary_files(
        self,
        *,
        paths: tuple[Path, ...],
        state_map: dict[str, LoginFileState],
        initialized: bool,
    ) -> list[LoginEvent]:
        events: list[LoginEvent] = []
        first_poll = not initialized

        for path in paths:
            if not path.exists():
                continue

            file_stat = path.stat()
            key = str(path)
            state = state_map.get(key)

            if state is None:
                position = file_stat.st_size if first_poll else 0
                state_map[key] = LoginFileState(inode=file_stat.st_ino, position=position)
                if first_poll:
                    continue
                state = state_map[key]

            if state.inode != file_stat.st_ino or file_stat.st_size < state.position:
                state.inode = file_stat.st_ino
                state.position = 0

            if state.position >= file_stat.st_size:
                continue

            pending = b""
            chunk_size = WTMP_RECORD_STRUCT.size * 256
            with path.open("rb") as handle:
                handle.seek(state.position)
                while True:
                    raw_chunk = handle.read(chunk_size)
                    if not raw_chunk:
                        break

                    chunk = pending + raw_chunk
                    complete_size = len(chunk) - (len(chunk) % WTMP_RECORD_STRUCT.size)
                    pending = chunk[complete_size:]

                    for offset in range(0, complete_size, WTMP_RECORD_STRUCT.size):
                        event = self._parse_wtmp_record(path, chunk[offset : offset + WTMP_RECORD_STRUCT.size])
                        if event is not None:
                            events.append(event)

                state.position = handle.tell() - len(pending)

        return events

    def _poll_session_events(self) -> list[LoginEvent]:
        utmp_path = next((path for path in self.utmp_paths if path.exists()), None)
        if utmp_path is None:
            self._sessions_initialized = False
            self._active_session_keys.clear()
            return []

        sessions = self._read_active_sessions(utmp_path)
        session_map = {self._build_session_key(session): session for session in sessions}
        current_keys = set(session_map)

        if not self._sessions_initialized:
            self._active_session_keys = current_keys
            self._sessions_initialized = True
            return []

        new_keys = current_keys - self._active_session_keys
        self._active_session_keys = current_keys
        return [
            session_map[key]
            for key in sorted(new_keys, key=lambda item: (item[0], item[1], item[2] or ""))
        ]

    def _read_active_sessions(self, utmp_path: Path) -> list[LoginEvent]:
        sessions: list[LoginEvent] = []

        with utmp_path.open("rb") as handle:
            while True:
                record = handle.read(WTMP_RECORD_STRUCT.size)
                if not record:
                    break
                if len(record) != WTMP_RECORD_STRUCT.size:
                    break

                event = self._parse_wtmp_record(utmp_path, record)
                if event is not None:
                    sessions.append(event)

        return sessions

    def _parse_wtmp_record(self, path: Path, record: bytes) -> LoginEvent | None:
        if len(record) != WTMP_RECORD_STRUCT.size:
            return None

        unpacked = WTMP_RECORD_STRUCT.unpack(record)
        record_type = unpacked[0]
        if record_type != USER_PROCESS:
            return None

        terminal = self._decode_c_string(unpacked[2])
        user_name = self._decode_c_string(unpacked[4])
        source = self._normalize_source(self._decode_c_string(unpacked[5]) or None)
        if not user_name or not terminal:
            return None

        event_type = "local" if source is None or source.startswith(":") else "ssh"
        happened_at = datetime.fromtimestamp(unpacked[9] + unpacked[10] / 1_000_000, tz=self.timezone)
        raw_line = f"{user_name} {terminal} {source or '-'} {happened_at.isoformat()}"

        return LoginEvent(
            event_type=event_type,
            user_name=user_name,
            source=source,
            host_name=self.host_name,
            happened_at=happened_at,
            raw_line=raw_line,
            log_path=str(path),
            terminal=terminal,
        )

    def _parse_log_line(self, path: Path, line: str) -> LoginEvent | None:
        ssh_match = SSH_ACCEPTED_RE.search(line)
        if ssh_match is not None:
            return LoginEvent(
                event_type="ssh",
                user_name=ssh_match.group("user"),
                source=ssh_match.group("source"),
                host_name=self._extract_host_name(line) or self.host_name,
                happened_at=self._parse_log_timestamp(line),
                raw_line=line,
                log_path=str(path),
            )

        local_match = LOCAL_LOGIN_RE.search(line)
        if local_match is not None:
            return LoginEvent(
                event_type="local",
                user_name=local_match.group("user"),
                source=None,
                host_name=self._extract_host_name(line) or self.host_name,
                happened_at=self._parse_log_timestamp(line),
                raw_line=line,
                log_path=str(path),
            )

        return None

    def _parse_failed_log_line(self, path: Path, line: str) -> FailedLoginEvent | None:
        failed_password_match = FAILED_PASSWORD_RE.search(line)
        if failed_password_match is not None:
            return FailedLoginEvent(
                user_name=failed_password_match.group("user"),
                source=failed_password_match.group("source"),
                host_name=self._extract_host_name(line) or self.host_name,
                happened_at=self._parse_log_timestamp(line),
                raw_line=line,
                log_path=str(path),
                reason=f"Failed {failed_password_match.group('method')}",
            )

        invalid_user_match = INVALID_USER_RE.search(line)
        if invalid_user_match is not None:
            return FailedLoginEvent(
                user_name=invalid_user_match.group("user"),
                source=invalid_user_match.group("source"),
                host_name=self._extract_host_name(line) or self.host_name,
                happened_at=self._parse_log_timestamp(line),
                raw_line=line,
                log_path=str(path),
                reason="Invalid user",
            )

        return None

    def _parse_log_timestamp(self, line: str) -> datetime:
        prefix = line[:15]
        current_year = datetime.now(self.timezone).year
        try:
            parsed = datetime.strptime(f"{current_year} {prefix}", "%Y %b %d %H:%M:%S")
            return parsed.replace(tzinfo=self.timezone)
        except ValueError:
            return datetime.now(self.timezone)

    def _deduplicate_events(self, events: list[LoginEvent]) -> list[LoginEvent]:
        unique_events: list[LoginEvent] = []

        for event in sorted(events, key=lambda item: item.happened_at):
            merged = False
            for index, existing_event in enumerate(unique_events):
                if not self._events_match(existing_event, event):
                    continue
                unique_events[index] = self._prefer_richer_event(existing_event, event)
                merged = True
                break

            if not merged:
                unique_events.append(event)

        return unique_events

    def _build_session_key(self, event: LoginEvent) -> tuple[str, str, str | None]:
        return (event.user_name, event.terminal or "", event.source)

    @staticmethod
    def _events_match(left: LoginEvent, right: LoginEvent) -> bool:
        if left.event_type != right.event_type:
            return False
        if left.user_name != right.user_name:
            return False
        if (left.source or "local") != (right.source or "local"):
            return False

        time_delta = abs((left.happened_at - right.happened_at).total_seconds())
        if time_delta > 60:
            return False

        if left.terminal and right.terminal and left.terminal != right.terminal:
            return False

        return True

    @staticmethod
    def _prefer_richer_event(left: LoginEvent, right: LoginEvent) -> LoginEvent:
        def score(event: LoginEvent) -> tuple[int, int]:
            return (
                1 if event.terminal else 0,
                1 if "wtmp" in event.log_path or "utmp" in event.log_path else 0,
            )

        return right if score(right) >= score(left) else left

    @staticmethod
    def _decode_c_string(raw_value: bytes) -> str:
        return raw_value.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()

    @staticmethod
    def _normalize_source(raw_value: str | None) -> str | None:
        if raw_value is None:
            return None

        value = raw_value.strip()
        if not value or value in {"-", "LOCAL"}:
            return None
        return value

    def _detect_host_name(self) -> str | None:
        for path in HOSTNAME_PATHS:
            try:
                if path.exists():
                    value = path.read_text(encoding="utf-8", errors="replace").strip()
                    if value:
                        return value
            except OSError:
                continue
        return None

    @staticmethod
    def _extract_host_name(line: str) -> str | None:
        parts = line.split()
        if len(parts) >= 4:
            return parts[3]
        return None

    @staticmethod
    def _read_recent_lines(path: Path, *, max_lines: int) -> list[str]:
        if max_lines <= 0:
            return []

        file_size = path.stat().st_size
        if file_size == 0:
            return []

        estimated_bytes_per_line = 120
        read_size = min(file_size, max_lines * estimated_bytes_per_line * 2)

        with path.open("rb") as handle:
            handle.seek(max(0, file_size - read_size))
            raw_data = handle.read()

        text = raw_data.decode("utf-8", errors="replace")
        all_lines = text.splitlines()
        return all_lines[-max_lines:]

    @staticmethod
    def _load_timezone(timezone_name: str) -> ZoneInfo | timezone:
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return timezone.utc
