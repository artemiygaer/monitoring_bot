from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


HOST_ROOT_DIR = "/hostfs"
HOST_ROOT_PATH = Path(HOST_ROOT_DIR)


def build_host_command(command: str, host_root: str = HOST_ROOT_DIR) -> list[str]:
    return [
        "nsenter",
        "--target",
        "1",
        "--uts",
        "--ipc",
        "--net",
        "--pid",
        "chroot",
        host_root,
        "/bin/sh",
        "-lc",
        command,
    ]


def main() -> int:
    command = os.getenv("MONITOR_HOST_COMMAND", "").strip()
    timeout_seconds = int(os.getenv("MONITOR_HOST_COMMAND_TIMEOUT_SECONDS", "20"))

    if not command:
        print("Команда не передана.", file=sys.stderr)
        return 2

    if not HOST_ROOT_PATH.exists():
        print(
            "Каталог /hostfs не найден. Проверь bind-mount корня хоста в docker-compose.",
            file=sys.stderr,
        )
        return 3

    host_command = build_host_command(command)

    try:
        completed = subprocess.run(
            host_command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(f"Команда превысила лимит {timeout_seconds} сек.", file=sys.stderr)
        return 124

    if completed.stdout:
        print(completed.stdout.rstrip())
    if completed.stderr:
        if completed.stdout:
            print()
        print(completed.stderr.rstrip(), file=sys.stderr)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
