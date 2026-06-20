#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "Проверяю наличие Docker..."
command -v docker >/dev/null 2>&1 || {
  echo "Docker не найден. Установи Docker и Docker Compose plugin."
  exit 1
}

if [ -f SHA256SUMS.txt ]; then
  echo "Проверяю контрольную сумму архива..."
  sha256sum -c SHA256SUMS.txt
fi

echo "Загружаю Docker-образ..."
docker load -i monitoring-bot-debian-amd64.tar

echo "Останавливаю старый контейнер..."
docker compose -f docker-compose.bot.yml down --remove-orphans

echo "Запускаю контейнер бота..."
docker compose -f docker-compose.bot.yml up -d --no-build --force-recreate

echo "Текущее состояние:"
docker compose -f docker-compose.bot.yml ps
