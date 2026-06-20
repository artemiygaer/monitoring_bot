param(
    [string]$BundleDir = "server_bundle_debian",
    [string]$ZipPath = "server_bundle_debian.zip"
)

$ErrorActionPreference = "Stop"

function Has-EnvVar {
    param(
        [string[]]$Lines,
        [string]$Key
    )

    return [bool]($Lines | Where-Object { $_ -match "^\s*$([regex]::Escape($Key))=" } | Select-Object -First 1)
}

function Get-EnvValue {
    param(
        [string[]]$Lines,
        [string[]]$Keys
    )

    foreach ($key in $Keys) {
        $match = $Lines | Where-Object { $_ -match "^\s*$([regex]::Escape($key))=(.*)$" } | Select-Object -First 1
        if ($match) {
            return ($match -split "=", 2)[1]
        }
    }

    return $null
}

$bundlePath = Join-Path (Get-Location) $BundleDir
$zipFullPath = Join-Path (Get-Location) $ZipPath

if (Test-Path $bundlePath) {
    Remove-Item $bundlePath -Recurse -Force
}

New-Item -ItemType Directory -Path $bundlePath | Out-Null

Copy-Item docker-compose.bot.yml (Join-Path $bundlePath "docker-compose.bot.yml") -Force
Copy-Item monitoring-bot-debian-amd64.tar (Join-Path $bundlePath "monitoring-bot-debian-amd64.tar") -Force
Copy-Item README.md (Join-Path $bundlePath "README.md") -Force
Copy-Item deploy.sh (Join-Path $bundlePath "deploy.sh") -Force
Copy-Item .env.example (Join-Path $bundlePath ".env.example") -Force
if (Test-Path "AGENTS.md") {
    Copy-Item AGENTS.md (Join-Path $bundlePath "AGENTS.md") -Force
}

$envLines = @()
if (-not (Test-Path ".env")) {
    throw "Файл '.env' не найден."
}
$envLines += Get-Content ".env"
$allowedIds = Get-EnvValue $envLines @("TELEGRAM_ALLOWED_USER_IDS", "ALLOWED_USER_IDS")
$buildDate = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")

if (-not (Has-EnvVar $envLines "MONITORING_BOT_IMAGE")) { $envLines += "MONITORING_BOT_IMAGE=monitoring-bot:debian-amd64" }
if (-not (Has-EnvVar $envLines "MONITOR_BOT_VERSION")) { $envLines += "MONITOR_BOT_VERSION=local" }
if (-not (Has-EnvVar $envLines "MONITOR_BOT_BUILD_DATE")) { $envLines += "MONITOR_BOT_BUILD_DATE=$buildDate" }
if (-not (Has-EnvVar $envLines "MONITOR_EXCLUDED_SERVICES")) { $envLines += "MONITOR_EXCLUDED_SERVICES=monitoring-bot" }
if (-not (Has-EnvVar $envLines "MONITOR_DOCKER_BASE_URL")) { $envLines += "MONITOR_DOCKER_BASE_URL=unix:///var/run/docker.sock" }
if (-not (Has-EnvVar $envLines "MONITOR_RESTART_TIMEOUT_SECONDS")) { $envLines += "MONITOR_RESTART_TIMEOUT_SECONDS=15" }
if (-not (Has-EnvVar $envLines "MONITOR_DEFAULT_LOGS_TAIL")) { $envLines += "MONITOR_DEFAULT_LOGS_TAIL=200" }
if (-not (Has-EnvVar $envLines "MONITOR_MAX_LOGS_TAIL")) { $envLines += "MONITOR_MAX_LOGS_TAIL=1000" }
if (-not (Has-EnvVar $envLines "MONITOR_MAX_INLINE_LOG_CHARS")) { $envLines += "MONITOR_MAX_INLINE_LOG_CHARS=3000" }
if (-not (Has-EnvVar $envLines "MONITOR_COMMAND_TIMEOUT_SECONDS")) { $envLines += "MONITOR_COMMAND_TIMEOUT_SECONDS=20" }
if (-not (Has-EnvVar $envLines "MONITOR_COMMAND_MAX_OUTPUT_CHARS")) { $envLines += "MONITOR_COMMAND_MAX_OUTPUT_CHARS=12000" }
if (-not (Has-EnvVar $envLines "MONITOR_BACKUP_SOURCE_DIR")) { $envLines += "MONITOR_BACKUP_SOURCE_DIR=/root" }
if (-not (Has-EnvVar $envLines "MONITOR_BACKUP_TARGET_DIR")) { $envLines += "MONITOR_BACKUP_TARGET_DIR=/backup" }
if (-not (Has-EnvVar $envLines "MONITOR_BACKUP_TIMEOUT_SECONDS")) { $envLines += "MONITOR_BACKUP_TIMEOUT_SECONDS=600" }
if (-not (Has-EnvVar $envLines "MONITOR_CLEANUP_PATH")) { $envLines += "MONITOR_CLEANUP_PATH=/opt/monitoring-bot" }
if (-not (Has-EnvVar $envLines "MONITOR_CLEANUP_TIMEOUT_SECONDS")) { $envLines += "MONITOR_CLEANUP_TIMEOUT_SECONDS=60" }
if (-not (Has-EnvVar $envLines "MONITOR_ALERT_POLL_SECONDS")) { $envLines += "MONITOR_ALERT_POLL_SECONDS=30" }
if (-not (Has-EnvVar $envLines "MONITOR_LOGIN_POLL_SECONDS")) { $envLines += "MONITOR_LOGIN_POLL_SECONDS=5" }
if (-not (Has-EnvVar $envLines "MONITOR_NOTIFY_ON_STARTUP")) { $envLines += "MONITOR_NOTIFY_ON_STARTUP=false" }
if (-not (Has-EnvVar $envLines "MONITOR_TIMEZONE")) { $envLines += "MONITOR_TIMEZONE=Europe/Moscow" }
if (-not (Has-EnvVar $envLines "MONITOR_SYSTEM_PROC_PATH")) { $envLines += "MONITOR_SYSTEM_PROC_PATH=/host/proc" }
if (-not (Has-EnvVar $envLines "MONITOR_SYSTEM_DISK_PATH")) { $envLines += "MONITOR_SYSTEM_DISK_PATH=/hostfs" }
if (-not (Has-EnvVar $envLines "MONITOR_SYSTEM_DISK_LABEL")) { $envLines += "MONITOR_SYSTEM_DISK_LABEL=/" }
if (-not (Has-EnvVar $envLines "MONITOR_SYSTEM_CACHE_SECONDS")) { $envLines += "MONITOR_SYSTEM_CACHE_SECONDS=5" }
if (-not (Has-EnvVar $envLines "MONITOR_SYSTEM_AVERAGE_WINDOW_SECONDS")) { $envLines += "MONITOR_SYSTEM_AVERAGE_WINDOW_SECONDS=300" }
if (-not (Has-EnvVar $envLines "MONITOR_SYSTEM_ALERT_THRESHOLD_PERCENT")) { $envLines += "MONITOR_SYSTEM_ALERT_THRESHOLD_PERCENT=90" }
if (-not (Has-EnvVar $envLines "MONITOR_LOGIN_ALERTS_ENABLED")) { $envLines += "MONITOR_LOGIN_ALERTS_ENABLED=true" }
if (-not (Has-EnvVar $envLines "MONITOR_LOGIN_LOG_PATHS")) { $envLines += "MONITOR_LOGIN_LOG_PATHS=/hostfs/var/log/auth.log,/hostfs/var/log/secure" }
if (-not (Has-EnvVar $envLines "MONITOR_LOGIN_WTMP_PATHS")) { $envLines += "MONITOR_LOGIN_WTMP_PATHS=/hostfs/var/log/wtmp" }
if (-not (Has-EnvVar $envLines "MONITOR_LOGIN_UTMP_PATHS")) { $envLines += "MONITOR_LOGIN_UTMP_PATHS=/hostfs/run/utmp,/hostfs/var/run/utmp" }
if (-not (Has-EnvVar $envLines "LOG_LEVEL")) { $envLines += "LOG_LEVEL=INFO" }

if (-not [string]::IsNullOrWhiteSpace($allowedIds)) {
    if (-not (Has-EnvVar $envLines "MONITOR_ALERT_CHAT_IDS")) {
        $envLines += "MONITOR_ALERT_CHAT_IDS=$allowedIds"
    }
}

$envPath = Join-Path $bundlePath ".env"
Set-Content -Path $envPath -Value $envLines

$hash = (Get-FileHash (Join-Path $bundlePath "monitoring-bot-debian-amd64.tar") -Algorithm SHA256).Hash.ToLower()
Set-Content -Path (Join-Path $bundlePath "SHA256SUMS.txt") -Value "$hash  monitoring-bot-debian-amd64.tar"

if (Test-Path $zipFullPath) {
    Remove-Item $zipFullPath -Force
}

Compress-Archive -Path (Join-Path $bundlePath "*") -DestinationPath $zipFullPath
