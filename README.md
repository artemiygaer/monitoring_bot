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
- 🗄️ **Бекап**: Создание, скачивание (до 200МБ) и удаление tar-архивов `/root`.
- ⚙️ **Система**: Подменю для второстепенных функций (Очистка, Ошибки входа, О боте).
- ℹ️ **О боте**: Версия, дата сборки, активные настройки, PID, Python, RSS/VmSize процесса и число активных сессий.
- 🛡️ **Безопасность**: Уведомления о входах (SSH/tty) и ошибки авторизации.
- 🚀 **Деплой**: Image-based доставка через `.tar` (никакой сборки на целевом сервере).

## Нижнее меню

Главное меню держит только частые действия:

- `Сводка` и `Ресурсы` — быстрый контроль состояния.
- `Контейнеры` и `Бекап` — основные операции.
- `Команды` и `Система` — административные действия.
- `Обновить` — повтор текущего экрана.

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

## Быстрый старт (Развертывание)

### Вариант A: через GitHub Release (без сборки на сервере)

1. **Подготовка**: Получите токен у @BotFather.
2. **Перенос архива**: Скачайте `monitoring-bot-debian-amd64.tar.gz` и `SHA256SUMS.txt` из [GitHub Release](https://github.com/artemiygaer/monitoring_bot/releases/latest).
3. **Настройка**: Создайте `.env` из `.env.example` (укажите токен и имя сервера).
4. **Запуск**:
```bash
mkdir -p /opt/monitoring-bot && cd /opt/monitoring-bot
curl -L -o monitoring-bot-debian-amd64.tar.gz https://github.com/artemiygaer/monitoring_bot/releases/latest/download/monitoring-bot-debian-amd64.tar.gz
curl -L -o SHA256SUMS.txt https://github.com/artemiygaer/monitoring_bot/releases/latest/download/SHA256SUMS.txt
curl -L -o docker-compose.bot.yml https://raw.githubusercontent.com/artemiygaer/monitoring_bot/main/docker-compose.bot.yml
sha256sum -c SHA256SUMS.txt
bash deploy.sh
```

### Вариант B: через git clone (образ подтянется из ghcr.io)

```bash
git clone https://github.com/artemiygaer/monitoring_bot.git /opt/monitoring-bot
cd /opt/monitoring-bot
cp .env.example .env
nano .env   # укажите BOT_TOKEN, ALLOWED_USER_IDS, MONITOR_SERVER_NAME
bash deploy.sh
```

`deploy.sh` сам определит способ: если рядом есть `monitoring-bot-debian-amd64.tar` — загрузит его, иначе попробует `docker pull ghcr.io/artemiygaer/monitoring_bot:latest`.

## Как это работает
- Бот запускается в Docker с доступом к `/var/run/docker.sock`.
- Хост-система монтируется в `/hostfs:ro` для чтения логов и метрик.
- Для выполнения команд и бэкапов запускается временный helper-контейнер с правами `privileged`.

## Безопасность
- Доступ строго по `ALLOWED_USER_IDS`.
- Все критические действия (перезапуск, команды, удаление бэкапов) требуют подтверждения.
- Бот оптимизирован для работы на слабых серверах (лимит ОЗУ ~100МБ).

[English version](README.en.md)
