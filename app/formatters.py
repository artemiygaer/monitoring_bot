from __future__ import annotations

import html
from datetime import datetime

from app.models import ContainerInfo
from app.models import ContainerStats, DiskUsage, ServiceInfo, SystemSnapshot


def service_level(service: ServiceInfo) -> str:
    if service.running_count == service.total_count and service.unhealthy_count == 0:
        return "OK"
    if service.running_count > 0:
        return "WARN"
    return "DOWN"


def service_level_emoji(service: ServiceInfo) -> str:
    mapping = {
        "OK": "🟢",
        "WARN": "🟡",
        "DOWN": "🔴",
    }
    return mapping[service_level(service)]


def service_level_text(service: ServiceInfo) -> str:
    mapping = {
        "OK": "в порядке",
        "WARN": "требует внимания",
        "DOWN": "недоступен",
    }
    return mapping[service_level(service)]


def format_overview(
    services: list[ServiceInfo],
    project_name: str | None,
    available_project_names: list[str] | None = None,
    system_snapshot: SystemSnapshot | None = None,
    updated_at: datetime | None = None,
) -> str:
    ok_count = sum(1 for service in services if service_level(service) == "OK")
    warn_count = sum(1 for service in services if service_level(service) == "WARN")
    down_count = sum(1 for service in services if service_level(service) == "DOWN")
    total_containers = sum(service.total_count for service in services)

    lines = [
        "<b>Сводка по Docker Compose</b>",
        f"<b>Проект:</b> {html.escape(project_name or 'все compose-проекты')}",
        f"<b>Сервисов:</b> {len(services)}",
        f"<b>Контейнеров:</b> {total_containers}",
        f"<b>Статусы:</b> 🟢 {ok_count}  🟡 {warn_count}  🔴 {down_count}",
        f"<b>Обновлено:</b> {html.escape(format_datetime(updated_at or datetime.now().astimezone()))}",
        "",
    ]

    if system_snapshot is not None:
        lines.append("<b>Система</b>")
        lines.extend(format_system_summary(system_snapshot).splitlines())
        lines.append("")

    if not services:
        lines.append("Подходящие сервисы не найдены.")
        if project_name and available_project_names:
            lines.append("")
            lines.append(
                f"<b>Возможная причина:</b> проект <code>{html.escape(project_name)}</code> не найден в Docker."
            )
            lines.append(f"<b>Доступные compose-проекты:</b> {html.escape(', '.join(available_project_names))}")
        return "\n".join(lines)

    sorted_services = sorted(
        services,
        key=lambda item: (service_sort_rank(item), (item.project_name or ""), item.name),
    )
    problem_services = [service for service in sorted_services if service_level(service) != "OK"]
    if problem_services:
        lines.append("<b>Проблемы сейчас</b>")
        for service in problem_services[:5]:
            lines.append(format_service_card(service, show_project=project_name is None))
        lines.append("")

    lines.append("<b>Все сервисы</b>")
    for service in sorted_services:
        lines.append(format_service_card(service, show_project=project_name is None))
    return "\n".join(lines)


def format_service_details(service: ServiceInfo) -> str:
    sections = [
        f"{service_level_emoji(service)} <b>Сервис:</b> {html.escape(service.name)}",
        f"<b>Проект:</b> {html.escape(service.project_name or 'не указан')}",
        f"<b>Контейнеров:</b> {service.total_count}",
        f"<b>Общий статус:</b> {service_level_emoji(service)} {html.escape(service_level_text(service))}",
        "",
    ]

    for container in service.containers:
        sections.extend(
            [
                format_container_line(container),
                f"Состояние: {status_emoji(container.status)} {html.escape(format_container_status(container.status))}",
                f"Проверка: {health_emoji(container.health)} {html.escape(format_health_status(container.health))}",
                f"Образ: {html.escape(container.image)}",
                f"Запущен: {html.escape(format_datetime(container.started_at))}",
                "",
            ]
        )

    return "\n".join(sections).strip()


def format_container_details(container: ContainerInfo) -> str:
    title = container.name
    if container.project_name:
        title = f"{container.project_name}/{container.service_name}/{container.name}"

    return "\n".join(
        [
            f"{status_emoji(container.status)} <b>Контейнер:</b> {html.escape(title)}",
            f"<b>Сервис:</b> {html.escape(container.service_name)}",
            f"<b>Проект:</b> {html.escape(container.project_name or 'не указан')}",
            f"<b>Состояние:</b> {status_emoji(container.status)} {html.escape(format_container_status(container.status))}",
            f"<b>Проверка:</b> {health_emoji(container.health)} {html.escape(format_health_status(container.health))}",
            f"<b>Образ:</b> {html.escape(container.image)}",
            f"<b>Запущен:</b> {html.escape(format_datetime(container.started_at))}",
        ]
    )


def format_stats(
    stats: list[ContainerStats],
    service_name: str | None = None,
    title: str | None = None,
) -> str:
    title = title or ("Статистика сервиса" if service_name else "Статистика контейнеров")
    lines = [f"<b>{title}</b>", ""]

    if not stats:
        lines.append("Нет данных по контейнерам.")
        return "\n".join(lines)

    blocks = []
    for item in stats:
        blocks.append(
            "\n".join(
                [
                    f"📊 {item.service_name}/{item.container_name}",
                    f"CPU: {item.cpu_percent:.2f}%",
                    f"RAM: {format_bytes(item.memory_usage)} / {format_bytes(item.memory_limit)} ({item.memory_percent:.2f}%)",
                    f"Сеть RX/TX: {format_bytes(item.network_rx)} / {format_bytes(item.network_tx)}",
                ]
            )
        )

    lines.append("<pre>")
    lines.append(html.escape("\n\n".join(blocks)))
    lines.append("</pre>")
    return "\n".join(lines)


def format_resources(snapshot: SystemSnapshot | None, stats: list[ContainerStats], *, top_limit: int = 5) -> str:
    lines = ["📈 <b>Ресурсы</b>"]

    if snapshot is None:
        lines.extend(
            [
                "",
                "<b>Хост:</b> системные метрики недоступны.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                f"<b>Хост:</b> {html.escape(snapshot.hostname)}",
                (
                    f"CPU: {usage_emoji(snapshot.cpu_percent)} {snapshot.cpu_percent:.1f}%"
                    f"  |  среднее {snapshot.cpu_percent_avg_5m:.1f}%"
                ),
                (
                    f"Load: {load_emoji(snapshot.load_average_1m, snapshot.cpu_count)} "
                    f"{snapshot.load_average_1m:.2f} / {snapshot.cpu_count} CPU"
                ),
                (
                    f"RAM: {usage_emoji(snapshot.memory_used_percent)} {format_bytes(snapshot.memory_used_bytes)}"
                    f" / {format_bytes(snapshot.memory_total_bytes)} ({snapshot.memory_used_percent:.1f}%)"
                ),
            ]
        )
        if snapshot.disk_usage is not None:
            lines.append(
                f"Диск {html.escape(snapshot.disk_usage.path_label)}: {format_disk_summary(snapshot.disk_usage)}"
            )

    if not stats:
        lines.extend(["", "<b>Контейнеры:</b> данных по ресурсам нет."])
        return "\n".join(lines)

    cpu_top = sorted(stats, key=lambda item: item.cpu_percent, reverse=True)[:top_limit]
    ram_top = sorted(stats, key=lambda item: item.memory_usage, reverse=True)[:top_limit]

    lines.extend(["", f"<b>Топ CPU</b>"])
    for item in cpu_top:
        lines.append(
            f"{usage_emoji(item.cpu_percent)} {html.escape(item.service_name)}/{html.escape(item.container_name)}"
            f" — {item.cpu_percent:.2f}%"
        )

    lines.extend(["", f"<b>Топ RAM</b>"])
    for item in ram_top:
        lines.append(
            f"{usage_emoji(item.memory_percent)} {html.escape(item.service_name)}/{html.escape(item.container_name)}"
            f" — {format_bytes(item.memory_usage)} ({item.memory_percent:.2f}%)"
        )

    total_memory = sum(item.memory_usage for item in stats)
    lines.extend(
        [
            "",
            f"<b>Контейнеров со статистикой:</b> {len(stats)}",
            f"<b>RAM контейнеров суммарно:</b> {format_bytes(total_memory)}",
        ]
    )
    return "\n".join(lines)


def format_logs_caption(service_name: str, tail: int) -> str:
    return f"Логи сервиса {service_name}, последние {tail} строк"


def format_system_summary(snapshot: SystemSnapshot) -> str:
    disk_text = "не настроен"
    if snapshot.disk_usage is not None:
        disk_text = format_disk_summary(snapshot.disk_usage)

    lines = [
        f"Хост: <b>{html.escape(snapshot.hostname)}</b>",
        (
            f"CPU: {usage_emoji(snapshot.cpu_percent)} {snapshot.cpu_percent:.1f}%"
            f"  |  Load: {load_emoji(snapshot.load_average_1m, snapshot.cpu_count)} "
            f"{snapshot.load_average_1m:.2f} / {snapshot.cpu_count}"
        ),
        (
            f"RAM: {usage_emoji(snapshot.memory_used_percent)} {format_bytes(snapshot.memory_used_bytes)}"
            f" / {format_bytes(snapshot.memory_total_bytes)} ({snapshot.memory_used_percent:.1f}%)"
        ),
        (
            f"Среднее за 5 мин: CPU {usage_emoji(snapshot.cpu_percent_avg_5m)} {snapshot.cpu_percent_avg_5m:.1f}%"
            f"  |  RAM {usage_emoji(snapshot.memory_used_percent_avg_5m)} {snapshot.memory_used_percent_avg_5m:.1f}%"
        ),
        f"Диск {html.escape(snapshot.disk_usage.path_label if snapshot.disk_usage else '/')}:" f" {disk_text}",
        f"Uptime: {html.escape(format_duration(snapshot.uptime_seconds))}",
    ]

    if snapshot.swap_total_bytes > 0:
        lines.append(
            f"Swap: {usage_emoji(snapshot.swap_used_percent)} {format_bytes(snapshot.swap_used_bytes)}"
            f" / {format_bytes(snapshot.swap_total_bytes)} ({snapshot.swap_used_percent:.1f}%)"
        )

    return "\n".join(lines)


def format_system_details(snapshot: SystemSnapshot) -> str:
    lines = [
        f"🖥️ <b>Состояние сервера {html.escape(snapshot.hostname)}</b>",
        f"<b>Обновлено:</b> {html.escape(format_datetime(snapshot.collected_at))}",
        "",
        f"<b>CPU:</b> {usage_emoji(snapshot.cpu_percent)} {snapshot.cpu_percent:.1f}% на {snapshot.cpu_count} CPU",
        (
            f"<b>CPU среднее за 5 мин:</b> {usage_emoji(snapshot.cpu_percent_avg_5m)} "
            f"{snapshot.cpu_percent_avg_5m:.1f}%"
        ),
        (
            f"<b>Load average:</b> {load_emoji(snapshot.load_average_1m, snapshot.cpu_count)} "
            f"{snapshot.load_average_1m:.2f} / {snapshot.load_average_5m:.2f} / {snapshot.load_average_15m:.2f}"
        ),
        (
            f"<b>RAM:</b> {usage_emoji(snapshot.memory_used_percent)} {format_bytes(snapshot.memory_used_bytes)}"
            f" / {format_bytes(snapshot.memory_total_bytes)} ({snapshot.memory_used_percent:.1f}%)"
        ),
        (
            f"<b>RAM среднее за 5 мин:</b> {usage_emoji(snapshot.memory_used_percent_avg_5m)} "
            f"{snapshot.memory_used_percent_avg_5m:.1f}%"
        ),
        (
            f"<b>RAM свободно:</b> {format_bytes(snapshot.memory_available_bytes)}"
        ),
        (
            f"<b>Swap:</b> {usage_emoji(snapshot.swap_used_percent) if snapshot.swap_total_bytes > 0 else '⚪'} "
            f"{format_bytes(snapshot.swap_used_bytes)} / {format_bytes(snapshot.swap_total_bytes)}"
            f" ({snapshot.swap_used_percent:.1f}%)"
        ),
    ]

    if snapshot.disk_usage is not None:
        lines.extend(
            [
                (
                    f"<b>Диск {html.escape(snapshot.disk_usage.path_label)}:</b> "
                    f"{format_disk_summary(snapshot.disk_usage)}"
                ),
                (
                    f"<b>Свободно на диске:</b> {format_bytes(snapshot.disk_usage.free_bytes)}"
                ),
            ]
        )
    else:
        lines.append("<b>Диск:</b> недоступен, путь мониторинга не смонтирован")

    lines.extend(
        [
            f"<b>Uptime:</b> {html.escape(format_duration(snapshot.uptime_seconds))}",
            (
                f"<b>Окно усреднения:</b> {html.escape(format_duration(snapshot.average_window_seconds))}, "
                f"замеров: {snapshot.average_sample_count}"
            ),
        ]
    )
    return "\n".join(lines)


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "неизвестно"
    return value.strftime("%d.%m.%Y %H:%M:%S %Z")


def format_bytes(value: int) -> str:
    if value <= 0:
        return "0 B"

    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    amount = float(value)
    unit_index = 0

    while amount >= 1024 and unit_index < len(units) - 1:
        amount /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(amount)} {units[unit_index]}"
    return f"{amount:.2f} {units[unit_index]}"


def format_duration(total_seconds: int) -> str:
    days, remainder = divmod(max(total_seconds, 0), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}д")
    if hours or parts:
        parts.append(f"{hours}ч")
    if minutes or parts:
        parts.append(f"{minutes}м")
    parts.append(f"{seconds}с")
    return " ".join(parts)


def usage_emoji(percent: float) -> str:
    if percent >= 90:
        return "🔴"
    if percent >= 70:
        return "🟡"
    return "🟢"


def load_emoji(load_average: float, cpu_count: int) -> str:
    if cpu_count <= 0:
        return "⚪"

    normalized_percent = load_average / cpu_count * 100
    if normalized_percent >= 100:
        return "🔴"
    if normalized_percent >= 70:
        return "🟡"
    return "🟢"


def format_disk_summary(disk_usage: DiskUsage) -> str:
    return (
        f"{usage_emoji(disk_usage.used_percent)} {format_bytes(disk_usage.used_bytes)}"
        f" / {format_bytes(disk_usage.total_bytes)} ({disk_usage.used_percent:.1f}%)"
    )


def format_container_status(value: str | None) -> str:
    mapping = {
        "created": "создан",
        "restarting": "перезапускается",
        "running": "работает",
        "removing": "удаляется",
        "paused": "на паузе",
        "exited": "остановлен",
        "dead": "недоступен",
    }
    return mapping.get(value or "", value or "неизвестно")


def format_health_status(value: str | None) -> str:
    mapping = {
        None: "не задана",
        "starting": "запускается",
        "healthy": "исправен",
        "unhealthy": "ошибка",
    }
    return mapping.get(value, value or "неизвестно")


def status_emoji(value: str | None) -> str:
    mapping = {
        "created": "⚪",
        "restarting": "🟡",
        "running": "🟢",
        "removing": "🟡",
        "paused": "⏸️",
        "exited": "🔴",
        "dead": "🔴",
    }
    return mapping.get(value or "", "⚪")


def health_emoji(value: str | None) -> str:
    mapping = {
        None: "⚪",
        "starting": "🟡",
        "healthy": "🟢",
        "unhealthy": "🔴",
    }
    return mapping.get(value, "⚪")


def format_service_card(service: ServiceInfo, show_project: bool) -> str:
    title = service.name
    if show_project and service.project_name:
        title = f"{service.project_name}/{service.name}"

    container_parts = ", ".join(
        f"{status_emoji(container.status)} {container.name}" for container in service.containers
    )
    return "\n".join(
        [
            f"{service_level_emoji(service)} <b>{html.escape(title)}</b> — {html.escape(service_level_text(service))}",
            f"Работает: {service.running_count}/{service.total_count}",
            f"Контейнеры: {html.escape(container_parts)}",
        ]
    )


def format_container_line(container: ContainerInfo) -> str:
    return f"{status_emoji(container.status)} <b>Контейнер:</b> {html.escape(container.name)}"


def service_sort_rank(service: ServiceInfo) -> int:
    rank = {
        "DOWN": 0,
        "WARN": 1,
        "OK": 2,
    }
    return rank[service_level(service)]
