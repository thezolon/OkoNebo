# OkoNebo Implementation

## Runtime Model

- Backend: FastAPI serving JSON API endpoints and static frontend assets
- Frontend: plain HTML/CSS/JS (no build step)
- Container port: `8000`
- Host port: `8888`
- Primary entrypoints: [app/main.py](../app/main.py), [app/weather_client.py](../app/weather_client.py), [app/static/js/app.js](../app/static/js/app.js)

## Architecture Summary

1. Client bootstraps from `/api/bootstrap` and `/api/config`.
2. First-run installs are blocked by a full-screen setup overlay until settings are saved.
3. Runtime settings and provider API keys are persisted in an encrypted SQLite store (`secure_settings.db`).
4. Weather endpoints use deterministic provider fallback chains and return structured error metadata on failure.
5. UI stores last-known-good state for recovery and continues rendering with partial data when possible.
6. Cache-backed history endpoint provides time-series access to recent observations.

## Provider Model

### Current Conditions Fallback

`nws -> weatherapi -> tomorrow -> visualcrossing -> meteomatics`

### Forecast/Hourly Fallback

`nws -> weatherapi -> tomorrow -> visualcrossing`

### Specialized Endpoints

- `/api/metar` via AviationWeather (keyless)
- `/api/tides` via NOAA CO-OPS (keyless)
- `/api/owm` supplemental data (keyed)

### Multi-Location Concurrent Fetch

- `/api/current/multi` accepts a comma-separated list of named locations from `config.yaml:alert_locations`.
- Each location fetches current conditions concurrently using the same provider fallback chain.
- Returns a structured map of `{ location_name: current_conditions | error }`.

### Provider Capability Registry

Provider capability metadata is exposed via `/api/bootstrap` and used by frontend setup UX.

## Computed and Derived Endpoints

### Astronomical Data (`/api/astro`)

- Computed locally using the `astral` library — no upstream API call or key required.
- Returns solar times (sunrise, sunset, solar noon, golden hour, civil/nautical/astronomical twilight), lunar phase, and moon illumination.
- Rendered in its own panel adjacent to current conditions.

### Air Quality Index (`/api/aqi`)

- Uses OpenWeather Air Pollution API when configured.
- Falls back to keyless Open-Meteo Air Quality API when OpenWeather is disabled/unconfigured/unavailable.
- Returns AQI index (1–5) and individual pollutant concentrations (PM2.5, PM10, O₃, NO₂, SO₂, CO).
- Returns `source` metadata (`openweather` or `openmeteo`) and stays gracefully available when fallback succeeds.

### Historical Trends (`/api/history`)

- Query parameter: `hours=N` (default 24, max 168).
- Returns temperature, humidity, pressure, and wind time-series from the in-memory cache.
- Cache is populated continuously by background weather fetches; no additional upstream calls.

## Security and Auth

### Settings Security

- Provider API keys are stored in `secure_settings.db` under encrypted fields (`cryptography.fernet`).
- Plain `config.yaml` remains a fallback/default source, not the preferred secret store.
- Centralized redaction (`app/redaction.py`) provides `redact_text()` and `redact_value()` helpers and a `RedactionFilter` logging filter that strips secrets from all structured log output.

### Auth Model

- Optional auth (`AUTH_ENABLED`) with admin and viewer roles.
- Admin-only write protection on `POST /api/settings`.
- Login rate limiting: 10 failed attempts per 5 minutes per IP.
- JWT token denylist supports explicit logout invalidation (`POST /api/auth/logout`).
- Auth precedence: environment variables (`ADMIN_PASSWORD`, `VIEWER_PASSWORD`) take precedence over SQLite values, enabling zero-touch headless re-deployment.

### AI Agent Tokens

- Agents (MCP, REST, ACP) authenticate via persistent bearer tokens with scoped permissions.
- Tokens are created via the `/agent-tokens` admin panel with configurable TTL and scope flags (`weather.read`, `config.read`, `stats.read`, `debug.read`).
- Token value is displayed once at creation (with copy-to-clipboard helper) and never persisted in plaintext or shown again.
- Failed access attempts and token expiration are logged for audit.
- Tokens can be deleted/revoked via admin panel with confirmation dialog.
- Expandable token metadata shows scopes, creation/expiration timestamps, and status (active/revoked).

## First-Run and Setup UX

- New installs show blocking first-run overlay requiring valid home coordinates.
- **In-app Setup Panel** allows editing all settings (location, timezone, provider configuration, authentication, AI agent tokens) with real-time unsaved changes detection.
- **Provider Configuration** integrates enable/disable toggles, API key fields, and pull cycle controls in unified cards for each provider.
- **Pull Cycle Control** lets operators tune provider check frequency (default 5 minutes) without restarting.
- **Provider Testing** includes individual test buttons per provider and a "Test All" button (only enabled providers). Provider test credentials are sent via POST body, never as URL query parameters.
- **Keyboard Shortcuts**: Ctrl+S (Cmd+S on Mac) saves settings instantly.
- **Unsaved Changes Detection**: visual indicator and confirmation dialogs prevent data loss.
- Client-side validation: numeric lat/lon required, range check enforced (lat `-90..90`, lon `-180..180`).
- Server-side validation mirrors coordinate checks for defense-in-depth.
- `mark_first_run_complete` sets secure bootstrap state; `/api/bootstrap` returns `first_run_required=false` afterwards.

## Webhooks

- Outbound webhook delivery is triggered on weather alert threat-level transitions (escalation and de-escalation).
- Webhooks are configured in the Admin panel at `/api/webhooks` with a URL, optional HMAC-SHA256 secret, and enable/disable toggle.
- Delivery includes a structured JSON payload with old/new threat level, active alerts, and timestamp.
- Failed deliveries are retried with exponential back-off; delivery history and last-error status are visible in the admin panel.

## Browser Push Notifications

- Implements Web Push (RFC 8030) with VAPID authentication.
- VAPID key pair is generated on first use and stored in `secure_settings.db`.
- VAPID public key is exposed via `/api/push/vapid-public-key` for browser subscription.
- Subscriptions are managed at `/api/push/subscribe` (POST) and `/api/push/unsubscribe` (DELETE).
- Push payloads are sent on the same threat-level transition events as webhooks.
- Service worker (`app/static/js/sw.js`) handles background delivery and notification display with click-through action.

## Home Assistant Integration

- `/api/ha/sensor` returns current conditions formatted as a Home Assistant REST sensor payload.
- `/api/ha/weather` returns a Home Assistant weather entity payload including hourly forecast.
- Both endpoints require an agent token with `weather.read` scope.
- Example HA `configuration.yaml` snippets are provided in [docs/home-assistant.md](home-assistant.md).

## Reliability and Operational Hardening

### Request and Cache Behavior

- In-flight request deduplication in frontend to avoid burst duplication.
- Browser last-known-good cache for short outage resilience.
- Frame cache TTL and bounded cleanup to avoid unbounded local storage growth.
- Backend retry logic with jitter on provider HTTP calls; connection pooling via `httpx.AsyncClient`.

## Diagnostics and Support

### Runtime Diagnostics

- `/api/debug` exposes runtime diagnostics and last client snapshot.
- `/api/stats` exposes upstream call counters by provider.
- **UI Event Timeline** records key events (observations, alerts, refreshes, system events) with timestamps.
- **Timeline Search/Filter** (Shift+F) allows filtering events by category or search text.
- **Admin Observability Dashboard** displays real-time metrics: request latency, error rates, server connection status, and operational health.

### Support Bundle

- `/api/support-bundle` (admin only) generates a sanitized ZIP archive containing config, redacted logs, diagnostic data, and system info.
- Equivalent CLI tool: `scripts/support_bundle.py`.
- All secrets are scrubbed by `app/redaction.py` before inclusion.

### Admin Credential Recovery

- `scripts/reset_admin.py` resets the admin password directly in `secure_settings.db` without requiring the current password.
- Use when locked out; requires shell access to the host.

### Health and Smoke Semantics

For fresh installs with unset location/provider keys, data endpoints may legitimately return `502` while infrastructure endpoints remain healthy.

- `health-check.sh` accepts `200|502` for `/api/current`, `/api/alerts`, `/api/forecast`, `/api/hourly`.
- Integration smoke (`tests/integration_smoke.py`) mirrors this behavior.

## Mobile, PWA, and Responsive UI

- **Progressive Web App**: `manifest.json` and service worker enable install-to-homescreen and offline last-known-good.
- **Panel Layout Control**: Compact/Expanded toggle (Shift+C) adapts dashboard to small screens.
- **Collapsible Panels** reduce visual clutter on mobile while preserving full data access.
- **Responsive Forecast Grid** adapts column count based on viewport width.
- **Touch-Optimized Controls** with minimum 44px tap targets for mobile accessibility.
- **Orientation Awareness** detects portrait/landscape and adjusts layout dynamically.
- **Persistent Layout State** saves user preference in localStorage across sessions.
- **Reset Layout Button** quickly restores default panel configuration.

## Testing and CI

### Test Suite (60 tests across 6 files)

| File | Tests | Coverage |
|------|-------|----------|
| `tests/test_provider_fallback.py` | 18 | Fallback chains, auth guards, provider error handling |
| `tests/test_setup_auth_integration.py` | 18 | Setup UX, auth flows, credential management |
| `tests/test_panel_layout_ui.py` | 8 | Layout state, panel visibility, responsive behavior |
| `tests/test_debug_observability.py` | 6 | Debug endpoint, stats, event timeline |
| `tests/test_weather_client_telemetry.py` | 6 | Retry logic, jitter, connection pooling telemetry |
| `tests/test_cache_db.py` | 4 | Cache read/write, TTL expiry, bounded cleanup |

### Local Harness

`scripts/test_harness.sh` runs:

1. Python compile checks
2. Unit tests (60 tests)
3. Docker build/start
4. Health check
5. Integration smoke (`tests/integration_smoke.py`)
6. Secret leak check (`scripts/security_check.py`)

### CI Workflow

`.github/workflows/ci.yml`:

- `test` job: compile checks, markdown link check, unittest discovery (60 tests), Bandit scan
- `docker` job: build, health check, smoke tests

## Key Files

| File | Purpose |
|------|---------|
| [app/main.py](../app/main.py) | API routes, auth, settings orchestration |
| [app/weather_client.py](../app/weather_client.py) | Upstream adapters, normalization, caching |
| [app/cache_db.py](../app/cache_db.py) | In-memory cache with TTL and history ring buffer |
| [app/secure_settings.py](../app/secure_settings.py) | Encrypted settings store (Fernet/SQLite) |
| [app/redaction.py](../app/redaction.py) | Centralized secret redaction for logs and support bundles |
| [app/static/js/app.js](../app/static/js/app.js) | Setup flows, rendering, PWA, diagnostics |
| [scripts/support_bundle.py](../scripts/support_bundle.py) | CLI support bundle generator |
| [scripts/reset_admin.py](../scripts/reset_admin.py) | Admin credential recovery tool |
| [scripts/security_check.py](../scripts/security_check.py) | Secret leak scanner |
| [tests/test_provider_fallback.py](../tests/test_provider_fallback.py) | Core fallback + auth unit tests |
| [tests/integration_smoke.py](../tests/integration_smoke.py) | Integration endpoint smoke checks |
| [health-check.sh](../health-check.sh) | Release/ops health gate |

## Verification Commands

```bash
cd /bulk/OkoNebo
python3 -m py_compile app/main.py app/weather_client.py
node --check app/static/js/app.js
bash scripts/test_harness.sh
```

## Documentation

See [docs/README.md](README.md) for the full documentation index.
