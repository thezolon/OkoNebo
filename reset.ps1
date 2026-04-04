# reset.ps1 — factory-reset OkoNebo state files (Windows / PowerShell)
#
# Normal rebuilds (docker compose up -d --build) preserve all state.
# Run THIS script only when you want to start completely fresh.
#
# What is removed:
#   secure_settings.db  — api keys, location, first-run flag, auth users
#   cache.db            — cached weather API responses
#
# What is NOT touched (unless -Config is passed):
#   config.yaml         — base location / timezone / static options
#   .env                — environment variables / credentials
#
# Usage:
#   .\reset.ps1              # wipe DBs only
#   .\reset.ps1 -Config      # wipe DBs + config.yaml (full blank slate)
#   .\reset.ps1 -Yes         # skip confirmation prompt

param(
    [switch]$Config,
    [switch]$Yes
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "OkoNebo factory reset"
Write-Host "====================="
Write-Host "  secure_settings.db  -> will be removed"
Write-Host "  cache.db            -> will be removed"
if ($Config) {
    Write-Host "  config.yaml         -> will be removed (-Config)"
}
Write-Host ""

if (-not $Yes) {
    $confirm = Read-Host "Are you sure? This cannot be undone. (yes/N)"
    if ($confirm -ne "yes") {
        Write-Host "Aborted."
        exit 0
    }
}

Write-Host "[reset] stopping container..."
Push-Location $root
docker compose down 2>$null
Pop-Location

Write-Host "[reset] removing state files..."
Remove-Item -Force -ErrorAction SilentlyContinue "$root\secure_settings.db"
Remove-Item -Force -ErrorAction SilentlyContinue "$root\cache.db"

if ($Config) {
    Remove-Item -Force -ErrorAction SilentlyContinue "$root\config.yaml"
    Write-Host "[reset] config.yaml removed"
}

# Re-create empty placeholder files so Docker bind-mounts
# get regular files (not directories) on next start.
New-Item -ItemType File -Force "$root\secure_settings.db" | Out-Null
New-Item -ItemType File -Force "$root\cache.db"           | Out-Null

Write-Host "[reset] done — run 'docker compose up -d --build' to start fresh"
