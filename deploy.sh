#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

REPO="artemiygaer/monitoring_bot"
LOCAL_IMAGE="monitoring-bot:debian-amd64"
GHCR_IMAGE="ghcr.io/${REPO}:latest"
SOURCE="${DEPLOY_SOURCE:-auto}"
GZIP_ARCHIVE="monitoring-bot-debian-amd64.tar.gz"
TAR_ARCHIVE="monitoring-bot-debian-amd64.tar"

fail() {
  echo "Ошибка: $*" >&2
  exit 1
}

[[ -w . ]] || fail "нет прав на запись в каталог установки: $(pwd)"
[[ -f docker-compose.bot.yml ]] || fail "не найден docker-compose.bot.yml"
[[ -f .env ]] || fail "не найден .env; сначала запусти: bash install.sh --config-only"

command -v docker >/dev/null 2>&1 ||
  fail "Docker не найден. Установи Docker Engine и Compose plugin."
docker info >/dev/null 2>&1 ||
  fail "Docker daemon недоступен. Проверь сервис Docker и права пользователя."
docker compose version >/dev/null 2>&1 ||
  fail "Docker Compose plugin недоступен. Нужна команда «docker compose»."

architecture="$(uname -m)"
case "$architecture" in
  x86_64|amd64|aarch64|arm64) ;;
  *) fail "архитектура $architecture не поддерживается" ;;
esac

case "$SOURCE" in
  auto|ghcr|archive|build) ;;
  *) fail "неизвестный источник $SOURCE; допустимо: auto, ghcr, archive, build" ;;
esac

verify_checksum() {
  local archive="$1"
  if [[ ! -f SHA256SUMS.txt ]]; then
    echo "Предупреждение: SHA256SUMS.txt отсутствует, checksum не проверен." >&2
    return 0
  fi
  grep -E "[[:space:]]$(basename "$archive")$" SHA256SUMS.txt |
    sha256sum -c - ||
    fail "контрольная сумма $(basename "$archive") не совпала"
}

load_archive() {
  local archive=""
  if [[ -f "$GZIP_ARCHIVE" ]]; then
    archive="$GZIP_ARCHIVE"
  elif [[ -f "$TAR_ARCHIVE" ]]; then
    archive="$TAR_ARCHIVE"
  else
    fail "не найден $GZIP_ARCHIVE или $TAR_ARCHIVE"
  fi

  case "$architecture" in
    x86_64|amd64) ;;
    *) fail "release-архив предназначен для amd64; для $architecture используй GHCR" ;;
  esac

  echo "Проверяю архив $(basename "$archive")..."
  verify_checksum "$archive"
  if [[ "$archive" == *.tar.gz ]]; then
    echo "Загружаю сжатый Docker-образ..."
    gzip -dc -- "$archive" | docker load
  else
    echo "Загружаю Docker-образ..."
    docker load -i "$archive"
  fi
}

pull_ghcr() {
  echo "Загружаю $GHCR_IMAGE..."
  docker pull "$GHCR_IMAGE"
  docker tag "$GHCR_IMAGE" "$LOCAL_IMAGE"
}

build_local() {
  [[ -f Dockerfile ]] || fail "для локальной сборки не найден Dockerfile"
  echo "Собираю $LOCAL_IMAGE локально..."
  docker build -t "$LOCAL_IMAGE" .
}

if [[ "$SOURCE" == "archive" ]]; then
  load_archive
elif [[ "$SOURCE" == "ghcr" ]]; then
  pull_ghcr
elif [[ "$SOURCE" == "build" ]]; then
  build_local
elif [[ -f "$GZIP_ARCHIVE" || -f "$TAR_ARCHIVE" ]]; then
  load_archive
elif ! pull_ghcr; then
  echo "GHCR недоступен, пробую локальную сборку." >&2
  build_local
fi

docker image inspect "$LOCAL_IMAGE" >/dev/null 2>&1 ||
  fail "образ $LOCAL_IMAGE не найден после подготовки"

echo "Проверяю Compose-конфигурацию..."
docker compose -f docker-compose.bot.yml config --quiet

echo "Запускаю бота..."
docker compose -f docker-compose.bot.yml up -d --no-build --force-recreate --remove-orphans
docker compose -f docker-compose.bot.yml ps
