from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from pathlib import Path, PurePosixPath
from shlex import quote


DEFAULT_BACKUP_SOURCE_DIR = "/root"
DEFAULT_BACKUP_TARGET_DIR = "/backup"
DEFAULT_HOSTFS_ROOT = "/hostfs"


@dataclass(slots=True, frozen=True)
class BackupCommand:
    source_dir: str
    target_dir: str
    archive_name: str
    archive_path: str
    command: str


@dataclass(slots=True, frozen=True)
class BackupArchive:
    name: str
    host_path: str
    container_path: Path
    size_bytes: int
    modified_at: datetime


def build_backup_command(
    created_at: datetime,
    *,
    source_dir: str = DEFAULT_BACKUP_SOURCE_DIR,
    target_dir: str = DEFAULT_BACKUP_TARGET_DIR,
) -> BackupCommand:
    normalized_source_dir = _normalize_absolute_path(source_dir)
    normalized_target_dir = _normalize_absolute_path(target_dir)
    archive_name = f"root-backup-{created_at:%Y%m%d-%H%M%S}.tar.gz"
    archive_path = f"{normalized_target_dir.rstrip('/')}/{archive_name}"

    source_arg = quote(normalized_source_dir)
    target_arg = quote(normalized_target_dir)
    archive_arg = quote(archive_path)
    missing_source_message = quote(f"Директория {normalized_source_dir} не найдена.")

    command = " ".join(
        [
            "set -eu;",
            f"if [ ! -d {source_arg} ]; then",
            f"echo {missing_source_message} >&2;",
            "exit 4;",
            "fi;",
            f"mkdir -p {target_arg};",
            f"source_kb=$(du -sk -- {source_arg} | awk '{{print $1}}');",
            f"available_kb=$(df -Pk -- {target_arg} | awk 'NR==2 {{print $4}}');",
            'if [ "$available_kb" -le "$source_kb" ]; then',
            "echo 'Недостаточно свободного места для бекапа.' >&2;",
            'echo "Нужно минимум: ${source_kb} KiB" >&2;',
            'echo "Доступно: ${available_kb} KiB" >&2;',
            "exit 5;",
            "fi;",
            f"tar -czf {archive_arg} -C {source_arg} .;",
            "echo 'Архив создан:';",
            f"echo {archive_arg};",
            "echo 'Размер:';",
            f"du -h {archive_arg} | awk '{{print $1}}';",
        ]
    )

    return BackupCommand(
        source_dir=normalized_source_dir,
        target_dir=normalized_target_dir,
        archive_name=archive_name,
        archive_path=archive_path,
        command=command,
    )


def build_delete_backup_command(
    archive_name: str,
    *,
    target_dir: str = DEFAULT_BACKUP_TARGET_DIR,
) -> BackupCommand:
    normalized_target_dir = _normalize_absolute_path(target_dir)
    safe_archive_name = _validate_archive_name(archive_name)
    archive_path = f"{normalized_target_dir.rstrip('/')}/{safe_archive_name}"
    archive_arg = quote(archive_path)
    missing_archive_message = quote(f"Архив {archive_path} не найден.")

    command = " ".join(
        [
            "set -eu;",
            f"if [ ! -f {archive_arg} ]; then",
            f"echo {missing_archive_message} >&2;",
            "exit 4;",
            "fi;",
            f"rm -f -- {archive_arg};",
            "echo 'Архив удалён:';",
            f"echo {archive_arg};",
        ]
    )

    return BackupCommand(
        source_dir="",
        target_dir=normalized_target_dir,
        archive_name=safe_archive_name,
        archive_path=archive_path,
        command=command,
    )


def list_backup_archives(
    *,
    target_dir: str = DEFAULT_BACKUP_TARGET_DIR,
    hostfs_root: str = DEFAULT_HOSTFS_ROOT,
    timezone_info: tzinfo | None = None,
) -> list[BackupArchive]:
    normalized_target_dir = _normalize_absolute_path(target_dir)
    container_dir = _container_path_for_host_path(normalized_target_dir, hostfs_root)
    if not container_dir.exists() or not container_dir.is_dir():
        return []

    archives: list[BackupArchive] = []
    timezone_info = timezone_info or timezone.utc
    for path in container_dir.iterdir():
        if not path.is_file():
            continue
        if not _is_backup_archive_name(path.name):
            continue
        stat = path.stat()
        archives.append(
            BackupArchive(
                name=path.name,
                host_path=f"{normalized_target_dir.rstrip('/')}/{path.name}",
                container_path=path,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone_info),
            )
        )

    return sorted(archives, key=lambda item: item.modified_at, reverse=True)


def find_backup_archive(
    archive_name: str,
    *,
    target_dir: str = DEFAULT_BACKUP_TARGET_DIR,
    hostfs_root: str = DEFAULT_HOSTFS_ROOT,
    timezone_info: tzinfo | None = None,
) -> BackupArchive:
    safe_archive_name = _validate_archive_name(archive_name)
    for archive in list_backup_archives(
        target_dir=target_dir,
        hostfs_root=hostfs_root,
        timezone_info=timezone_info,
    ):
        if archive.name == safe_archive_name:
            return archive
    raise LookupError(f"Архив '{safe_archive_name}' не найден")


def _container_path_for_host_path(host_path: str, hostfs_root: str) -> Path:
    normalized_host_path = _normalize_absolute_path(host_path)
    normalized_hostfs_root = hostfs_root.strip() or DEFAULT_HOSTFS_ROOT
    relative_host_path = normalized_host_path.lstrip("/")
    return Path(normalized_hostfs_root) / relative_host_path


def _normalize_absolute_path(value: str) -> str:
    path = value.strip()
    if not path:
        raise ValueError("Путь для бекапа не может быть пустым")
    if not path.startswith("/"):
        raise ValueError("Путь для бекапа должен быть абсолютным")
    return path.rstrip("/") or "/"


def _validate_archive_name(value: str) -> str:
    archive_name = value.strip()
    if not archive_name:
        raise ValueError("Имя архива не может быть пустым")
    if PurePosixPath(archive_name).name != archive_name:
        raise ValueError("Имя архива не должно содержать путь")
    if not _is_backup_archive_name(archive_name):
        raise ValueError("Имя архива должно заканчиваться на .tar или .tar.gz")
    return archive_name


def _is_backup_archive_name(value: str) -> bool:
    return value.endswith(".tar") or value.endswith(".tar.gz")
