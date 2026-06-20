from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from shlex import quote


DEFAULT_CLEANUP_PATH = "/opt/monitoring-bot"
DEFAULT_HOSTFS_ROOT = "/hostfs"


@dataclass(slots=True, frozen=True)
class CleanupCommand:
    cleanup_path: str
    command: str


@dataclass(slots=True, frozen=True)
class CleanupCandidate:
    path: str
    container_path: Path
    size_bytes: int


def build_cleanup_command(cleanup_path: str = DEFAULT_CLEANUP_PATH) -> CleanupCommand:
    normalized_cleanup_path = _normalize_absolute_path(cleanup_path)
    cleanup_arg = quote(normalized_cleanup_path)
    missing_path_message = quote(f"Каталог {normalized_cleanup_path} не найден.")

    command = " ".join(
        [
            "set -eu;",
            f"cleanup_root={cleanup_arg};",
            f"if [ ! -d {cleanup_arg} ]; then",
            f"echo {missing_path_message} >&2;",
            "exit 4;",
            "fi;",
            "removed_list=$(mktemp);",
            "find \"$cleanup_root\" -type d \\( -name __pycache__ -o -name .pytest_cache \\) -prune -print > \"$removed_list\";",
            "find \"$cleanup_root\" -maxdepth 1 -type d -name 'tmp*' -print >> \"$removed_list\";",
            "sort -u \"$removed_list\" -o \"$removed_list\";",
            "while IFS= read -r target; do",
            "[ -n \"$target\" ] || continue;",
            "case \"$target\" in \"$cleanup_root\"/*) rm -rf -- \"$target\" ;; *) echo \"Пропущен небезопасный путь: $target\" >&2 ;; esac;",
            "done < \"$removed_list\";",
            "count=$(wc -l < \"$removed_list\" | tr -d ' ');",
            "echo \"Удалено элементов: $count\";",
            "if [ \"$count\" -gt 0 ]; then cat \"$removed_list\"; fi;",
            "rm -f \"$removed_list\";",
        ]
    )

    return CleanupCommand(cleanup_path=normalized_cleanup_path, command=command)


def list_cleanup_candidates(
    cleanup_path: str,
    *,
    hostfs_root: str = DEFAULT_HOSTFS_ROOT,
) -> list[CleanupCandidate]:
    normalized_cleanup_path = _normalize_absolute_path(cleanup_path)
    cleanup_root = _container_path_for_host_path(normalized_cleanup_path, hostfs_root)
    if not cleanup_root.exists() or not cleanup_root.is_dir():
        return []

    candidates: dict[Path, CleanupCandidate] = {}

    for path in cleanup_root.rglob("*"):
        if not path.is_dir():
            continue
        if path.name not in {"__pycache__", ".pytest_cache"}:
            continue
        candidates[path] = CleanupCandidate(
            path=_host_path_for_container_path(path, normalized_cleanup_path, cleanup_root),
            container_path=path,
            size_bytes=_directory_size(path),
        )

    for path in cleanup_root.glob("tmp*"):
        if not path.is_dir():
            continue
        candidates[path] = CleanupCandidate(
            path=_host_path_for_container_path(path, normalized_cleanup_path, cleanup_root),
            container_path=path,
            size_bytes=_directory_size(path),
        )

    return sorted(candidates.values(), key=lambda item: item.path)


def _directory_size(path: Path) -> int:
    total_size = 0
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        try:
            total_size += item.stat().st_size
        except OSError:
            continue
    return total_size


def _container_path_for_host_path(host_path: str, hostfs_root: str) -> Path:
    normalized_hostfs_root = hostfs_root.strip() or DEFAULT_HOSTFS_ROOT
    relative_host_path = host_path.lstrip("/")
    return Path(normalized_hostfs_root) / relative_host_path


def _host_path_for_container_path(path: Path, host_root_path: str, container_root_path: Path) -> str:
    try:
        relative_path = path.relative_to(container_root_path)
    except ValueError:
        return str(path)
    return str(PurePosixPath(host_root_path) / PurePosixPath(relative_path.as_posix()))


def _normalize_absolute_path(value: str) -> str:
    path = value.strip()
    if not path:
        raise ValueError("Путь очистки не может быть пустым")
    if not path.startswith("/"):
        raise ValueError("Путь очистки должен быть абсолютным")
    return path.rstrip("/") or "/"
