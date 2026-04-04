# Architecture Overview

OkoNebo is a self-hostable weather web application built on:

- **Backend**: FastAPI (Python 3.11+), served via Uvicorn.
- **Frontend**: Vanilla HTML/CSS/JavaScript — no build step, no framework.
- **Persistence**: SQLite via `cache_db.py` (weather cache) and `secure_settings.py` (encrypted settings).
- **Deployment**: Docker Compose (single container, host port `8888` mapped to container port `8000`).

## Directory Structure

```
OkoNebo/
├── app/
│   ├── main.py            # FastAPI application, routes, middleware
│   ├── weather_client.py  # All upstream provider HTTP clients + caching
│   ├── secure_settings.py # Fernet-encrypted settings store (SQLite)
│   ├── cache_db.py        # Adaptive-TTL SQLite weather cache
│   └── static/            # Frontend served as static files
│       ├── index.html
│       ├── css/style.css
│       └── js/app.js
├── scripts/
│   ├── test_harness.sh    # Full quality gate (venv + Docker)
│   ├── security_check.py  # Secret leak scanner
│   ├── reset.sh           # Linux/macOS factory reset helper
│   └── checksums.sh       # Release checksum generator
├── tests/
│   ├── test_provider_fallback.py        # Provider fallback + auth guard tests
│   ├── test_setup_auth_integration.py   # Setup/auth integration tests
│   ├── integration_smoke.py             # Live API smoke tests
│   └── frontend_smoke.py                # Frontend setup/radar control smoke tests
├── .github/workflows/ci.yml        # GitHub Actions CI
├── start.sh               # Linux/macOS Docker start helper
├── start.bat              # Windows Docker start helper
├── health-check.ps1       # Windows health probe
├── reset.ps1              # Windows factory reset helper
├── config.yaml            # Location, auth, provider toggles
├── docker-compose.yml
└── Dockerfile
```

## Request Flow

```
Browser → FastAPI middleware (rate-limit → auth-guard → CORS)
       → Route handler (api_current / api_forecast / api_hourly / ...)
       → Provider fallback chain (nws → weatherapi → tomorrow → visualcrossing → meteomatics)
       → weather_client.py (HybridTTLCache → upstream HTTP)
       → Response with source annotation
```

## Provider Fallback Architecture

Each weather endpoint (current conditions, forecast, hourly) attempts providers in a deterministic order.  The first provider that returns a valid payload wins.  Errors are collected and returned in the 502 response if all providers fail.

```
/api/current   : nws → weatherapi → tomorrow → visualcrossing → meteomatics
/api/forecast  : nws → weatherapi → tomorrow → visualcrossing
/api/hourly    : nws → weatherapi → tomorrow → visualcrossing
/api/metar     : aviationweather (keyless only, no fallback)
/api/tides     : noaa_tides (keyless only, no fallback)
```

Providers are enabled/disabled per-install via the settings API or Setup panel.  Keyed providers are only attempted when a valid API key is configured.

## Provider Capability Matrix

| Provider         | Current | Forecast | Hourly | Alerts | METAR | Tides | Key Required |
|-----------------|---------|----------|--------|--------|-------|-------|--------------|
| NWS             | ✓       | ✓        | ✓      | ✓      |       |       | No           |
| WeatherAPI      | ✓       | ✓        | ✓      |        |       |       | Yes          |
| Tomorrow.io     | ✓       | ✓        | ✓      |        |       |       | Yes          |
| Visual Crossing | ✓       | ✓        | ✓      |        |       |       | Yes          |
| Meteomatics     | ✓       |          |        |        |       |       | Yes (user:pw)|
| OpenWeather     |         |          |        |        |       |       | Yes (OWM 3.0)|
| PWS             |         |          |        |        |       |       | Yes          |
| AviationWeather |         |          |        |        | ✓     |       | No           |
| NOAA Tides      |         |          |        |        |       | ✓     | No           |

## Caching Strategy

`HybridTTLCache` stores weather data in both an in-memory dict and SQLite:

| Data type       | Memory TTL | SQLite TTL | Adaptive (storm)|
|----------------|-----------|-----------|-----------------|
| Current obs     | 5 min     | 5 min     | 2 min           |
| Forecast        | 15 min    | 15 min    | 5 min           |
| Hourly          | 15 min    | 15 min    | 5 min           |
| Alerts          | 5 min     | 5 min     | 2 min           |
| METAR           | 10 min    | 10 min    | —               |
| Tides           | 30 min    | 30 min    | —               |

When NWS active alerts are present, cache TTLs shrink to keep data fresher during weather events.

## Authentication

Auth is **disabled by default**.  When enabled (`auth.enabled: true` in config or settings):

- HMAC-SHA256 signed tokens (24-hour TTL, configurable).
- Admin role: read + write (`POST /api/settings`, provider key management).
- Viewer role: read-only.
- Token revocation via `POST /api/auth/logout` (in-memory denylist, pruned on expiry).
- Login brute-force protection: 10 attempts per 5-minute window per IP.

## Security Hardening

- API keys are never included in JSON responses.
- Encrypted settings store uses Fernet (AES-128-CBC + HMAC-SHA256).
- `scripts/security_check.py` scans for leaked keys in config/env before any release.
- Rate limiter: 800 requests per 60-second window per IP.
- OWM tiles proxied server-side so the API key never reaches the browser.
