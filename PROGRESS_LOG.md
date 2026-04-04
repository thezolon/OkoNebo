# WeatherApp Progress Log

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

## Current Risks
- Host Python dependency drift can break local test execution even when container runtime is healthy.
- Fallback chain complexity grows with each provider and needs automated coverage.

## Next Actions
1. Expand fallback tests to cover forecast/hourly failure details and attempted-provider metadata.
2. Add CI workflow to run `scripts/test_harness.sh` on pull requests.
3. Add adapter-specific contract tests for each keyed provider.
