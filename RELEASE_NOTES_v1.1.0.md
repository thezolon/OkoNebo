# OkoNebo v1.1.0 Release Notes

Release date: 2026-04-05

## Highlights

- Completed the deferred post-`v1.0.x` feature backlog and stabilized the release line for `v1.1.0`.
- Added multi-location current-condition comparison, cache-backed history, and browser severe-alert Web Push support.
- Improved release polish by aligning UI behavior with provider availability, including hiding AQI when OpenWeather is not configured.

## What's New

### Dashboard and UX

- Added a `Location Compare` sidebar panel powered by `GET /api/current/multi` for compact multi-location current-condition comparison.
- Added a bounded current-condition history endpoint (`GET /api/history?hours=N`) backed by the existing SQLite cache store for lightweight charting/trend use.
- Added browser Web Push controls in the dashboard sidebar for severe-alert transitions.
- Added service-worker push handling and notification click routing back to the dashboard.
- Updated AQI panel behavior so it is hidden when OpenWeather is not configured, while still showing an unavailable placeholder when OpenWeather is configured but AQI fetches fail.

### Integrations and APIs

- Added push endpoints:
  - `GET /api/push/config`
  - `POST /api/push/subscribe`
  - `DELETE /api/push/subscribe`
- Added secure encrypted storage for Web Push VAPID keys and browser subscriptions.
- Added transition-triggered Web Push delivery for `approaching` and `active` threat-level changes.
- Corrected transition payload semantics so `previous_level` reflects the actual pre-transition state.
- Extended agent capability metadata for newly added weather endpoints.

### Reliability and Data Behavior

- Closed out the previously open API reliability workstream after reconciling the already-landed shared retry helper, `Retry-After` support, jitter, and client reuse implementation.
- Added history recording to the existing weather cache for current-condition cache types without introducing a new persistence dependency.

### Validation and Tests

- Added targeted tests for:
  - cache-backed history capture and bounded ordering
  - `/api/history` endpoint behavior
  - push subscription round-trip and transition deduplication behavior
- Extended live smoke coverage for:
  - `GET /api/current/multi`
  - `GET /api/history`
  - `GET /api/push/config`
  - dashboard push control element presence

## Validation Summary

- Full harness status: PASS
- Compile checks: PASS
- Unit tests: PASS
- Docker build/start: PASS
- Health check: PASS
- Integration smoke: PASS
- Frontend smoke: PASS
- Secret leak check: PASS

## Upgrade Notes

- Browser push notifications require a real browser subscription and notification permission grant; end-to-end device receipt should be verified once after upgrade.
- AQI remains dependent on OpenWeather configuration. When OpenWeather is disabled, the AQI panel is now hidden instead of showing a permanent unavailable state.
- Existing installs do not need a schema migration step beyond normal startup; history storage is created automatically in the existing cache database.

## Included Mainline Changes

- `88dd9e5` `feat(ui): add multi-location current comparison`
- `a7205dc` `feat(api): add cache-backed history endpoint`
- `c3e7c89` `feat(push): add browser severe alert notifications`
- `dd6e880` `fix(ui): hide AQI panel when OWM is disabled`