#!/usr/bin/env bash
set -euo pipefail

CONFIG_ONLY=false
NON_INTERACTIVE=false
INSTALL_DIR="$(pwd)"
ENV_FILE=""
PROMPT_INPUT="/dev/stdin"

usage() {
  cat <<'EOF'
Использование: bash install.sh [параметры]

  --config-only       только создать или обновить .env
  --non-interactive   взять значения из MONITOR_INSTALL_* или существующего .env
  --install-dir PATH  каталог установки (по умолчанию текущий)
  --env-file PATH     путь к .env относительно каталога установки
  -h, --help          показать справку

Токен нельзя передавать аргументом. Для автоматизации используй
MONITOR_INSTALL_BOT_TOKEN или заранее созданный .env.
EOF
}

fail() {
  echo "Ошибка: $*" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    --config-only)
      CONFIG_ONLY=true
      shift
      ;;
    --non-interactive)
      NON_INTERACTIVE=true
      shift
      ;;
    --install-dir)
      (($# >= 2)) || fail "для --install-dir нужен путь"
      INSTALL_DIR="$2"
      shift 2
      ;;
    --env-file)
      (($# >= 2)) || fail "для --env-file нужен путь"
      ENV_FILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "неизвестный параметр: $1"
      ;;
  esac
done

if [[ "$NON_INTERACTIVE" != "true" && -r /dev/tty ]]; then
  PROMPT_INPUT="/dev/tty"
fi

[[ -d "$INSTALL_DIR" ]] || fail "каталог установки не найден: $INSTALL_DIR"
[[ -w "$INSTALL_DIR" ]] || fail "нет прав на запись в каталог установки: $INSTALL_DIR"
cd "$INSTALL_DIR"

if [[ -z "$ENV_FILE" ]]; then
  ENV_FILE=".env"
fi
ENV_DIR="$(dirname "$ENV_FILE")"
[[ -d "$ENV_DIR" ]] || fail "каталог для .env не найден: $ENV_DIR"
[[ -w "$ENV_DIR" ]] || fail "нет прав на запись в каталог для .env: $ENV_DIR"

read_env() {
  local key="$1"
  [[ -f "$ENV_FILE" ]] || return 0
  awk -F= -v wanted="$key" '
    $1 == wanted {
      sub(/^[^=]*=/, "")
      sub(/\r$/, "")
      print
      exit
    }
  ' "$ENV_FILE"
}

read_first_env() {
  local key value
  for key in "$@"; do
    value="$(read_env "$key")"
    if [[ -n "$value" ]]; then
      printf '%s' "$value"
      return 0
    fi
  done
}

prompt_visible() {
  local label="$1"
  local default_value="$2"
  local required="$3"
  local entered

  while true; do
    if [[ -n "$default_value" ]]; then
      printf '%s [%s]: ' "$label" "$default_value" >&2
    else
      printf '%s: ' "$label" >&2
    fi
    if ! IFS= read -r entered < "$PROMPT_INPUT"; then
      fail "интерактивный ввод недоступен; используй --non-interactive"
    fi
    entered="${entered:-$default_value}"
    if [[ "$required" != "true" || -n "$entered" ]]; then
      REPLY_VALUE="$entered"
      return 0
    fi
    echo "Значение обязательно." >&2
  done
}

prompt_secret() {
  local has_existing="$1"
  local entered

  while true; do
    if [[ "$has_existing" == "true" ]]; then
      printf 'Токен Telegram [Enter — оставить текущий]: ' >&2
    else
      printf 'Токен Telegram: ' >&2
    fi
    if ! IFS= read -r -s entered < "$PROMPT_INPUT"; then
      fail "интерактивный ввод недоступен; используй --non-interactive"
    fi
    echo >&2
    if [[ -n "$entered" ]]; then
      REPLY_VALUE="$entered"
      return 0
    fi
    if [[ "$has_existing" == "true" ]]; then
      REPLY_VALUE=""
      return 0
    fi
    echo "Токен обязателен." >&2
  done
}

normalize_ids() {
  printf '%s' "$1" | tr -d '[:space:]'
}

validate_token() {
  [[ "$1" =~ ^[0-9]+:[A-Za-z0-9_-]{20,}$ ]] ||
    fail "токен Telegram имеет неверный формат"
}

validate_ids() {
  [[ "$1" =~ ^[0-9]+(,[0-9]+)*$ ]] ||
    fail "ID должны быть числами через запятую"
}

validate_server_name() {
  [[ -n "$1" && ${#1} -le 64 && "$1" != *$'\n'* ]] ||
    fail "имя сервера должно содержать от 1 до 64 символов"
}

validate_timezone() {
  [[ "$1" =~ ^[A-Za-z0-9._+-]+(/[A-Za-z0-9._+-]+)*$ ]] ||
    fail "timezone имеет неверный формат"
  if [[ -d /usr/share/zoneinfo && ! -f "/usr/share/zoneinfo/$1" ]]; then
    fail "timezone не найден в /usr/share/zoneinfo: $1"
  fi
}

existing_token="$(read_first_env BOT_TOKEN TELEGRAM_BOT_TOKEN)"
existing_ids="$(read_first_env ALLOWED_USER_IDS TELEGRAM_ALLOWED_USER_IDS)"
existing_server="$(read_env MONITOR_SERVER_NAME)"
existing_timezone="$(read_env MONITOR_TIMEZONE)"
existing_project="$(read_env MONITOR_DOCKER_PROJECT)"
existing_alert_ids="$(read_first_env MONITOR_ALERT_CHAT_IDS ALERT_CHAT_IDS)"
existing_notify="$(read_env MONITOR_NOTIFY_ON_STARTUP)"

if [[ "$NON_INTERACTIVE" == "true" ]]; then
  bot_token="${MONITOR_INSTALL_BOT_TOKEN:-$existing_token}"
  allowed_ids="${MONITOR_INSTALL_ALLOWED_USER_IDS:-$existing_ids}"
  server_name="${MONITOR_INSTALL_SERVER_NAME:-$existing_server}"
  timezone="${MONITOR_INSTALL_TIMEZONE:-${existing_timezone:-Europe/Moscow}}"
  docker_project="${MONITOR_INSTALL_DOCKER_PROJECT:-$existing_project}"
  alert_ids="${MONITOR_INSTALL_ALERT_CHAT_IDS:-${existing_alert_ids:-$allowed_ids}}"
  notify_startup="${MONITOR_INSTALL_NOTIFY_ON_STARTUP:-${existing_notify:-false}}"
  install_source="${MONITOR_INSTALL_SOURCE:-auto}"
else
  prompt_secret "$([[ -n "$existing_token" ]] && echo true || echo false)"
  bot_token="${REPLY_VALUE:-$existing_token}"
  prompt_visible "Telegram ID пользователей (через запятую)" "$existing_ids" true
  allowed_ids="$REPLY_VALUE"
  prompt_visible "Имя сервера" "${existing_server:-$(hostname -s 2>/dev/null || echo server)}" true
  server_name="$REPLY_VALUE"
  prompt_visible "Timezone" "${existing_timezone:-Europe/Moscow}" true
  timezone="$REPLY_VALUE"
  prompt_visible "Docker Compose project (пусто — все)" "$existing_project" false
  docker_project="$REPLY_VALUE"
  prompt_visible "ID для алертов" "${existing_alert_ids:-$allowed_ids}" true
  alert_ids="$REPLY_VALUE"
  prompt_visible "Уведомлять о старте: true/false" "${existing_notify:-false}" true
  notify_startup="$REPLY_VALUE"
  prompt_visible "Источник образа: auto/ghcr/archive/build" "${MONITOR_INSTALL_SOURCE:-auto}" true
  install_source="$REPLY_VALUE"
fi

allowed_ids="$(normalize_ids "$allowed_ids")"
alert_ids="$(normalize_ids "$alert_ids")"
[[ -n "$bot_token" ]] || fail "не задан токен Telegram"
[[ -n "$allowed_ids" ]] || fail "не заданы разрешённые Telegram ID"
validate_token "$bot_token"
validate_ids "$allowed_ids"
validate_ids "$alert_ids"
validate_server_name "$server_name"
validate_timezone "$timezone"
[[ "$notify_startup" == "true" || "$notify_startup" == "false" ]] ||
  fail "MONITOR_NOTIFY_ON_STARTUP должен быть true или false"
case "$install_source" in
  auto|ghcr|archive|build) ;;
  *) fail "источник должен быть auto, ghcr, archive или build" ;;
esac

umask 077
if [[ -f "$ENV_FILE" ]]; then
  backup_path="${ENV_FILE}.backup-$(date +%Y%m%d-%H%M%S)"
  if [[ -e "$backup_path" ]]; then
    backup_path="${backup_path}-$$"
  fi
  cp -p -- "$ENV_FILE" "$backup_path"
  chmod 600 "$backup_path"
  echo "Создана резервная копия: $backup_path"
fi

temp_env="$(mktemp "${ENV_FILE}.tmp.XXXXXX")"
trap 'rm -f -- "$temp_env"' EXIT
known_keys="BOT_TOKEN,TELEGRAM_BOT_TOKEN,ALLOWED_USER_IDS,TELEGRAM_ALLOWED_USER_IDS,MONITOR_SERVER_NAME,MONITOR_TIMEZONE,MONITOR_DOCKER_PROJECT,MONITOR_ALERT_CHAT_IDS,ALERT_CHAT_IDS,MONITOR_NOTIFY_ON_STARTUP,MONITORING_BOT_IMAGE"
if [[ -f "$ENV_FILE" ]]; then
  awk -F= -v keys="$known_keys" '
    BEGIN {
      count = split(keys, list, ",")
      for (item = 1; item <= count; item++) known[list[item]] = 1
    }
    /^[A-Za-z_][A-Za-z0-9_]*=/ {
      if (known[$1]) next
    }
    { sub(/\r$/, ""); print }
  ' "$ENV_FILE" > "$temp_env"
fi

{
  [[ ! -s "$temp_env" ]] || echo
  printf 'BOT_TOKEN=%s\n' "$bot_token"
  printf 'ALLOWED_USER_IDS=%s\n' "$allowed_ids"
  printf 'MONITOR_SERVER_NAME=%s\n' "$server_name"
  printf 'MONITOR_TIMEZONE=%s\n' "$timezone"
  printf 'MONITOR_DOCKER_PROJECT=%s\n' "$docker_project"
  printf 'MONITOR_ALERT_CHAT_IDS=%s\n' "$alert_ids"
  printf 'MONITOR_NOTIFY_ON_STARTUP=%s\n' "$notify_startup"
  printf 'MONITORING_BOT_IMAGE=%s\n' "monitoring-bot:debian-amd64"
} >> "$temp_env"

chmod 600 "$temp_env"
mv -f -- "$temp_env" "$ENV_FILE"
chmod 600 "$ENV_FILE"
trap - EXIT

echo "Конфигурация сохранена: $ENV_FILE (права 600)"
echo "Токен Telegram: настроен (значение скрыто)"
echo "Сервер: $server_name; timezone: $timezone; пользователи: $allowed_ids"

if [[ "$CONFIG_ONLY" == "true" ]]; then
  echo "Режим config-only завершён."
  exit 0
fi

[[ -f deploy.sh ]] || fail "в каталоге установки не найден deploy.sh"
DEPLOY_SOURCE="$install_source" bash ./deploy.sh
