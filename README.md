# OkoNebo

[![CI](https://github.com/thezolon/OkoNebo/actions/workflows/ci.yml/badge.svg)](https://github.com/thezolon/OkoNebo/actions/workflows/ci.yml)

Self-hosted weather dashboard and local API for your configured monitoring location. Current conditions, active alerts, 7-day forecast, hourly trend, radar, personal weather stations, aviation METAR, and coastal tide predictions - all from one Docker container, no cloud dependency required.

## Features

- **Multi-provider fallback** - NWS -> WeatherAPI -> Tomorrow.io -> Visual Crossing -> Meteomatics; first successful response wins
- **Keyless providers** - NWS, AviationWeather (METAR), NOAA Tides start without any API key
- **First-run blocking overlay** - fresh installs prompt for location and optional API keys before the dashboard loads
- **Encrypted settings store** - provider keys are stored in a Fernet-encrypted SQLite database, never in plain text on disk
- **Optional authentication** - JWT-based login with admin and viewer roles; login rate limiting (10 attempts / 5 min / IP); token revocation on logout
- **In-app Setup panel** - edit location, timezone, providers, and map layer without restarting
- **Offline-aware UI** - persistent browser cache, last-known-good state, visible diagnostics
- **Radar** - RainViewer with OWM overlay option; Esri/OSM/CARTO base layers
- **PWS** - personal weather station comparison and trend chart
- **CI pipeline** - compile checks, unit tests (16), Bandit security scan, Docker build + health + smoke on every push

## Quick Start

### 1. Copy the example config

```bash
cp config.yaml.example config.yaml
# Edit config.yaml and set lat/lon to your location
```

### 2. Start with Docker

```bash
docker compose up -d --build
bash health-check.sh
```

### 3. Open the UI

Browse to **http://localhost:8888** - a first-run overlay will prompt for your location and any optional provider API keys.
After saving, the dashboard loads and begins polling.

| URL | Purpose |
|-----|---------|
| http://localhost:8888 | Dashboard |
| http://localhost:8888/docs | Swagger UI |
| http://localhost:8888/openapi.json | OpenAPI spec |
| http://localhost:8888/api/debug | Runtime diagnostics |

### Direct Python (no Docker)

```bash
bash start.sh
bash health-check.sh
```

### Raspberry Pi

```bash
# On the Pi, after extracting the release package:
cd weatherapp-pi-release-*
bash deploy-on-pi.sh
```

## Configuration

Copy [config.yaml.example](config.yaml.example) to `config.yaml`. The minimal required fields are `lat` and `lon`.
All settings can also be changed at runtime through the in-app Setup panel - no restart required.

### Environment variables (optional)

Copy `.env.example` to `.env` before starting:

| Variable | Purpose |
|----------|---------|
| `AUTH_ENABLED` | `true` to require login (default: `false`) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Admin credentials when auth is on |
| `VIEWER_USERNAME` / `VIEWER_PASSWORD` | Read-only viewer credentials (optional) |
| `SETTINGS_ENCRYPTION_KEY` | Fernet key for `secure_settings.db` (auto-generated if absent) |
| `WEATHERAPI_KEY` | WeatherAPI.com key |
| `TOMORROW_KEY` | Tomorrow.io key |
| `VISUALCROSSING_KEY` | Visual Crossing key |
| `OPENWEATHER_KEY` | OpenWeather One Call 3.0 key |
| `METEOMATICS_API_KEY` | `username:password` from Meteomatics |

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/config` | Location and integration availability |
| `GET /api/current` | Current conditions (multi-provider fallback) |
| `GET /api/forecast` | 7-day forecast (multi-provider fallback) |
| `GET /api/hourly` | 48-hour hourly data (multi-provider fallback) |
| `GET /api/alerts` | Active NWS alerts for monitored locations |
| `GET /api/metar` | Latest aviation METAR (AviationWeather, keyless) |
| `GET /api/tides?days=1` | Tide predictions (NOAA CO-OPS, keyless) |
| `GET /api/owm` | OpenWeather supplemental data |
| `GET /api/pws` | Personal weather station observations |
| `GET /api/pws/trend?hours=3` | PWS trend points |
| `GET /api/stats` | Upstream call counts per provider |
| `POST /api/settings` | Save runtime settings (admin only when auth on) |
| `POST /api/auth/login` | Obtain JWT (rate-limited: 10 attempts / 5 min / IP) |
| `POST /api/auth/logout` | Revoke current token |
| `GET /api/debug` | Server/runtime diagnostics |
| `GET /api/bootstrap` | First-run completion state |

## Providers

| Provider | Type | Key required | Capabilities |
|----------|------|-------------|--------------|
| NWS | keyless | no | current, forecast, hourly, alerts |
| AviationWeather | keyless | no | METAR |
| NOAA Tides | keyless | no | tide predictions |
| WeatherAPI | keyed | yes | current, forecast, hourly |
| Tomorrow.io | keyed | yes | current, forecast, hourly |
| Visual Crossing | keyed | yes | current, forecast, hourly |
| OpenWeather | keyed | yes | current supplemental |
| Meteomatics | keyed | yes (`user:pass`) | current |

Keyless providers are enabled by default. Keyed providers activate automatically when their key is present.

## Development and Testing

### Local test harness

```bash
bash scripts/test_harness.sh
```

Runs: compile checks -> 16 unit tests -> Docker build -> health check -> integration smoke -> frontend smoke -> secret leak check.

```bash
# Skip Docker (test against an already-running container):
HARNESS_SKIP_DOCKER=1 bash scripts/test_harness.sh

# Point at a different host:
WEATHERAPP_BASE_URL=http://myhost:8888 bash scripts/test_harness.sh
```

### Continuous Integration

The CI pipeline (`.github/workflows/ci.yml`) runs on every push and PR to `main` and `release/**`:

- **test job**: compile checks, pytest (16 tests), Bandit security scan
- **docker job**: build image, health check, integration smoke, frontend smoke

## Operations Notes

- Weather data endpoints return `502` when no providers are configured or all providers fail - this is expected on a fresh install before location is set.
- The browser stores a last-known-good state so the UI can recover after reloads or brief outages.
- Frame-cache cleanup runs automatically and keeps browser storage bounded.
- Docker build context is trimmed via `.dockerignore`; local virtualenv and editor files do not end up in the image.
- Login brute-force protection: 10 failed attempts in a 5-minute window locks the IP until the window resets.
- The test alert defaults to off.

## Files Worth Knowing

| File | Purpose |
|------|---------|
| [app/main.py](app/main.py) | FastAPI routes, auth, orchestration |
| [app/weather_client.py](app/weather_client.py) | All upstream HTTP clients and normalizers |
| [app/static/js/app.js](app/static/js/app.js) | Frontend state, rendering, first-run overlay |
| [app/static/index.html](app/static/index.html) | Dashboard layout |
| [app/static/css/style.css](app/static/css/style.css) | Styling |
| [config.yaml.example](config.yaml.example) | Annotated configuration template |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, provider matrix, auth notes |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | Technical implementation notes |
| [SECURITY.md](SECURITY.md) | Security policy and reporting |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribution guide |
| [RASPBERRY_PI_DEPLOYMENT.md](RASPBERRY_PI_DEPLOYMENT.md) | Pi deployment notes |

## Troubleshooting

### Health check

```bash
bash health-check.sh
```

Weather data endpoints (`/api/current`, `/api/forecast`, `/api/hourly`, `/api/alerts`) report `OK (502)` on a fresh install with no location configured - this is correct. Configure your location through the first-run overlay or Setup panel to get live data.

### Debug payload

```bash
curl http://localhost:8888/api/debug
```

### Provider statistics

```bash
curl http://localhost:8888/api/stats
```

### Secret leak check

```bash
python3 scripts/security_check.py
```

Expected: `SECRET LEAK CHECK: OK`

### Rebuild container

```bash
docker compose up -d --build
```

### Verify OpenWeather key is active

```bash
curl -s http://localhost:8888/api/owm
```

Success signals: UI `OWM` source badge is green; `/api/owm` contains populated `current`, `hourly`, and `daily`.

Not-ready signals: `/api/owm` returns `{"available": false, "error": "..."}` or `401 Unauthorized` - confirm One Call 3.0 is enabled on the OWM account, then rebuild/restart.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
Security issues: see [SECURITY.md](SECURITY.md) for the responsible disclosure process.

## License

[MIT](LICENSE)

## Attribution

- [NOAA National Weather Service](https://www.weather.gov/) - public domain weather data
- [AviationWeather.gov](https://www.aviationweather.gov/) - public domain METAR data
- [NOAA CO-OPS](https://tidesandcurrents.noaa.gov/) - public domain tide predictions
- [OpenWeather](https://openweathermap.org/)
- [RainViewer](https://www.rainviewer.com/)
- [Leaflet](https://leafletjs.com/)
- [Chart.js](https://www.chartjs.org/)
