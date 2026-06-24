# Памятка Для ИИ-Агента

Файл нужен агенту, который вернётся к проекту после паузы.

## Контекст

- Пользователь общается на русском и просит отвечать коротко.
- Документация и комментарии в коде должны быть на русском.
- Рабочая папка: `H:\bot\monitoring_v3.5`.
- Это **git-репозиторий**, origin: `https://github.com/artemiygaer/monitoring_bot.git`.
- Бот запускается на удалённых Debian-серверах в Docker, не локально на Windows.
- Подготовка и тестирование выполняются локально через Docker Desktop.
- Основной compose-файл: `docker-compose.bot.yml`.
- Готовые артефакты публикуются через GitHub Actions: образ в `ghcr.io/artemiygaer/monitoring_bot`, архив `monitoring-bot-debian-amd64.tar.gz` + `SHA256SUMS.txt` в GitHub Release.
- Не выводить содержимое `.env`, Telegram token и полный вывод `docker compose config`.

## Что Реализовано

- мониторинг Docker Compose;
- системные метрики хоста;
- экран `Ресурсы` с CPU/RAM/Disk хоста и топом контейнеров по CPU/RAM;
- Docker/system/login-алерты;
- быстрая проверка входов через `MONITOR_LOGIN_POLL_SECONDS=5`;
- чтение `utmp`/`wtmp` без запуска внешней команды `who`;
- выполнение команд на хосте через временный helper-контейнер;
- сжатый бекап `/root` в `/backup/root-backup-YYYYMMDD-HHMMSS.tar.gz`;
- проверка свободного места перед созданием бекапа;
- список бекапов, скачивание выбранного архива и удаление выбранного архива;
- ручной просмотр failed login событий кнопкой `Ошибки входа`;
- экран `О боте` с версией, настройками, PID, Python, RSS/VmSize процесса и числом сессий;
- ручная очистка `__pycache__`, `.pytest_cache` и `tmp*` кнопкой `Очистка`;
- главное меню: `Сводка`, `Ресурсы`, `Контейнеры`, `Бекап`, `Команды`, `Система`, `Обновить`;
- редкие действия (`Очистка`, `Ошибки входа`, `О боте`) находятся в подменю `Система`;
- оптимизация ОЗУ/CPU: TTL-очистка сессий, лимит логов, потоковое чтение login-логов, лёгкий Docker API для списков контейнеров;
- Docker-образ на базе Alpine;
- CI через GitHub Actions: pytest + compileall, buildx → ghcr.io (linux/amd64 + linux/arm64), Release на тег `v*.*.*`;
- `deploy.sh` поддерживает три источника: tar из Release, pull из `ghcr.io`, локальная сборка из Dockerfile.

## Важные Файлы

- `app/main.py` — запуск бота и фоновых задач.
- `app/handlers.py` — Telegram-экраны и обработчики меню.
- `app/keyboards.py` — кнопки меню.
- `app/formatters.py` — форматирование сообщений.
- `app/config.py` — переменные окружения.
- `app/docker_monitor.py` — чтение Docker-сервисов, контейнеров, логов и stats.
- `app/system_monitor.py` — системные метрики хоста.
- `app/alerting.py` — Docker/system/login-алерты.
- `app/login_monitor.py` — чтение auth.log/secure, wtmp и utmp.
- `app/host_command_executor.py` — запуск helper-контейнера.
- `app/command_worker.py` — выполнение команды на хосте через `nsenter` и `chroot`.
- `app/backup.py` — список архивов, команды создания и удаления бекапа.
- `app/maintenance.py` — команда очистки временных каталогов.
- `.github/workflows/ci.yml` — pytest + compileall.
- `.github/workflows/docker.yml` — buildx → ghcr.io.
- `.github/workflows/release.yml` — Release с `.tar.gz` + `SHA256SUMS.txt`.
- `.env.example`, `README.md`, `README.en.md` — синхронизировать при новых env-переменных.
- `.gitattributes` — принудительный LF для `*.sh`, `*.yml`, `Dockerfile`, `*.md`.

## Перед Изменениями

```powershell
Get-ChildItem -Force
git status
python -m pytest -q
```

## После Изменений

```powershell
python -m pytest -q
python -m compileall -q app tests
git add -A
git status
git commit -m "<сообщение>"
git push
git tag -a vX.Y.Z -m "Release vX.Y.Z"  # только для релиза
git push origin vX.Y.Z                  # только для релиза
```

Если тег `vX.Y.Z` запушен, GitHub Actions автоматически:
- пересоберёт образ в `ghcr.io/artemiygaer/monitoring_bot:X.Y.Z` (multi-arch);
- создаст Release с артефактами `monitoring-bot-debian-amd64.tar.gz` и `SHA256SUMS.txt`.

Локальная сборка Docker больше не требуется — образ уже публикуется CI.

## Если Docker Desktop Выключен

```powershell
Start-Service com.docker.service
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe" -WindowStyle Hidden
docker context use desktop-linux
docker version
```

## Правила Для Правок

- Если меняется код в `app`, прогнать `pytest` и `compileall`, закоммитить, запушить.
- Если добавляется env-переменная, обновить `app/config.py`, `.env.example`, `README.md`, `README.en.md`.
- Если меняется Telegram-меню, проверить `app/keyboards.py`, `app/handlers.py`, `app/formatters.py` и тесты.
- Если меняется deploy, проверить `deploy.sh` и `server_bundle_debian/deploy.sh` (они должны быть идентичны).
- Если меняется CI/workflow, проверить YAML-синтаксис (`python -c "import yaml; yaml.safe_load(open('.github/workflows/X.yml'))"`).