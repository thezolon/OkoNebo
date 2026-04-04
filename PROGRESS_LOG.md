# OkoNebo Progress Log

## Date: 2026-04-04

## Phase Snapshot
- Phase M1 (architecture/provider framework): in progress
- Phase M2 (first-run/auth completion): in progress
- Phase M3 (provider adapters): in progress
- Phase M4 (security/quality): in progress
- Phase M5 (release cut): not started

## Task Status Delta
- Completed: fallback framework for `current`, `forecast`, and `hourly` in `app/main.py`
- Completed: WeatherAPI adapters (`current`, `forecast`, `hourly`) in `app/weather_client.py`
- Completed: Tomorrow.io adapters (`current`, `forecast`, `hourly`) in `app/weather_client.py`
- Completed: Visual Crossing adapters (`current`, `forecast`, `hourly`) in `app/weather_client.py`
- Completed: provider capability metadata exposed via `/api/bootstrap` and `/api/settings`
- Completed: initial fallback test file `tests/test_provider_fallback.py`
- Completed: reliable local test harness (`scripts/test_harness.sh`) to remove host environment drift
- Completed: setup/auth integration test suite `tests/test_setup_auth_integration.py` covering first-run bootstrap transition and auth login/logout paths
- Completed: harness unit test stage expanded to run 16 tests across fallback + setup/auth integration
- Completed: frontend smoke test `tests/frontend_smoke.py` for setup + first-run controls and map-provider options, now wired into harness
- Completed: duplicate frontend `setupStatus()` declaration removed in `app/static/js/app.js`

## Current Risks
- Host Python dependency drift can break local test execution even when container runtime is healthy.
- Fallback chain complexity grows with each provider and needs automated coverage.

## Next Actions
1. Add frontend smoke tests for setup/map-provider selection (T7.3).
2. Final docs pass for setup/auth/providers/security with fresh-install walkthrough validation (T8.4).
3. Start release engineering cut tasks (T9.1-T9.3): freeze policy, tag flow, checksums script.
