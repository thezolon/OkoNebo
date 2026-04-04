# backup.ps1 [output-dir]
# Creates a timestamped backup of runtime state files.

param(
    [string]$OutputDir
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $OutputDir) {
    $OutputDir = Join-Path $root "backups"
}
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$dest = Join-Path $OutputDir "okonebo-backup-$ts"

New-Item -ItemType Directory -Force $dest | Out-Null

$files = @("config.yaml", "secure_settings.db", "cache.db", ".env")
foreach ($f in $files) {
    $src = Join-Path $root $f
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $dest $f) -Force
    }
}

$manifest = @()
$manifest += "backup_created_at=$ts"
$manifest += "source_root=$root"
Get-ChildItem $dest -Name | ForEach-Object { $manifest += "file=$_" }
$manifest | Set-Content (Join-Path $dest "manifest.txt")

Write-Host "Backup written to: $dest"
Get-ChildItem $dest -Name
