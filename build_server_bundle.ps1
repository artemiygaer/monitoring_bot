param(
    [string]$BundleDir = "server_bundle_debian",
    [string]$ZipPath = "server_bundle_debian.zip",
    [string]$ImageArchive = ""
)

$ErrorActionPreference = "Stop"

$bundlePath = Join-Path (Get-Location) $BundleDir
$zipFullPath = Join-Path (Get-Location) $ZipPath
$resolvedBundlePath = [System.IO.Path]::GetFullPath($bundlePath)
$workspacePath = [System.IO.Path]::GetFullPath((Get-Location).Path)

if (-not $resolvedBundlePath.StartsWith($workspacePath, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Каталог bundle должен находиться внутри рабочей папки."
}

if (Test-Path -LiteralPath $resolvedBundlePath) {
    Remove-Item -LiteralPath $resolvedBundlePath -Recurse -Force
}
New-Item -ItemType Directory -Path $resolvedBundlePath | Out-Null

$publicFiles = @(
    "docker-compose.bot.yml",
    "README.md",
    "deploy.sh",
    "install.sh",
    ".env.example"
)
foreach ($file in $publicFiles) {
    if (-not (Test-Path -LiteralPath $file)) {
        throw "Не найден публичный файл '$file'."
    }
    Copy-Item -LiteralPath $file -Destination (Join-Path $resolvedBundlePath $file) -Force
}

if ([string]::IsNullOrWhiteSpace($ImageArchive)) {
    if (Test-Path -LiteralPath "monitoring-bot-debian-amd64.tar.gz") {
        $ImageArchive = "monitoring-bot-debian-amd64.tar.gz"
    }
    elseif (Test-Path -LiteralPath "monitoring-bot-debian-amd64.tar") {
        $ImageArchive = "monitoring-bot-debian-amd64.tar"
    }
}

if (-not [string]::IsNullOrWhiteSpace($ImageArchive)) {
    if (-not (Test-Path -LiteralPath $ImageArchive)) {
        throw "Архив образа '$ImageArchive' не найден."
    }
    $archiveName = Split-Path -Leaf $ImageArchive
    $bundleArchive = Join-Path $resolvedBundlePath $archiveName
    Copy-Item -LiteralPath $ImageArchive -Destination $bundleArchive -Force
    $hash = (Get-FileHash -LiteralPath $bundleArchive -Algorithm SHA256).Hash.ToLower()
    Set-Content -LiteralPath (Join-Path $resolvedBundlePath "SHA256SUMS.txt") -Value "$hash  $archiveName"
}

if (Test-Path -LiteralPath $zipFullPath) {
    Remove-Item -LiteralPath $zipFullPath -Force
}
Compress-Archive -Path (Join-Path $resolvedBundlePath "*") -DestinationPath $zipFullPath

Write-Output "Bundle создан без .env и секретов: $resolvedBundlePath"
