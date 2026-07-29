# Telegram-бот для мониторинга Docker Compose (V2)

[![CI](https://github.com/artemiygaer/monitoring_bot/actions/workflows/ci.yml/badge.svg)](https://github.com/artemiygaer/monitoring_bot/actions/workflows/ci.yml)
[![Docker](https://github.com/artemiygaer/monitoring_bot/actions/workflows/docker.yml/badge.svg)](https://github.com/artemiygaer/monitoring_bot/actions/workflows/docker.yml)
[![Release](https://img.shields.io/github/v/release/artemiygaer/monitoring_bot)](https://github.com/artemiygaer/monitoring_bot/releases/latest)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
[![Docker Image](https://ghcr.io/artemiygaer/monitoring_bot)](https://github.com/artemiygaer/monitoring_bot/pkgs/container/monitoring_bot)
![Python](https://img.shields.io/badge/python-3.12-blue)
![Platform](https://img.shields.io/badge/platform-Debian%20%2F%20Linux-blue)

Децентрализованный Telegram-бот для мониторинга Debian-серверов. Каждый сервер работает независимо, предоставляя полный контроль через изолированный узел.

## Основные возможности

- 📊 **Сводка**: Общее состояние CPU/RAM/Disk и Docker-сервисов (включает кастомное имя сервера).
- 📈 **Ресурсы**: Хостовые CPU/RAM/Disk и топ контейнеров по CPU/RAM в одном экране.
- 🐳 **Контейнеры**: Управление контейнерами (статус, логи, статистика, перезапуск).
- ⌨️ **Команды**: Выполнение любых Shell-команд на хосте с подтверждением.
- 🗄️ **Бекап**: Создание, скачивание (до 50 МиБ) и удаление tar-архивов `/root`.
- ⚙️ **Система**: Подменю для второстепенных функций (Очистка, Ошибки входа, О боте).
- ℹ️ **О боте**: Версия, дата сборки, активные настройки, PID, Python, RSS/VmSize процесса и число активных сессий.
- 🛡️ **Безопасность**: Уведомления о входах (SSH/tty) и ошибки авторизации.
- 🚀 **Деплой**: Готовый образ из GHCR, `.tar.gz` или `.tar`; локальная сборка — резервный вариант.

## Нижнее меню

Главное меню держит только частые действия:

- `Сводка` и `Ресурсы` — быстрый контроль состояния.
- `Контейнеры` и `Бекап` — основные операции.
- `Команды` и `Система` — административные действия.
- `Обновить данные` — повтор текущего экрана.

Редкие действия вынесены в `Система`, чтобы нижняя клавиатура не была перегружена.

## Типы выводимых данных

- `Сводка` показывает короткий статус Docker Compose и системный минимум.
- `Ресурсы` показывает хостовые метрики и топ контейнеров по CPU/RAM.
- `Контейнеры` показывает состояние, healthcheck, образ, логи, статистику и перезапуск.
- `О боте` показывает диагностические данные самого процесса бота.

## Переменные окружения (.env)

| Переменная | Описание |
| :--- | :--- |
| `BOT_TOKEN` | Токен вашего Telegram-бота. |
| `ALLOWED_USER_IDS` | ID пользователей через запятую, имеющих доступ. |
| `MONITOR_SERVER_NAME` | Понятное имя сервера (отображается в сводке вместо ID). |
| `MONITOR_TIMEZONE` | Таймзона (например, `Europe/Moscow`). |
| `MONITOR_BACKUP_SOURCE_DIR` | Что бэкапить (по умолчанию `/root`). |
| `MONITOR_BACKUP_TARGET_DIR` | Куда сохранять бэкапы (по умолчанию `/backup`). |
| `MONITOR_DOCKER_CACHE_SECONDS` | TTL списка контейнеров, по умолчанию 3 секунды. |
| `MONITOR_STATS_CACHE_SECONDS` | TTL статистики контейнеров, по умолчанию 10 секунд. |
| `MONITOR_IO_WORKERS` | Число потоков для блокирующего I/O, по умолчанию 2. |
| `MONITOR_CONTAINER_MEMORY_LIMIT` | Лимит памяти контейнера, по умолчанию `192m`. |
| `MONITOR_CONTAINER_CPU_LIMIT` | Лимит CPU контейнера, по умолчанию `0.5`. |
| `MONITOR_CONTAINER_PIDS_LIMIT` | Лимит процессов контейнера, по умолчанию 64. |

## Быстрый старт (развёртывание)

### Вариант A: через GitHub Release (без сборки на сервере)

На Debian заранее должны быть установлены Docker Engine и Compose plugin. Установщик не меняет APT-репозитории и не устанавливает Docker.

Установка последнего Release одной командой:

```bash
curl -fsSL https://raw.githubusercontent.com/artemiygaer/monitoring_bot/main/install-from-github.sh | sudo bash
```

Скрипт скачает публичные файлы Release в `/opt/monitoring-bot`, проверит checksum образа и запустит интерактивную настройку. Для ARM64 автоматически используется multi-arch образ из GHCR.

Ручная загрузка тех же файлов:

```bash
mkdir -p /opt/monitoring-bot && cd /opt/monitoring-bot
base_url="https://github.com/artemiygaer/monitoring_bot/releases/latest/download"
for file in monitoring-bot-debian-amd64.tar.gz SHA256SUMS.txt install-from-github.sh install.sh deploy.sh docker-compose.bot.yml .env.example; do
  curl -fL -O "$base_url/$file"
done
chmod +x install-from-github.sh install.sh deploy.sh
sha256sum -c SHA256SUMS.txt
bash install.sh
```

### Вариант B: через git clone (образ подтянется из ghcr.io)

```bash
git clone https://github.com/artemiygaer/monitoring_bot.git /opt/monitoring-bot
cd /opt/monitoring-bot
bash install.sh
```

`install.sh` скрыто запросит токен, проверит числовые Telegram ID, имя сервера, часовой пояс и источник образа. Существующий `.env` копируется в `.env.backup-YYYYMMDD-HHMMSS`; неизвестные ключи сохраняются, известные обновляются без дублей. Итоговый `.env` получает права `600`.

Только подготовить конфигурацию:

```bash
bash install.sh --config-only
```

Для автоматизации доступен `--non-interactive`. Токен передаётся через окружение, но не через аргумент процесса:

```bash
read -rsp "Telegram token: " MONITOR_INSTALL_BOT_TOKEN && echo
export MONITOR_INSTALL_BOT_TOKEN
MONITOR_INSTALL_ALLOWED_USER_IDS=123456789 \
MONITOR_INSTALL_SERVER_NAME=server-01 \
MONITOR_INSTALL_TIMEZONE=Europe/Moscow \
bash install.sh --non-interactive
unset MONITOR_INSTALL_BOT_TOKEN
```

Источники: `auto` (по умолчанию), `ghcr`, `archive` или `build`; для non-interactive режима используется `MONITOR_INSTALL_SOURCE`. `deploy.sh` поддерживает `monitoring-bot-debian-amd64.tar.gz`, `.tar`, GHCR и локальную сборку.

Другой каталог для GitHub-установки задаётся так:

```bash
curl -fsSL https://raw.githubusercontent.com/artemiygaer/monitoring_bot/main/install-from-github.sh \
  | sudo MONITOR_INSTALL_DIR=/srv/monitoring-bot bash
```

## Как это работает
- Бот запускается в Docker с доступом к `/var/run/docker.sock`.
- Хост-система монтируется в `/hostfs:ro` для чтения логов и метрик.
- Для выполнения команд и бэкапов запускается временный helper-контейнер с правами `privileged`.

## Безопасность
- Доступ строго по `ALLOWED_USER_IDS`.
- `.env` создаётся атомарно с правами `600`; токен установщик не выводит.
- Все критические действия (перезапуск, команды, удаление бэкапов) требуют подтверждения.
- Бот оптимизирован для слабых серверов: Docker-запросы кешируются, блокирующий I/O ограничен двумя потоками, лимит памяти по умолчанию — 192 МБ.

[English version](README.en.md)
