# Telegram Bot for Docker Compose Monitoring (V2)

[![CI](https://github.com/artemiygaer/monitoring_bot/actions/workflows/ci.yml/badge.svg)](https://github.com/artemiygaer/monitoring_bot/actions/workflows/ci.yml)
[![Docker](https://github.com/artemiygaer/monitoring_bot/actions/workflows/docker.yml/badge.svg)](https://github.com/artemiygaer/monitoring_bot/actions/workflows/docker.yml)
[![Release](https://img.shields.io/github/v/release/artemiygaer/monitoring_bot)](https://github.com/artemiygaer/monitoring_bot/releases/latest)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
[![Docker Image](https://ghcr.io/artemiygaer/monitoring_bot)](https://github.com/artemiygaer/monitoring_bot/pkgs/container/monitoring_bot)
![Python](https://img.shields.io/badge/python-3.12-blue)
![Platform](https://img.shields.io/badge/platform-Debian%20%2F%20Linux-blue)

Decentralized Telegram bot for monitoring Debian servers. Each server runs independently, providing full control through an isolated node.

## Key Features

- 📊 **Summary**: Overall CPU/RAM/Disk status and Docker services (includes custom server name).
- 📈 **Resources**: Host CPU/RAM/Disk and top containers by CPU/RAM in a single screen.
- 🐳 **Containers**: Container management (status, logs, statistics, restart).
- ⌨️ **Commands**: Execute any shell command on the host with confirmation.
- 🗄️ **Backup**: Create, download (up to 50 MiB) and delete `/root` tar archives.
- ⚙️ **System**: Submenu for secondary functions (Cleanup, Login Errors, About).
- ℹ️ **About**: Version, build date, active settings, PID, Python, RSS/VmSize of the process and active session count.
- 🛡️ **Security**: Login notifications (SSH/tty) and authentication errors.
- 🚀 **Deploy**: Prebuilt image from GHCR, `.tar.gz`, or `.tar`; local build is a fallback.

## Bottom Menu

The main menu keeps only frequent actions:

- `Summary` and `Resources` — quick state checks.
- `Containers` and `Backup` — main operations.
- `Commands` and `System` — administrative actions.
- `Refresh data` — repeat the current screen.

Rare actions are moved to `System` so the bottom keyboard is not overloaded.

## Output Types

- `Summary` shows a short Docker Compose status and system minimum.
- `Resources` shows host metrics and top containers by CPU/RAM.
- `Containers` shows state, healthcheck, image, logs, statistics and restart.
- `About` shows diagnostic data of the bot process itself.

## Environment Variables (.env)

| Variable | Description |
| :--- | :--- |
| `BOT_TOKEN` | Your Telegram bot token. |
| `ALLOWED_USER_IDS` | Comma-separated user IDs that have access. |
| `MONITOR_SERVER_NAME` | Friendly server name (shown in summary instead of ID). |
| `MONITOR_TIMEZONE` | Timezone (e.g., `Europe/Moscow`). |
| `MONITOR_BACKUP_SOURCE_DIR` | What to back up (default `/root`). |
| `MONITOR_BACKUP_TARGET_DIR` | Where to store backups (default `/backup`). |
| `MONITOR_DOCKER_CACHE_SECONDS` | Container inventory TTL, 3 seconds by default. |
| `MONITOR_STATS_CACHE_SECONDS` | Container statistics TTL, 10 seconds by default. |
| `MONITOR_IO_WORKERS` | Blocking I/O worker count, 2 by default. |
| `MONITOR_CONTAINER_MEMORY_LIMIT` | Container memory limit, `192m` by default. |
| `MONITOR_CONTAINER_CPU_LIMIT` | Container CPU limit, `0.5` by default. |
| `MONITOR_CONTAINER_PIDS_LIMIT` | Container process limit, 64 by default. |

## Quick Start (Deployment)

### Option A: via GitHub Release (no build on the server)

Docker Engine and the Compose plugin must already be installed on Debian. The installer does not change APT sources or install Docker.

Install the latest Release with one command:

```bash
curl -fsSL https://raw.githubusercontent.com/artemiygaer/monitoring_bot/main/install-from-github.sh | sudo bash
```

The script downloads public Release files to `/opt/monitoring-bot`, verifies the image checksum, and starts interactive configuration. ARM64 automatically uses the multi-arch GHCR image.

Manual download of the same files:

```bash
mkdir -p /opt/monitoring-bot && cd /opt/monitoring-bot
base_url="https://github.com/artemiygaer/monitoring_bot/releases/latest/download"
for file in monitoring-bot-debian-amd64.tar.gz SHA256SUMS.txt install-from-github.sh install.sh deploy.sh docker-compose.bot.yml; do
  curl -fL -O "$base_url/$file"
done
curl -fL "$base_url/default.env.example" -o .env.example
chmod +x install-from-github.sh install.sh deploy.sh
sha256sum -c SHA256SUMS.txt
bash install.sh
```

### Option B: via git clone (image is pulled from ghcr.io)

```bash
git clone https://github.com/artemiygaer/monitoring_bot.git /opt/monitoring-bot
cd /opt/monitoring-bot
bash install.sh
```

`install.sh` securely prompts for the token, validates numeric Telegram IDs, server name, timezone, and image source. An existing `.env` is copied to `.env.backup-YYYYMMDD-HHMMSS`; unknown keys are preserved and known keys are replaced without duplicates. The resulting `.env` has mode `600`.

Configure without deploying:

```bash
bash install.sh --config-only
```

For automation, use `--non-interactive`. Pass the token through the environment, never as a process argument:

```bash
read -rsp "Telegram token: " MONITOR_INSTALL_BOT_TOKEN && echo
export MONITOR_INSTALL_BOT_TOKEN
MONITOR_INSTALL_ALLOWED_USER_IDS=123456789 \
MONITOR_INSTALL_SERVER_NAME=server-01 \
MONITOR_INSTALL_TIMEZONE=Europe/Moscow \
bash install.sh --non-interactive
unset MONITOR_INSTALL_BOT_TOKEN
```

Supported sources are `auto` (default), `ghcr`, `archive`, and `build`; set `MONITOR_INSTALL_SOURCE` in non-interactive mode. `deploy.sh` supports `monitoring-bot-debian-amd64.tar.gz`, `.tar`, GHCR, and local Docker builds.

Use another directory for GitHub installation:

```bash
curl -fsSL https://raw.githubusercontent.com/artemiygaer/monitoring_bot/main/install-from-github.sh \
  | sudo MONITOR_INSTALL_DIR=/srv/monitoring-bot bash
```

## How It Works
- The bot runs in Docker with access to `/var/run/docker.sock`.
- The host filesystem is mounted to `/hostfs:ro` for reading logs and metrics.
- For executing commands and backups, a temporary helper container with `privileged` rights is launched.

## Security
- Access is strictly by `ALLOWED_USER_IDS`.
- `.env` is written atomically with mode `600`; the installer never prints the token.
- All critical actions (restart, commands, backup deletion) require confirmation.
- The bot is optimized for weak servers: Docker requests are cached, blocking I/O uses two bounded workers, and the default memory limit is 192 MB.

See also: [Russian version](README.md), [English Security Policy](SECURITY.en.md).
