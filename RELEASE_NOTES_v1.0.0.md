# OkoNebo v1.0.0 Release Notes

Release date: 2026-04-04

## Highlights

- Public v1.0.0 baseline with Docker-first deployment and full local API docs.
- Deterministic provider fallback for core weather endpoints.
- First-run blocking setup overlay for fresh installs.
- Encrypted settings persistence for provider API keys and runtime setup.
- Optional auth roles (admin/viewer) with login protections and token revocation.
- CI pipeline with test + security + Docker gates.

## What's New

### Providers and Data

- Added provider adapters:
  - Meteomatics (current conditions, keyed `username:password`)
  - AviationWeather (METAR, keyless)
  - NOAA CO-OPS (tides, keyless)
- Expanded provider capabilities metadata and upstream call stats.
- Added new endpoints:
  - `GET /api/metar`
  - `GET /api/tides?days=1`

### Setup and UX

- Added full-screen first-run overlay that blocks dashboard until setup is saved.
- Keyless providers default enabled; keyed providers are opt-in by API key.
- Setup panel remains editable after install.
- Added client-side coordinate validation in setup flows.

### Security and Auth

- Added login rate limiting: 10 failed attempts per 5 minutes per IP.
- Added JWT token denylist and `POST /api/auth/logout` token revocation.
- Enforced admin-only writes to settings when auth is enabled.
- Added [SECURITY.md](SECURITY.md) disclosure policy.

### Testing and CI

- Unit tests expanded to 16 focused tests:
  - provider fallback metadata behavior
  - auth/settings write-guard behavior
- Added CI workflow: compile checks, pytest, Bandit, Docker build, health check, integration smoke.
- Health/smoke semantics updated for fresh installs:
  - weather endpoints accept `200` or `502` before location/provider setup

### OSS Governance and Docs

- Added:
  - [LICENSE](LICENSE) (MIT)
  - [CONTRIBUTING.md](CONTRIBUTING.md)
  - [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
  - [ARCHITECTURE.md](ARCHITECTURE.md)
  - Issue templates and PR template under [.github](.github)
- Added [config.yaml.example](config.yaml.example) for first-time setup.
- README updated for public release guidance.

## Validation Summary

- Full harness status: PASS
- Unit tests: PASS (16/16)
- Docker build/start: PASS
- Health check: PASS
- Integration smoke: PASS
- Secret leak check: PASS

## Upgrade Notes

- Fresh installs should copy [config.yaml.example](config.yaml.example) to `config.yaml`.
- Existing installs can continue using current config, but should review new provider and auth options.
- If enabling auth, set credentials in `.env` and validate access control before internet exposure.

## Known Behavior

- On fresh installs without valid location/provider data, core weather endpoints may return `502`; this indicates app is running but no upstream source is currently available.
- Once setup is saved, `/api/bootstrap` reports `first_run_required=false` and normal data polling starts.
