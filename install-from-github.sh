#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="artemiygaer/monitoring_bot"
INSTALL_DIR="${MONITOR_INSTALL_DIR:-/opt/monitoring-bot}"
RELEASE_BASE="${MONITOR_GITHUB_RELEASE_BASE:-https://github.com/${REPOSITORY}/releases/latest/download}"
REQUESTED_SOURCE="${MONITOR_INSTALL_SOURCE:-auto}"
ARCHIVE_NAME="monitoring-bot-debian-amd64.tar.gz"

fail() {
  echo "Ошибка: $*" >&2
  exit 1
}

download_file() {
  local name="$1"
  local destination="$INSTALL_DIR/$name"
  local temporary

  temporary="$(mktemp "$INSTALL_DIR/.${name}.tmp.XXXXXX")"
  if ! curl --fail --location --silent --show-error \
    --retry 3 --connect-timeout 15 \
    "$RELEASE_BASE/$name" \
    --output "$temporary"; then
    rm -f -- "$temporary"
    fail "не удалось скачать $name из GitHub Release"
  fi
  chmod 600 "$temporary"
  mv -f -- "$temporary" "$destination"
}

command -v curl >/dev/null 2>&1 ||
  fail "curl не найден. Установи curl и повтори запуск."
command -v sha256sum >/dev/null 2>&1 ||
  fail "sha256sum не найден. Установи coreutils и повтори запуск."

case "$REQUESTED_SOURCE" in
  auto|ghcr|archive) ;;
  *) fail "для установки из GitHub допустим источник auto, ghcr или archive" ;;
esac

architecture="$(uname -m)"
case "$architecture" in
  x86_64|amd64)
    download_archive=true
    ;;
  aarch64|arm64)
    [[ "$REQUESTED_SOURCE" != "archive" ]] ||
      fail "release-архив доступен только для amd64; используй MONITOR_INSTALL_SOURCE=ghcr"
    download_archive=false
    ;;
  *)
    fail "архитектура $architecture не поддерживается"
    ;;
esac

if [[ ! -d "$INSTALL_DIR" ]]; then
  mkdir -p -- "$INSTALL_DIR" 2>/dev/null ||
    fail "не удалось создать $INSTALL_DIR; запусти команду через sudo или задай MONITOR_INSTALL_DIR"
fi
[[ -w "$INSTALL_DIR" ]] ||
  fail "нет прав на запись в $INSTALL_DIR; запусти команду через sudo"

echo "Скачиваю установщик из GitHub Release..."
for file in install.sh deploy.sh docker-compose.bot.yml .env.example; do
  download_file "$file"
done

if [[ "$download_archive" == "true" && "$REQUESTED_SOURCE" != "ghcr" ]]; then
  download_file "$ARCHIVE_NAME"
  download_file "SHA256SUMS.txt"
  (
    cd "$INSTALL_DIR"
    sha256sum -c SHA256SUMS.txt
  ) || fail "контрольная сумма release-архива не совпала"
fi

chmod 755 "$INSTALL_DIR/install.sh" "$INSTALL_DIR/deploy.sh"

echo "Файлы GitHub Release сохранены в $INSTALL_DIR."
cd "$INSTALL_DIR"
MONITOR_INSTALL_SOURCE="$REQUESTED_SOURCE" bash ./install.sh
