from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.login_monitor import LoginLogMonitor, USER_PROCESS, WTMP_RECORD_STRUCT


def build_wtmp_record(
    *,
    user_name: str,
    terminal: str,
    source: str = "",
    timestamp: int,
) -> bytes:
    def encode(value: str, length: int) -> bytes:
        return value.encode("utf-8")[: length - 1].ljust(length, b"\x00")

    return WTMP_RECORD_STRUCT.pack(
        USER_PROCESS,
        1234,
        encode(terminal, 32),
        b"p0s0",
        encode(user_name, 32),
        encode(source, 256),
        0,
        0,
        1,
        timestamp,
        0,
        0,
        0,
        0,
        0,
        b"\x00" * 20,
    )


class LoginMonitorTests(unittest.TestCase):
    def test_monitor_reads_only_new_login_events_from_logs(self) -> None:
        log_path = Path("tests") / f"tmp_auth_{uuid.uuid4().hex}.log"
        try:
            log_path.write_text(
                "Apr 16 09:00:00 srv sshd[100]: Accepted publickey for root from 1.2.3.4 port 2222 ssh2\n",
                encoding="utf-8",
            )

            monitor = LoginLogMonitor(
                log_paths=(str(log_path),),
                wtmp_paths=tuple(),
                timezone_name="UTC",
                utmp_paths=tuple(),
            )

            first_poll = monitor.poll_events()
            self.assertEqual([], first_poll)

            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    "Apr 16 09:05:00 srv sshd[101]: Accepted password for admin from 5.6.7.8 port 2200 ssh2\n"
                )
                handle.write(
                    "Apr 16 09:06:00 srv login[102]: pam_unix(login:session): session opened for user root(uid=0) by LOGIN(uid=0)\n"
                )

            events = monitor.poll_events()

            self.assertEqual(2, len(events))
            self.assertEqual("ssh", events[0].event_type)
            self.assertEqual("admin", events[0].user_name)
            self.assertEqual("5.6.7.8", events[0].source)
            self.assertEqual("local", events[1].event_type)
            self.assertEqual("root", events[1].user_name)
        finally:
            if log_path.exists():
                log_path.unlink()

    def test_monitor_detects_new_sessions_from_utmp(self) -> None:
        utmp_path = Path("tests") / f"tmp_utmp_{uuid.uuid4().hex}"
        try:
            utmp_path.write_bytes(
                build_wtmp_record(
                    user_name="root",
                    terminal="tty1",
                    timestamp=int(datetime(2026, 4, 18, 9, 0, tzinfo=timezone.utc).timestamp()),
                )
            )
            monitor = LoginLogMonitor(
                log_paths=tuple(),
                wtmp_paths=tuple(),
                timezone_name="UTC",
                utmp_paths=(str(utmp_path),),
            )

            self.assertEqual([], monitor.poll_events())

            with utmp_path.open("ab") as handle:
                handle.write(
                    build_wtmp_record(
                        user_name="admin",
                        terminal="pts/0",
                        source="5.6.7.8",
                        timestamp=int(datetime(2026, 4, 18, 9, 5, tzinfo=timezone.utc).timestamp()),
                    )
                )

            events = monitor.poll_events()

            self.assertEqual(1, len(events))
            self.assertEqual("ssh", events[0].event_type)
            self.assertEqual("admin", events[0].user_name)
            self.assertEqual("5.6.7.8", events[0].source)
            self.assertEqual("pts/0", events[0].terminal)
        finally:
            if utmp_path.exists():
                utmp_path.unlink()

    def test_monitor_deduplicates_log_and_utmp_events(self) -> None:
        log_path = Path("tests") / f"tmp_auth_{uuid.uuid4().hex}.log"
        utmp_path = Path("tests") / f"tmp_utmp_{uuid.uuid4().hex}"
        try:
            log_path.write_text("", encoding="utf-8")
            utmp_path.write_bytes(b"")
            monitor = LoginLogMonitor(
                log_paths=(str(log_path),),
                wtmp_paths=tuple(),
                timezone_name="UTC",
                utmp_paths=(str(utmp_path),),
            )

            self.assertEqual([], monitor.poll_events())

            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    "Apr 18 09:05:00 srv sshd[101]: Accepted password for admin from 5.6.7.8 port 2200 ssh2\n"
                )
            with utmp_path.open("ab") as handle:
                handle.write(
                    build_wtmp_record(
                        user_name="admin",
                        terminal="pts/0",
                        source="5.6.7.8",
                        timestamp=int(datetime(2026, 4, 18, 9, 5, tzinfo=timezone.utc).timestamp()),
                    )
                )

            events = monitor.poll_events()

            self.assertEqual(1, len(events))
            self.assertEqual("admin", events[0].user_name)
            self.assertEqual("5.6.7.8", events[0].source)
        finally:
            if log_path.exists():
                log_path.unlink()
            if utmp_path.exists():
                utmp_path.unlink()

    def test_monitor_reads_new_wtmp_records(self) -> None:
        wtmp_path = Path("tests") / f"tmp_wtmp_{uuid.uuid4().hex}"
        try:
            wtmp_path.write_bytes(
                build_wtmp_record(
                    user_name="root",
                    terminal="tty1",
                    timestamp=int(datetime(2026, 4, 27, 9, 0, tzinfo=timezone.utc).timestamp()),
                )
            )

            monitor = LoginLogMonitor(
                log_paths=tuple(),
                wtmp_paths=(str(wtmp_path),),
                timezone_name="UTC",
                utmp_paths=tuple(),
            )

            self.assertEqual([], monitor.poll_events())

            with wtmp_path.open("ab") as handle:
                handle.write(
                    build_wtmp_record(
                        user_name="admin",
                        terminal="pts/0",
                        source="5.6.7.8",
                        timestamp=int(datetime(2026, 4, 27, 9, 5, tzinfo=timezone.utc).timestamp()),
                    )
                )

            events = monitor.poll_events()

            self.assertEqual(1, len(events))
            self.assertEqual("ssh", events[0].event_type)
            self.assertEqual("admin", events[0].user_name)
            self.assertEqual("5.6.7.8", events[0].source)
            self.assertEqual("pts/0", events[0].terminal)
        finally:
            if wtmp_path.exists():
                wtmp_path.unlink()

    def test_monitor_keeps_two_sessions_same_minute_on_different_terminals(self) -> None:
        wtmp_path = Path("tests") / f"tmp_wtmp_{uuid.uuid4().hex}"
        try:
            wtmp_path.write_bytes(b"")
            monitor = LoginLogMonitor(
                log_paths=tuple(),
                wtmp_paths=(str(wtmp_path),),
                timezone_name="UTC",
                utmp_paths=tuple(),
            )

            self.assertEqual([], monitor.poll_events())

            with wtmp_path.open("ab") as handle:
                handle.write(
                    build_wtmp_record(
                        user_name="admin",
                        terminal="pts/0",
                        source="5.6.7.8",
                        timestamp=int(datetime(2026, 4, 27, 9, 5, tzinfo=timezone.utc).timestamp()),
                    )
                )
                handle.write(
                    build_wtmp_record(
                        user_name="admin",
                        terminal="pts/1",
                        source="5.6.7.8",
                        timestamp=int(datetime(2026, 4, 27, 9, 5, 20, tzinfo=timezone.utc).timestamp()),
                    )
                )

            events = monitor.poll_events()

            self.assertEqual(2, len(events))
            self.assertEqual({"pts/0", "pts/1"}, {event.terminal for event in events})
        finally:
            if wtmp_path.exists():
                wtmp_path.unlink()

    def test_monitor_lists_recent_failed_login_events(self) -> None:
        log_path = Path("tests") / f"tmp_auth_{uuid.uuid4().hex}.log"
        try:
            log_path.write_text(
                "\n".join(
                    [
                        "Apr 18 09:00:00 srv sshd[100]: Failed password for root from 1.2.3.4 port 2222 ssh2",
                        "Apr 18 09:01:00 srv sshd[101]: Invalid user test from 5.6.7.8 port 2200",
                        "Apr 18 09:02:00 srv sshd[102]: Accepted publickey for root from 9.9.9.9 port 22 ssh2",
                    ]
                ),
                encoding="utf-8",
            )

            monitor = LoginLogMonitor(
                log_paths=(str(log_path),),
                wtmp_paths=tuple(),
                timezone_name="UTC",
                utmp_paths=tuple(),
            )

            events = monitor.list_failed_login_events(limit=10)

            self.assertEqual(2, len(events))
            self.assertEqual("test", events[0].user_name)
            self.assertEqual("5.6.7.8", events[0].source)
            self.assertEqual("Invalid user", events[0].reason)
            self.assertEqual("root", events[1].user_name)
            self.assertEqual("1.2.3.4", events[1].source)
            self.assertEqual("Failed password", events[1].reason)
        finally:
            if log_path.exists():
                log_path.unlink()


if __name__ == "__main__":
    unittest.main()
