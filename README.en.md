# Telegram Bot for Docker Compose Monitoring (V2)

Decentralized Telegram bot for monitoring Debian servers. Each server runs independently, providing full control through an isolated node.

## Key Features

- 📊 **Summary**: Overall CPU/RAM/Disk status and Docker services (includes custom server name).
- 📈 **Resources**: Host CPU/RAM/Disk and top containers by CPU/RAM in a single screen.
- 🐳 **Containers**: Container management (status, logs, statistics, restart).
- ⌨️ **Commands**: Execute any shell command on the host with confirmation.
- 🗄️ **Backup**: Create, download (up to 200 MB) and delete `/root` tar archives.
- ⚙️ **System**: Submenu for secondary functions (Cleanup, Login Errors, About).
- ℹ️ **About**: Version, build date, active settings, PID, Python, RSS/VmSize of the process and active session count.
- 🛡️ **Security**: Login notifications (SSH/tty) and authentication errors.
- 🚀 **Deploy**: Image-based delivery via `.tar` (no build on target server).

## Bottom Menu

The main menu keeps only frequent actions:

- `Summary` and `Resources` — quick state checks.
- `Containers` and `Backup` — main operations.
- `Commands` and `System` — administrative actions.
- `Refresh` — repeat the current screen.

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

## Quick Start (Deployment)

### Option A: via GitHub Release (no build on the server)

1. **Prepare**: Get a token from @BotFather.
2. **Transfer archive**: Download `monitoring-bot-debian-amd64.tar.gz` and `SHA256SUMS.txt` from the [GitHub Release](https://github.com/artemiygaer/monitoring_bot/releases/latest).
3. **Configure**: Create `.env` from `.env.example` (set token and server name).
4. **Run**:
```bash
mkdir -p /opt/monitoring-bot && cd /opt/monitoring-bot
curl -L -o monitoring-bot-debian-amd64.tar.gz https://github.com/artemiygaer/monitoring_bot/releases/latest/download/monitoring-bot-debian-amd64.tar.gz
curl -L -o SHA256SUMS.txt https://github.com/artemiygaer/monitoring_bot/releases/latest/download/SHA256SUMS.txt
curl -L -o docker-compose.bot.yml https://raw.githubusercontent.com/artemiygaer/monitoring_bot/main/docker-compose.bot.yml
sha256sum -c SHA256SUMS.txt
bash deploy.sh
```

### Option B: via git clone (image is pulled from ghcr.io)

```bash
git clone https://github.com/artemiygaer/monitoring_bot.git /opt/monitoring-bot
cd /opt/monitoring-bot
cp .env.example .env
nano .env   # set BOT_TOKEN, ALLOWED_USER_IDS, MONITOR_SERVER_NAME
bash deploy.sh
```

`deploy.sh` auto-detects the source: if `monitoring-bot-debian-amd64.tar` is present, it loads it; otherwise it pulls `ghcr.io/artemiygaer/monitoring_bot:latest`.

## How It Works
- The bot runs in Docker with access to `/var/run/docker.sock`.
- The host filesystem is mounted to `/hostfs:ro` for reading logs and metrics.
- For executing commands and backups, a temporary helper container with `privileged` rights is launched.

## Security
- Access is strictly by `ALLOWED_USER_IDS`.
- All critical actions (restart, commands, backup deletion) require confirmation.
- The bot is optimized for weak servers (RAM limit ~100 MB).

See also: [Russian version](README.md), [English Security Policy](SECURITY.en.md).