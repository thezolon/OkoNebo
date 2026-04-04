# OkoNebo Implementation

## Runtime Model

- Backend: FastAPI serving JSON API endpoints and static frontend assets
- Frontend: plain HTML/CSS/JS (no build step)
- Container port: `8000`
- Host port: `8888`
- Primary entrypoints: [app/main.py](app/main.py), [app/weather_client.py](app/weather_client.py), [app/static/js/app.js](app/static/js/app.js)

## Architecture Summary

1. Client bootstraps from `/api/bootstrap` and `/api/config`.
2. First-run installs are blocked by a full-screen setup overlay until settings are saved.
3. Runtime settings and provider API keys are persisted in an encrypted SQLite store (`secure_settings.db`).
4. Weather endpoints use deterministic provider fallback chains and return structured error metadata on failure.
5. UI stores last-known-good state for recovery and continues rendering with partial data when possible.

## Provider Model

### Current Conditions Fallback

`nws -> weatherapi -> tomorrow -> visualcrossing -> meteomatics`

### Forecast/Hourly Fallback

`nws -> weatherapi -> tomorrow -> visualcrossing`

### Specialized Endpoints

- `/api/metar` via AviationWeather (keyless)
- `/api/tides` via NOAA CO-OPS (keyless)
- `/api/owm` supplemental data (keyed)

### Provider Capability Registry

Provider capability metadata is exposed via `/api/bootstrap` and used by frontend setup UX.

## Security and Auth

### Settings Security

- Provider API keys are stored in `secure_settings.db` under encrypted keys.
- Plain `config.yaml` remains a fallback/default source, not the preferred secret store.

### Auth Model

- Optional auth (`AUTH_ENABLED`) with admin and viewer roles.
- Admin-only write protection on `POST /api/settings`.
- Login rate limiting: 10 failed attempts per 5 minutes per IP.
- JWT token denylist supports explicit logout invalidation (`POST /api/auth/logout`).

### AI Agent Tokens

- Agents (MCP, REST, ACP) authenticate via persistent bearer tokens with scoped permissions.
- Tokens are created via `/agent-tokens` with configurable TTL and scope flags (`weather.read`, `config.read`, `stats.read`, `debug.read`).
- Token value is displayed once at creation (with copy-to-clipboard helper) and never persisted or shown again.
- Failed access attempts and token expiration are logged for audit.
- Tokens can be deleted/revoked via admin panel with confirmation dialog.
- Expandable token metadata shows scopes, creation/expiration timestamps, and status (active/revoked).

## First-Run and Setup UX

- New installs show blocking first-run overlay requiring valid home coordinates.
- **In-app Setup Panel** allows editing all settings (location, timezone, provider configuration, authentication, AI agent tokens) with real-time unsaved changes detection.
- **Provider Configuration** integrates enable/disable toggles, API key fields, and pull cycle controls in unified cards for each provider.
- **Pull Cycle Control** lets operators tune provider check frequency (default 5m) without restarting.
- **Provider Testing** includes individual test buttons per provider and a "Test All" button (only enabled providers) for quick validation.
- **Keyboard Shortcuts**: Ctrl+S (Cmd+S on Mac) saves settings instantly.
- **Unsaved Changes Detection**: Visual indicator and confirmation dialogs prevent data loss.
- Client-side validation:
  - numeric lat/lon required
  - range check enforced: lat `-90..90`, lon `-180..180`
- Server-side validation mirrors coordinate checks for defense-in-depth.
- `mark_first_run_complete` sets secure bootstrap state, and `/api/bootstrap` returns `first_run_required=false` afterwards.

## Reliability and Operational Hardening

### Request and Cache Behavior

- In-flight request deduplication in frontend to avoid burst duplication.
- Browser last-known-good cache for short outage resilience.
- Frame cache TTL and bounded cleanup to avoid unbounded local storage growth.

### Diagnostics

- `/api/debug` exposes runtime diagnostics and last client snapshot.
- `/api/stats` exposes upstream call counters by provider.
- UI timeline records key events for operator visibility.

### Health and Smoke Semantics

For fresh installs with unset location/provider keys, weather data endpoints may legitimately return `502` while infrastructure endpoints remain healthy.

- `health-check.sh` accepts `200|502` for:
  - `/api/current`
  - `/api/alerts`
  - `/api/forecast`
  - `/api/hourly`
- Integration smoke (`tests/integration_smoke.py`) mirrors this behavior.

## Testing and CI

### Local Harness

`scripts/test_harness.sh` runs:

1. Python compile checks
2. Unit tests (`tests/test_provider_fallback.py` + `tests/test_setup_auth_integration.py`, 16 tests)
3. Docker build/start
4. Health check
5. Integration smoke
6. Secret leak check (`scripts/security_check.py`)

### CI Workflow

`.github/workflows/ci.yml`:

- `test` job: compile checks, pytest, Bandit scan
- `docker` job: build, health check, smoke tests

## Key Files

- [app/main.py](app/main.py): API routes, auth, settings orchestration
- [app/weather_client.py](app/weather_client.py): upstream adapters, normalization, caching
- [app/static/js/app.js](app/static/js/app.js): setup flows, rendering, diagnostics
- [tests/test_provider_fallback.py](tests/test_provider_fallback.py): fallback and auth guard unit tests
- [tests/integration_smoke.py](tests/integration_smoke.py): integration endpoint smoke checks
- [tests/frontend_smoke.py](tests/frontend_smoke.py): setup/map-provider frontend smoke checks
- [health-check.sh](health-check.sh): release/ops health gate

## Verification Commands

```bash
cd /bulk/weatherapp
python3 -m py_compile app/main.py app/weather_client.py
node --check app/static/js/app.js
bash scripts/test_harness.sh
```

## Documentation Set (v1.0)

- [README.md](README.md)
- [ARCHITECTURE.md](ARCHITECTURE.md)
- [SECURITY.md](SECURITY.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
