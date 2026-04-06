# OkoNebo v1.2.0 Release Notes

Release date: 2026-04-05

## Highlights

- Added comprehensive `docs/` documentation set and consolidated root-level docs.
- Added in-app admin docs viewer at `/admin-docs.html` with admin-gated API access and markdown rendering.
- Added runtime version visibility in both dashboard and admin UI.
- Renamed Docker Compose service/container to `okonebo` and standardized related scripts/docs.
- Set explicit Compose image name to `okonebo:latest`.
- Added CI markdown link checking and Bandit security scan step.
- Expanded CI unit testing to unittest discovery across `tests/test_*.py`.
- Decoupled AQI from OpenWeather key requirement:
  - OpenWeather AQI remains preferred when configured.
  - Keyless Open-Meteo AQI fallback added and enabled automatically.
- Fixed AQI dashboard visibility so fallback-source AQI displays correctly.

## API and Runtime Changes

- `/api/aqi` now supports provider fallback and returns `source` metadata (`openweather` or `openmeteo`).
- `/api/bootstrap`, `/api/config`, and `/api/settings` include `runtime_version` metadata.
- Admin docs endpoints added:
  - `GET /api/admin/docs`
  - `GET /api/admin/docs/{path}`

## Operational Notes

- Existing `weather-app` containers from older compose versions may remain as orphans; startup paths now use `--remove-orphans`.
- Docker image metadata label updated to `1.2.0`.

## Validation Summary

- Full test harness passes:
  - compile checks
  - unit tests
  - Docker build/start
  - health checks
  - integration smoke
  - frontend smoke
  - secret leak check

## Upgrade Guidance

```bash
git pull
docker compose down
docker compose up -d --build --remove-orphans
bash health-check.sh
```
