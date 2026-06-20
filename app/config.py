from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    pass


load_dotenv()


def _read_first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None:
            return value
    return ""


def _parse_int_set(raw_value: str | None) -> frozenset[int]:
    if not raw_value:
        return frozenset()

    values: set[int] = set()
    for chunk in raw_value.split(","):
        item = chunk.strip()
        if not item:
            continue
        values.add(int(item))
    return frozenset(values)


def _parse_str_set(raw_value: str | None) -> frozenset[str]:
    if not raw_value:
        return frozenset()

    return frozenset(item.strip() for item in raw_value.split(",") if item.strip())


def _parse_str_list(raw_value: str | None) -> tuple[str, ...]:
    if not raw_value:
        return tuple()

    return tuple(item.strip() for item in raw_value.split(",") if item.strip())


def _parse_bool(raw_value: str | None, default: bool) -> bool:
    if raw_value is None:
        return default

    value = raw_value.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _read_absolute_path(name: str, default: str) -> str:
    value = os.getenv(name, default).strip() or default
    if not value.startswith("/"):
        raise ValueError(f"{name} должен быть абсолютным путём")
    return value


@dataclass(slots=True)
class Settings:
    bot_version: str
    bot_build_date: str
    telegram_token: str
    allowed_user_ids: frozenset[int]
    alert_chat_ids: frozenset[int]
    bot_image_name: str
    docker_base_url: str
    docker_project_name: str | None
    excluded_services: frozenset[str]
    restart_timeout_seconds: int
    default_logs_tail: int
    max_logs_tail: int
    max_inline_log_chars: int
    command_timeout_seconds: int
    command_max_output_chars: int
    backup_source_dir: str
    backup_target_dir: str
    backup_timeout_seconds: int
    cleanup_path: str
    cleanup_timeout_seconds: int
    alert_poll_seconds: int
    login_poll_seconds: int
    notify_on_startup: bool
    timezone_name: str
    log_level: str
    system_proc_path: str
    system_disk_path: str | None
    system_disk_label: str
    system_cache_seconds: int
    system_average_window_seconds: int
    system_alert_threshold_percent: float
    login_alerts_enabled: bool
    login_log_paths: tuple[str, ...]
    login_wtmp_paths: tuple[str, ...]
    login_utmp_paths: tuple[str, ...]
    server_name: str | None


def load_settings() -> Settings:
    telegram_token = _read_first_env("TELEGRAM_BOT_TOKEN", "BOT_TOKEN").strip()
    if not telegram_token:
        raise ValueError("Не задан TELEGRAM_BOT_TOKEN или BOT_TOKEN")

    allowed_user_ids = _parse_int_set(_read_first_env("TELEGRAM_ALLOWED_USER_IDS", "ALLOWED_USER_IDS"))
    if not allowed_user_ids:
        raise ValueError("Не задан TELEGRAM_ALLOWED_USER_IDS или ALLOWED_USER_IDS")

    alert_chat_ids = _parse_int_set(_read_first_env("MONITOR_ALERT_CHAT_IDS", "ALERT_CHAT_IDS"))
    if not alert_chat_ids:
        alert_chat_ids = allowed_user_ids

    default_logs_tail = int(os.getenv("MONITOR_DEFAULT_LOGS_TAIL", "200"))
    max_logs_tail = int(os.getenv("MONITOR_MAX_LOGS_TAIL", "1000"))
    if default_logs_tail <= 0 or max_logs_tail <= 0:
        raise ValueError("MONITOR_DEFAULT_LOGS_TAIL и MONITOR_MAX_LOGS_TAIL должны быть больше нуля")
    if default_logs_tail > max_logs_tail:
        raise ValueError("MONITOR_DEFAULT_LOGS_TAIL не может быть больше MONITOR_MAX_LOGS_TAIL")

    restart_timeout_seconds = int(os.getenv("MONITOR_RESTART_TIMEOUT_SECONDS", "15"))
    if restart_timeout_seconds <= 0:
        raise ValueError("MONITOR_RESTART_TIMEOUT_SECONDS должен быть больше нуля")

    command_timeout_seconds = int(os.getenv("MONITOR_COMMAND_TIMEOUT_SECONDS", "20"))
    if command_timeout_seconds <= 0:
        raise ValueError("MONITOR_COMMAND_TIMEOUT_SECONDS должен быть больше нуля")

    command_max_output_chars = int(os.getenv("MONITOR_COMMAND_MAX_OUTPUT_CHARS", "12000"))
    if command_max_output_chars <= 0:
        raise ValueError("MONITOR_COMMAND_MAX_OUTPUT_CHARS должен быть больше нуля")

    backup_timeout_seconds = int(os.getenv("MONITOR_BACKUP_TIMEOUT_SECONDS", "600"))
    if backup_timeout_seconds <= 0:
        raise ValueError("MONITOR_BACKUP_TIMEOUT_SECONDS должен быть больше нуля")
    backup_source_dir = _read_absolute_path("MONITOR_BACKUP_SOURCE_DIR", "/root")
    backup_target_dir = _read_absolute_path("MONITOR_BACKUP_TARGET_DIR", "/backup")

    cleanup_timeout_seconds = int(os.getenv("MONITOR_CLEANUP_TIMEOUT_SECONDS", "60"))
    if cleanup_timeout_seconds <= 0:
        raise ValueError("MONITOR_CLEANUP_TIMEOUT_SECONDS должен быть больше нуля")
    cleanup_path = _read_absolute_path("MONITOR_CLEANUP_PATH", "/opt/monitoring-bot")

    alert_poll_seconds = int(os.getenv("MONITOR_ALERT_POLL_SECONDS", "30"))
    if alert_poll_seconds <= 0:
        raise ValueError("MONITOR_ALERT_POLL_SECONDS должен быть больше нуля")

    login_poll_seconds = int(os.getenv("MONITOR_LOGIN_POLL_SECONDS", "5"))
    if login_poll_seconds <= 0:
        raise ValueError("MONITOR_LOGIN_POLL_SECONDS должен быть больше нуля")

    system_cache_seconds = int(os.getenv("MONITOR_SYSTEM_CACHE_SECONDS", "5"))
    if system_cache_seconds <= 0:
        raise ValueError("MONITOR_SYSTEM_CACHE_SECONDS должен быть больше нуля")

    system_average_window_seconds = int(os.getenv("MONITOR_SYSTEM_AVERAGE_WINDOW_SECONDS", "300"))
    if system_average_window_seconds < 60:
        raise ValueError("MONITOR_SYSTEM_AVERAGE_WINDOW_SECONDS должен быть не меньше 60")

    system_alert_threshold_percent = float(os.getenv("MONITOR_SYSTEM_ALERT_THRESHOLD_PERCENT", "90"))
    if not 0 < system_alert_threshold_percent <= 100:
        raise ValueError("MONITOR_SYSTEM_ALERT_THRESHOLD_PERCENT должен быть в диапазоне от 0 до 100")

    login_log_paths = _parse_str_list(
        os.getenv("MONITOR_LOGIN_LOG_PATHS", "/hostfs/var/log/auth.log,/hostfs/var/log/secure")
    )
    login_wtmp_paths = _parse_str_list(
        os.getenv("MONITOR_LOGIN_WTMP_PATHS", "/hostfs/var/log/wtmp")
    )
    login_utmp_paths = _parse_str_list(
        os.getenv("MONITOR_LOGIN_UTMP_PATHS", "/hostfs/run/utmp,/hostfs/var/run/utmp")
    )

    return Settings(
        bot_version=os.getenv("MONITOR_BOT_VERSION", "local").strip() or "local",
        bot_build_date=os.getenv("MONITOR_BOT_BUILD_DATE", "").strip() or "unknown",
        telegram_token=telegram_token,
        allowed_user_ids=allowed_user_ids,
        alert_chat_ids=alert_chat_ids,
        bot_image_name=os.getenv("MONITORING_BOT_IMAGE", "monitoring-bot:debian-amd64").strip(),
        docker_base_url=os.getenv("MONITOR_DOCKER_BASE_URL", "unix:///var/run/docker.sock").strip(),
        docker_project_name=os.getenv("MONITOR_DOCKER_PROJECT", "").strip() or None,
        excluded_services=_parse_str_set(os.getenv("MONITOR_EXCLUDED_SERVICES")),
        restart_timeout_seconds=restart_timeout_seconds,
        default_logs_tail=default_logs_tail,
        max_logs_tail=max_logs_tail,
        max_inline_log_chars=int(os.getenv("MONITOR_MAX_INLINE_LOG_CHARS", "3000")),
        command_timeout_seconds=command_timeout_seconds,
        command_max_output_chars=command_max_output_chars,
        backup_source_dir=backup_source_dir,
        backup_target_dir=backup_target_dir,
        backup_timeout_seconds=backup_timeout_seconds,
        cleanup_path=cleanup_path,
        cleanup_timeout_seconds=cleanup_timeout_seconds,
        alert_poll_seconds=alert_poll_seconds,
        login_poll_seconds=login_poll_seconds,
        notify_on_startup=_parse_bool(os.getenv("MONITOR_NOTIFY_ON_STARTUP"), default=False),
        timezone_name=os.getenv("MONITOR_TIMEZONE", "Europe/Moscow").strip(),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        system_proc_path=os.getenv("MONITOR_SYSTEM_PROC_PATH", "/host/proc").strip(),
        system_disk_path=os.getenv("MONITOR_SYSTEM_DISK_PATH", "/hostfs").strip() or None,
        system_disk_label=os.getenv("MONITOR_SYSTEM_DISK_LABEL", "/").strip() or "/",
        system_cache_seconds=system_cache_seconds,
        system_average_window_seconds=system_average_window_seconds,
        system_alert_threshold_percent=system_alert_threshold_percent,
        login_alerts_enabled=_parse_bool(os.getenv("MONITOR_LOGIN_ALERTS_ENABLED"), default=True),
        login_log_paths=login_log_paths,
        login_wtmp_paths=login_wtmp_paths,
        login_utmp_paths=login_utmp_paths,
        server_name=os.getenv("MONITOR_SERVER_NAME", "").strip() or None,
    )
