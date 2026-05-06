# OkoNebo v1.4.0 Release Notes

Release date: 2026-05-06

## Highlights

- **Security hardening pass** — XSS mitigations across six frontend render paths, Subresource Integrity on CDN scripts, non-root Docker container, and auth/secrets improvements.
- **Hourly chart improvements** — day-boundary markers ("Tomorrow", weekday+date) and a live "Now" line at interpolated current time.
- **PWA improvements** — corrected manifest icon `purpose` entries for Android maskable support, iOS apple-touch-icon, and service worker update notifications.
- **Backend reliability** — NWS station guard, PWS UTC timestamp fix, NOAA tides catalog cache, PWS history retry logic, and HA precipitation key fix.

---

## Security

- **XSS hardening** — Applied `escapeHtml()` to all server-sourced fields injected via `innerHTML`: alert cards, timeline entries, forecast/hourly cells, OWM daily rows, and alert polygon popups. Added URL scheme validation for `src` attributes.
- **Subresource Integrity** — Added `integrity` and `crossorigin="anonymous"` to Leaflet 1.9.4 and Chart.js 3.9.1 CDN tags in `index.html`.
- **Non-root container** — `Dockerfile` now creates `appuser`, `chown`s `/app`, and switches to that user before `CMD`. Eliminates root-in-container risk.
- **Auth token persistence** — `AUTH_TOKEN_SECRET` is now persisted to `SECURE_STORE` on first generation so container restarts no longer silently invalidate all sessions and revocation lists.
- **Encryption key fallback removed** — `SETTINGS_ENCRYPTION_KEY` derivation no longer falls back to the predictable `user_agent` string. A randomly generated key is used and a warning is emitted if no explicit key is configured.
- **CORS scoping** — When `AUTH_ENABLED=true`, allowed origins are read from `CORS_ALLOWED_ORIGINS` env var instead of defaulting to `*`.
- **Push subscription SSRF** — `_sanitize_push_subscription` now validates that `endpoint` starts with `https://` before storing, matching the existing webhook validation.
- **First-run race** — Auth middleware bypass now double-checks `SECURE_STORE` directly, not just the in-memory `FIRST_RUN_COMPLETE` flag, closing a restart-window race.
- **Debug endpoints hidden** — `/api/debug` and `/api/support-bundle` are now excluded from the public OpenAPI schema (`include_in_schema=False`).
- **`.dockerignore`** — Added `*.db`, `secure_settings.db`, `cache.db`, and `config.yaml` so database and live config files are never baked into a built image.

---

## Bug Fixes

- **HA weather precipitation** — `/api/ha/weather` forecast now correctly reads `precip_percent` (was `precip_probability`, which was always `null`).
- **NWS station guard** — Added bounds check before `station_data["features"][0]`; raises a clear `RuntimeError` instead of an unhandled `IndexError` on empty NWS station responses.
- **PWS history UTC** — Replaced `time.mktime(time.strptime(...))` (local wall clock) with `datetime.fromisoformat(...).timestamp()` (UTC-aware) so PWS history time-window filtering is correct on non-UTC servers.
- **Radar double-play** — Rapid Play button clicks no longer start duplicate animation loops; animation timer handle is cleared before starting a new loop.
- **localStorage array validation** — `cache.alerts`, `cache.forecast`, and `cache.hourly` are validated as arrays after API fetch and after localStorage restore, preventing `TypeError` crashes on degraded/tampered state.
- **Visibility display** — Imperial visibility now shows one decimal place (`6.2 mi`) instead of raw float precision.

---

## Hourly Chart

- Added `dayBoundaryPlugin` — dashed vertical lines at midnight crossings with "Tomorrow" / short weekday+date labels near the chart bottom.
- Added interpolated "Now" line — solid red vertical line at fractional position between hourly ticks, with "Now" label at chart top.
- Service worker cache bumped to v8.

---

## PWA

- Manifest icon entries split into separate `"purpose": "any"` and `"purpose": "maskable"` objects for correct Android launcher behavior.
- PNG icon entries added to manifest for iOS compatibility.
- `apple-touch-icon` link tag added to `index.html`.
- Service worker now posts `{ type: 'SW_UPDATE' }` to clients after a background cache refresh; dashboard shows a reload banner.

---

## Reliability & Performance

- **NOAA tides** — Station catalog is now cached separately with a 24-hour TTL; per-location prediction cache misses no longer re-fetch the entire global catalog.
- **PWS history retry** — `_pws_get_history_one` now uses `_http_get_with_retry` with 3 retries, matching `_pws_get_one`.
- **Docker HEALTHCHECK** — `Dockerfile` now includes `HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3` using `curl` on `/api/bootstrap`.
- **Pi resource limits** — `docker-compose.yml` sets `memory: 512m` / `cpus: "1.0"` limits suitable for Raspberry Pi 4/5.
- **`_upsert_env_user` deduplication** — Extracted to a single module-level helper; was previously duplicated in `_apply_config` and `_refresh_auth_users_from_store`.

---

## Dependency Updates

- `cachetools`: `7.0.6` → `7.1.1` (type stub improvements)
- `pywebpush`: `>=2.3.0,<3` → `==2.3.0` (pinned for reproducible builds)

---

## Upgrade Guidance

```bash
git pull
docker compose down
docker compose up -d --build --remove-orphans
bash health-check.sh
```

**Note for operators with custom encryption keys:** If you were relying on the `user_agent` string as an implicit encryption seed (i.e., `SETTINGS_ENCRYPTION_KEY` was not set), set it explicitly before upgrading to avoid a key mismatch on your existing `secure_settings.db`. See `INSTALL.md` for details.
