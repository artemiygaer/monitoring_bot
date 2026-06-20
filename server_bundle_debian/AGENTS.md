# Памятка Для ИИ-Агента

Файл нужен агенту, который вернётся к проекту после паузы.

## Контекст

- Пользователь общается на русском и просит отвечать коротко.
- Документация и комментарии в коде должны быть на русском.
- Рабочая папка: `H:\bot\monitoring_v3`.
- Это не git-репозиторий.
- Бот запускается на удалённых Debian-серверах в Docker, не локально на Windows.
- Подготовка и тестирование выполняются локально через Docker Desktop.
- Основной compose-файл: `docker-compose.bot.yml`.
- Целевые deploy-архивы: `deploy_server1.tar.gz` и `deploy_server2.tar.gz`.
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
- сборка серверного комплекта через `build_server_bundle.ps1`;
- оптимизация ОЗУ/CPU: TTL-очистка сессий, лимит логов, потоковое чтение login-логов, лёгкий Docker API для списков контейнеров;
- Docker-образ на базе Alpine.

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
- `.env.example`, `README.md` и `build_server_bundle.ps1` — синхронизировать при новых env-переменных.

## Перед Изменениями

```powershell
Get-ChildItem -Force
rg --files -g "!__pycache__" -g "!.pytest_cache"
python -m pytest -q
```

## После Изменений

```powershell
python -m pytest -q
python -m compileall -q app tests
docker build -t monitoring-bot:debian-amd64 .
docker save -o monitoring-bot-debian-amd64.tar monitoring-bot:debian-amd64
.\build_server_bundle.ps1
docker run --rm monitoring-bot:debian-amd64 python -c "import app.main; print('image ok')"
```

Если менялся серверный комплект, обновить `deploy_server1.tar.gz` и `deploy_server2.tar.gz`, сохранив их индивидуальные `.env`.

## Если Docker Desktop Выключен

```powershell
Start-Service com.docker.service
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe" -WindowStyle Hidden
docker context use desktop-linux
docker version
```

## Правила Для Правок

- Если меняется код в `app`, пересобрать образ и bundle.
- Если добавляется env-переменная, обновить `app/config.py`, `.env.example`, `build_server_bundle.ps1` и README.
- Если меняется Telegram-меню, проверить `app/keyboards.py`, `app/handlers.py`, `app/formatters.py` и тесты.
- Если меняется серверный deploy, проверить `server_bundle_debian` через `build_server_bundle.ps1`.
