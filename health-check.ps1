# health-check.ps1 — verify OkoNebo is running (Windows / PowerShell)
# Requires: Docker Desktop running, curl available (Windows 10+ built-in) or
#           PowerShell 7+ (uses Invoke-WebRequest as fallback)
#
# Usage:
#   .\health-check.ps1
#   .\health-check.ps1 localhost:8888

param(
    [string]$Host = "localhost:8888"
)

$base = "http://$Host"
Write-Host "Checking OkoNebo at $base..."
Write-Host ""

$allOk = $true

function Check-Endpoint {
    param(
        [string]$Label,
        [string]$Url,
        [int[]]$AcceptCodes = @(200)
    )
    Write-Host -NoNewline "${Label}: "
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
        $code = $resp.StatusCode
    } catch {
        # Invoke-WebRequest throws on 4xx/5xx — extract status from exception
        $code = $_.Exception.Response.StatusCode.value__
        if (-not $code) { $code = 0 }
    }
    if ($AcceptCodes -contains $code) {
        Write-Host "OK ($code)" -ForegroundColor Green
        return $true
    } else {
        Write-Host "FAILED ($code)" -ForegroundColor Red
        return $false
    }
}

$allOk = (Check-Endpoint "Config endpoint"    "$base/api/config"    200)       -and $allOk
$allOk = (Check-Endpoint "Bootstrap endpoint" "$base/api/bootstrap" 200)       -and $allOk
$allOk = (Check-Endpoint "Current conditions" "$base/api/current"   200, 502)  -and $allOk
$allOk = (Check-Endpoint "Active alerts"      "$base/api/alerts"    200, 502)  -and $allOk
$allOk = (Check-Endpoint "7-day forecast"     "$base/api/forecast"  200, 502)  -and $allOk
$allOk = (Check-Endpoint "Hourly forecast"    "$base/api/hourly"    200, 502)  -and $allOk
$allOk = (Check-Endpoint "Swagger UI docs"    "$base/docs"          200)       -and $allOk
$allOk = (Check-Endpoint "OpenAPI spec"       "$base/openapi.json"  200)       -and $allOk

Write-Host -NoNewline "Browser UI: "
try {
    $body = (Invoke-WebRequest -Uri $base -UseBasicParsing -TimeoutSec 10).Content
    if ($body -match "Weather Dashboard|Storm Dashboard") {
        Write-Host "OK" -ForegroundColor Green
    } else {
        Write-Host "FAILED (unexpected content)" -ForegroundColor Red
        $allOk = $false
    }
} catch {
    Write-Host "FAILED ($($_.Exception.Message))" -ForegroundColor Red
    $allOk = $false
}

Write-Host ""
if ($allOk) {
    Write-Host "All systems operational!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Dashboard : $base"
    Write-Host "  API docs  : $base/docs"
    Write-Host "  OpenAPI   : $base/openapi.json"
    exit 0
} else {
    Write-Host "One or more checks failed. Run: docker compose logs weather-app" -ForegroundColor Red
    exit 1
}
