#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

REPO="artemiygaer/monitoring_bot"
IMAGE="monitoring-bot:debian-amd64"
GHCR_IMAGE="ghcr.io/${REPO}:latest"

echo "Проверяю наличие Docker..."
command -v docker >/dev/null 2>&1 || {
  echo "Docker не найден. Установи Docker и Docker Compose plugin."
  exit 1
}

if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    echo "Создан .env из .env.example. Отредактируй его перед запуском."
  else
    echo "Не найден ни .env, ни .env.example."
    exit 1
  fi
fi

if [ -f SHA256SUMS.txt ] && [ -f monitoring-bot-debian-amd64.tar ]; then
  echo "Проверяю контрольную сумму архива..."
  sha256sum -c SHA256SUMS.txt
fi

ensure_image() {
  if docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Образ $IMAGE уже загружен."
    return 0
  fi

  if [ -f monitoring-bot-debian-amd64.tar ]; then
    echo "Загружаю образ из monitoring-bot-debian-amd64.tar..."
    docker load -i monitoring-bot-debian-amd64.tar
  elif [ -f Dockerfile ]; then
    echo "Локальный образ не найден. Тяну $GHCR_IMAGE из GitHub Container Registry..."
    if docker pull "$GHCR_IMAGE"; then
      docker tag "$GHCR_IMAGE" "$IMAGE"
    else
      echo "Pull не удался. Собираю образ локально из Dockerfile..."
      docker build -t "$IMAGE" .
    fi
  else
    echo "Не найден ни monitoring-bot-debian-amd64.tar, ни Dockerfile."
    echo "Положи архив из GitHub Release рядом со скриптом или запусти из клона репозитория."
    exit 1
  fi
}

ensure_image

echo "Останавливаю старый контейнер..."
docker compose -f docker-compose.bot.yml down --remove-orphans

echo "Запускаю контейнер бота..."
docker compose -f docker-compose.bot.yml up -d --no-build --force-recreate

echo "Текущее состояние:"
docker compose -f docker-compose.bot.yml ps