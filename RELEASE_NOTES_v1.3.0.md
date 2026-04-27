# OkoNebo v1.3.0 Release Notes

Release date: 2026-04-27

## Highlights

- Added Fire Watch support with a keyless wildfire incident feed (`/api/firewatch`) based on NIFC incident data.
- Added viewport-aware alert and fire behavior on the map so overlays and sidebar cards track current map bounds.
- Added capability-gated API UI behavior so key-required OpenWeather controls are hidden/disabled when unavailable while keyless features remain available.
- Added background cache warming loop to improve first-load responsiveness for weather, alerts, fire incidents, and AQI fallback data.
- Added Fire Watch API tests for success and graceful upstream-failure behavior.

## API and Runtime Changes

- New endpoint: `GET /api/firewatch`
  - Supports multi-location aggregation and viewport bounding-box queries.
  - Returns de-duplicated incidents including location, acreage, containment, and nearest monitored location.
- Updated endpoint: `GET /api/alerts`
  - Adds optional viewport bounding-box query support for map-scoped alert retrieval.
- Agent capability metadata updated to include Fire Watch coverage under `weather.read`.

## Frontend and UX

- Added Fire Watch section in the sidebar with incident cards and viewport-sensitive counts.
- Added fire overlay mode to radar map controls.
- Added alert layer subtype filters (tornado/flood/thunderstorm).
- Added return-home map control and improved viewport refresh orchestration.

## Dependency Updates

Consolidated Dependabot updates included in this release:

- `fastapi`: `0.135.3` -> `0.136.1`
- `uvicorn[standard]`: `0.43.0` -> `0.46.0`
- `cachetools`: `7.0.5` -> `7.0.6`
- `cryptography`: `46.0.6` -> `47.0.0`
- `pywebpush`: `>=1.14,<3` -> `>=2.3.0,<3`
- `mcp`: `>=1.2.0` -> `>=1.27.0`

## Operational Notes

- Docker OCI image metadata label updated to `1.3.0`.
- Runtime default version updated to `1.3.0`.
- Example `user_agent` version updated in `config.yaml.example`.

## Validation Summary

- Docker-based unit validation completed, including Fire Watch test module.
- Full project unit test set used by the harness passed in Docker (61 tests).

## Upgrade Guidance

```bash
git pull
docker compose down
docker compose up -d --build --remove-orphans
bash health-check.sh
```
