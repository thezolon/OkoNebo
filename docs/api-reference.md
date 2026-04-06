# API Reference

All endpoints are served at the base URL (default `http://localhost:8888`). The OpenAPI schema is available at `/openapi.json` and the interactive Swagger UI at `/docs`.

---

## Authentication

When `AUTH_ENABLED=true`, include a bearer token header:

```
Authorization: Bearer <token>
```

Most read endpoints accept both admin session tokens and scoped agent tokens. Write endpoints require an admin session token. See [authentication.md](authentication.md) and [agents.md](agents.md).

---

## Weather Endpoints

All weather endpoints require agent scope `weather.read` when auth is enabled.

### `GET /api/current`

Current surface observations from the nearest NWS automated station, with provider fallback.

| Field | Type | Description |
|-------|------|-------------|
| `temp_f` | number | Temperature °F |
| `feels_like_f` | number | Feels-like temperature °F |
| `dewpoint_f` | number | Dewpoint °F |
| `humidity` | number | Relative humidity % |
| `wind_speed_mph` | number | Wind speed mph |
| `wind_direction` | string | Wind direction (e.g. `"SW"`) |
| `pressure_inhg` | number | Barometric pressure inHg |
| `visibility_miles` | number | Visibility miles |
| `description` | string | Short text description |
| `source` | string | Provider used |
| `station` | string | Observation station identifier |

Returns `502` with `attempted`/`errors` detail if all providers fail.

---

### `GET /api/current/multi`

Current conditions for all configured monitored locations, fetched in parallel.

Query: *(none)*

```json
{
  "locations": [
    { "label": "Home", "role": "primary", "lat": 36.15, "lon": -95.99, "ok": true, "current": {...}, "error": null },
    { "label": "Office", "role": "secondary", "lat": 36.16, "lon": -95.98, "ok": true, "current": {...}, "error": null }
  ],
  "requested_count": 2,
  "success_count": 2,
  "failure_count": 0,
  "updated_at": 1712345678.0
}
```

See [multi-location.md](multi-location.md).

---

### `GET /api/forecast`

7-day forecast, day/night periods. Cached 15 min.

Returns a list of forecast period objects. Each period includes `start_time`, `temperature`, `wind_speed`, `wind_direction`, `short_forecast`, `detailed_forecast`, `precip_probability`, `is_daytime`.

---

### `GET /api/hourly`

48-hour hourly forecast. Cached 15 min.

Returns a list of hourly objects with `start_time`, `temperature`, `wind_speed`, `wind_direction`, `precip_probability`, `short_forecast`.

---

### `GET /api/history`

Historical current-condition snapshots for trend charting.

| Query parameter | Type | Default | Range | Description |
|-----------------|------|---------|-------|-------------|
| `hours` | integer | `6` | 1–24 | How many hours of history to return |

Returns a list of timestamped observation snapshots in ascending chronological order, drawn from the local SQLite cache.

---

### `GET /api/alerts`

Active NWS weather alerts for all monitored locations. Cached 5 min.

Returns `{ "alerts": [...], "updated_at": ... }`. Each alert includes `id`, `event`, `severity`, `urgency`, `certainty`, `headline`, `description`, `instruction`, `expires`, `geometry` (GeoJSON when available), and `locations` (which monitored points are affected). Returns `{ "alerts": [] }` when no alerts are active.

---

### `GET /api/metar`

Latest aviation METAR from AviationWeather. Keyless. Cached 10 min.

Includes `raw_metar`, `temp_c`, `dewpoint_c`, `wind_dir_degrees`, `wind_speed_kt`, `visibility_statute_mi`, `altim_in_hg`, `ceiling_ft`, `flight_category` (`VFR`/`MVFR`/`IFR`/`LIFR`), `station_id`.

Returns `{ "available": false }` if the provider is disabled.

---

### `GET /api/tides`

NOAA CO-OPS tide predictions. Keyless. Cached 30 min.

| Query parameter | Type | Default | Range | Description |
|-----------------|------|---------|-------|-------------|
| `days` | integer | `2` | 1–7 | Number of days of predictions |

Returns `{ "station": {...}, "predictions": [...] }`. Each prediction has `t` (ISO timestamp), `v` (water level ft), `type` (`H`/`L`).

Returns `{ "available": false }` if the provider is disabled.

---

### `GET /api/owm`

OpenWeather One Call 3.0 supplemental data. Cached 10 min.

Returns `current`, `hourly` (48-entry list), `daily` (8-entry list), `alerts` (OWM alert list), `timezone`.
Returns `{ "available": false }` if OWM is not configured.

---

### `GET /api/pws`

Personal weather station observations. Cached 2 min.

Returns `{ "provider", "stations": [...], "errors": [...], "updated_at", "available" }`.
Returns `{ "available": false }` if PWS is not configured.

---

### `GET /api/pws/trend`

PWS observation trend series for sparkline charts.

| Query parameter | Type | Default | Range |
|-----------------|------|---------|-------|
| `hours` | integer | `3` | 1–24 |

---

### `GET /api/astro`

Astronomical data for the configured location. Computed locally (no external API call). Cached 6 h.

Returns `sunrise`, `sunset`, `solar_noon`, `golden_hour_start`, `golden_hour_end`, `moon_phase` (string), `moon_illumination` (0–1), `day_length_minutes`.

---

### `GET /api/aqi`

Air Quality Index from OpenWeatherMap. Requires OWM key. Cached 30 min.

Returns `{ "available": bool, "aqi": 1-5, "components": {...}, "timestamp": ... }`.

AQI scale: 1 = Good, 2 = Fair, 3 = Moderate, 4 = Poor, 5 = Very Poor.

---

## Configuration Endpoints

Scope `config.read` required when auth is enabled.

### `GET /api/config`

Location and integration availability snapshot.

```json
{
  "lat": 36.15, "lon": -95.99, "label": "Home", "timezone": "America/Chicago",
  "alert_locations": [...],
  "owm_available": true,
  "pws_available": false,
  "pws_provider": "weather.com",
  "pws_station_count": 0,
  "map_provider": "esri",
  "providers": { "nws": { "enabled": true }, "weatherapi": { "enabled": false }, ... }
}
```

---

### `GET /api/bootstrap`

First-run state and provider configuration.

```json
{
  "first_run_required": false,
  "auth": { "enabled": false, "require_viewer_login": false },
  "providers": {
    "nws": { "enabled": true, "requires_api_key": false, "configured": true, "capabilities": ["current","forecast","hourly","alerts"] },
    ...
  },
  "map": { "provider": "esri", "options": ["esri","osm","carto-light","carto-dark"] }
}
```

---

### `GET /api/settings`

Full runtime settings (admin). Includes cache TTLs, auth config, and provider state.

### `POST /api/settings`

Save settings (admin). Body fields: `location`, `pws`, `auth`, `providers`, `map`, `cache`, `mark_first_run_complete`.

---

### `GET /api/capabilities`

Agent tool manifest. See [agents.md](agents.md).

---

## Integration Endpoints

### `GET /api/ha/sensor`

Home Assistant REST sensor payload. See [home-assistant.md](home-assistant.md).

### `GET /api/ha/weather`

Home Assistant weather entity payload. See [home-assistant.md](home-assistant.md).

---

## Webhook Endpoints (admin only)

See [webhooks.md](webhooks.md) for the full guide.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/webhooks` | List webhooks and delivery stats |
| `POST` | `/api/webhooks` | Add a webhook URL |
| `POST` | `/api/webhooks/{id}/test` | Send test delivery |
| `DELETE` | `/api/webhooks/{id}` | Delete a webhook |

---

## Push Notification Endpoints

See [push-notifications.md](push-notifications.md) for the full guide.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/push/config` | VAPID public key + subscription count (public) |
| `POST` | `/api/push/subscribe` | Store a browser push subscription |
| `DELETE` | `/api/push/subscribe` | Remove a browser push subscription |

---

## Auth Endpoints

See [authentication.md](authentication.md) for the full guide.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/auth/config` | Auth mode (enabled/viewer-login-required) |
| `POST` | `/api/auth/login` | Login → bearer token (rate-limited) |
| `POST` | `/api/auth/logout` | Revoke current token |
| `GET` | `/api/auth/me` | Current identity |
| `GET` | `/api/agent-tokens` | List agent tokens (admin) |
| `POST` | `/api/agent-tokens` | Create agent token (admin) |
| `DELETE` | `/api/agent-tokens/{id}` | Revoke agent token (admin) |

---

## Debug / Diagnostics Endpoints

Scope `debug.read` required when auth is enabled.

### `GET /api/stats`

Provider call counts since server start.

```json
{ "nws": 42, "weatherapi": 0, "tomorrow": 0, ... }
```

### `GET /api/debug`

Full runtime diagnostics snapshot: request counts, error rates, recent event timeline, last client-side metric snapshot.

### `GET /api/support-bundle`

Safe-to-share redacted bundle. No keys, no coordinates, no passwords. See [support-troubleshooting.md](support-troubleshooting.md).

---

## Provider Test Endpoint (admin)

```
POST /api/test-provider
Authorization: Bearer <admin_session_token>
Content-Type: application/json

{
  "provider": "weatherapi",
  "api_key": "test-key-value"
}
```

Returns `{ "ok": true, "provider": "...", "message": "..." }` on success or a `400`/`502` with a descriptive error.
`api_key` goes in the JSON body (never in the URL) to prevent logging in browser history or server access logs.

---

## Agent Discovery Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /.well-known/okonebo-agent.json` | Machine-readable agent profile |
| `GET /.well-known/okonebo-agent-instructions.txt` | Plain-text agent instructions |
| `GET /api/capabilities` | Full tool + scope manifest |

---

## HTTP Status Codes

| Code | Meaning |
|------|---------|
| `200` | Success |
| `400` | Bad request — invalid parameter, missing key, config error |
| `401` | Not authenticated |
| `403` | Authenticated but insufficient role/scope |
| `404` | Resource not found |
| `413` | Payload too large |
| `429` | Rate limit exceeded (login endpoint) |
| `502` | All upstream weather providers failed; body contains attempted list and per-provider errors |
| `503` | Service/provider disabled |
