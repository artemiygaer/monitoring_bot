from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.alerting import DockerAlertWatcher
from app.config import load_settings
from app.docker_monitor import DockerMonitor
from app.handlers import create_router
from app.host_command_executor import HostCommandExecutor
from app.login_monitor import LoginLogMonitor
from app.system_monitor import SystemMonitor


async def main() -> None:
    settings = load_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    monitor = DockerMonitor(
        base_url=settings.docker_base_url,
        project_name=settings.docker_project_name,
        excluded_services=settings.excluded_services,
        timezone_name=settings.timezone_name,
    )
    monitor.ping()

    system_monitor = SystemMonitor(
        proc_path=settings.system_proc_path,
        disk_path=settings.system_disk_path,
        disk_label=settings.system_disk_label,
        cache_seconds=settings.system_cache_seconds,
        average_window_seconds=settings.system_average_window_seconds,
        timezone_name=settings.timezone_name,
        server_name=settings.server_name,
    )

    login_monitor = None
    if settings.login_alerts_enabled:
        login_monitor = LoginLogMonitor(
            log_paths=settings.login_log_paths,
            wtmp_paths=settings.login_wtmp_paths,
            timezone_name=settings.timezone_name,
            utmp_paths=settings.login_utmp_paths,
        )
    command_executor = HostCommandExecutor(
        base_url=settings.docker_base_url,
        helper_image=settings.bot_image_name,
        timeout_seconds=settings.command_timeout_seconds,
        max_output_chars=settings.command_max_output_chars,
    )

    bot = Bot(
        token=settings.telegram_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(create_router(monitor, system_monitor, login_monitor, command_executor, settings))
    
    alert_tasks: list[asyncio.Task[None]] = []

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_my_commands([])

        alert_watcher = DockerAlertWatcher(
            monitor=monitor,
            system_monitor=system_monitor,
            login_monitor=login_monitor,
            bot=bot,
            chat_ids=settings.alert_chat_ids,
            poll_interval_seconds=settings.alert_poll_seconds,
            login_poll_interval_seconds=settings.login_poll_seconds,
            notify_on_startup=settings.notify_on_startup,
            system_alert_threshold_percent=settings.system_alert_threshold_percent,
        )
        alert_tasks.append(asyncio.create_task(alert_watcher.run(), name="docker-alert-watcher"))

        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        for task in alert_tasks:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        
        monitor.close()
        command_executor.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
