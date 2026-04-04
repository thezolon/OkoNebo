# OkoNebo Progress Log

## Date: 2026-04-04

## Phase Snapshot
- Phase M1 (architecture/provider framework): COMPLETE
- Phase M2 (first-run/auth completion): COMPLETE
- Phase M3 (provider adapters): COMPLETE
- Phase M4 (security/quality): COMPLETE
- Phase M5 (release cut): in progress

## Recent Completions (Admin Panel UX Overhaul)

### Runtime Hardening & Observability (4/4/26)
- Added strict settings validation for timezone, labels, usernames, password strength, user-agent, PWS station limits, and provider API key constraints.
- Added startup-safe config parsing and runtime timezone sanitization to prevent invalid config from breaking app behavior.
- Introduced request correlation IDs (`X-Request-ID`) on API responses for easier incident tracing.
- Added structured JSON event logging for auth denials, token create/revoke, provider attempts, rate-limit blocks, and settings saves.
- Added provider outcome counters in debug payload (`provider_outcomes`) for quick fallback performance visibility.
- Expanded resilience tests to cover timeout, rate-limited fallback, and 503 fallback scenarios.

### Weather Client Telemetry Expansion (4/4/26)
- Added runtime retry telemetry by upstream provider (`attempted`, `exhausted`) and exposed it through `/api/stats`.
- Added cache runtime telemetry (`memory_hit`, `sqlite_hit`, `miss`, `stale_hit`, `singleflight_wait`, `refresh`, `refresh_error`) to improve cache behavior diagnostics.
- Instrumented single-flight refresh contention tracking to identify stampede pressure under concurrency.
- Added direct telemetry unit tests for retry exhaustion accounting and cache hit/miss/set counters.

### Debug Health Signals (4/4/26)
- Added computed observability health summary in `/api/debug` with `overall`, retry pressure, cache pressure, and rate-limit pressure indicators.
- Added derived metrics (`retry_attempted_total`, `retry_exhausted_total`, `cache_hit_ratio`, `cache_lookups`) for faster triage.
- Added debug endpoint unit tests that assert healthy and degraded scenarios based on synthetic telemetry.
- Added an admin-facing Observability Health card with quick pressure badges, retry/cache diagnostics, and manual refresh.
- Extended frontend smoke checks to require observability card element IDs in `/admin.html`.

### Stabilization Pass (4/4/26)
- Updated test harness to include new observability and telemetry unit test modules in both compile checks and unittest execution.
- Fixed admin token details toggle label consistency (`Expand`/`Collapse`) to avoid mismatched initial button state.
- Re-ran full harness with expanded test set; all checks passing.

### Observability Live Refresh (4/4/26)
- Added automatic observability polling in admin (45s interval) with visibility-aware refresh when tab focus returns.
- Added staleness indicator (`obs-stale`) that shows telemetry age and warns when data is older than 120 seconds.
- Extended frontend smoke checks to require the staleness element in admin diagnostics.

### Observability Action Guidance (4/4/26)
- Added backend-generated observability recommendations in `/api/debug` based on retry, cache, and rate-limit pressure levels.
- Surfaced recommendations in the admin diagnostics card (`obs-actions`) so operators can act immediately from current telemetry.
- Extended debug unit tests and frontend smoke checks to validate recommendation payload and card element presence.

### Observability Trend History (4/4/26)
- Added rolling client-side history (`obs-history`) in admin diagnostics that shows recent observability snapshots across auto-refresh intervals.
- Keeps latest history bounded to avoid unbounded growth while still preserving short-term trend visibility.
- Extended frontend smoke checks to assert history element presence.

### Dashboard Observability Surface (4/4/26)
- Added observability visibility directly into the main dashboard `System Status` panel (`debug-observability`, `debug-pressure`, `debug-guidance`).
- Wired dashboard debug renderer to show overall health, compact pressure summary, and top recommended action from `/api/debug`.
- Extended frontend smoke checks to require the new dashboard observability field IDs.

### Dashboard Observability UX Polish (4/4/26)
- Improved pressure line readability with labeled tokens (`Retry`, `Cache`, `Rate`) and per-pressure visual chips.
- Added trend indicator (`debug-trend`) that shows improving/stable/worsening direction from recent observability snapshots.
- Shortened guidance text for sidebar readability while preserving priority action intent.

### Right-Panel Real Estate Controls (4/4/26)
- Added collapsible controls for non-weather right-panel sections: `System Status`, `Admin`, `Viewer Help`, and `Ops Timeline`.
- Added persistent collapse state via localStorage so panel preferences survive refreshes.
- Defaulted utility sections (`Admin`, `Viewer Help`, `Ops Timeline`) to collapsed to preserve map/forecast focus.
- Added `Reset Layout` action in `System Status` to restore default collapsed/open utility panel layout instantly.
- Added `Compact` quick action in `System Status` to collapse all utility right-panel sections in one click, and toggle back to `Expand`.
- Added right-panel layout status hint and `Shift+C` keyboard shortcut for fast compact/expand toggling.
- Added comprehensive UI behavior test suite for panel layout controls (7 tests covering all controls and accessibility).
- Enhanced admin observability history display to show visual health trend indicators (colored dots: 🟢 healthy, 🟡 warning, 🔴 degraded) with timestamp and detailed pressure tooltips.
- Improved mobile responsiveness with enhanced touch targets for buttons/toggles on tablets (900px) and phone optimizations (480px).

### Observability Stability Signals (4/4/26)
- Added backend observability runtime tracking for state transitions, flaps in the last 10 minutes, and time since last status change.
- Added dashboard `Stability` field showing stable/watch/flapping with transition cadence context.
- Extended debug observability tests and frontend smoke checks for new stability signal coverage.

### Pull Cycle Integration (4/4/26)
- Moved provider pull cycle controls into unified provider cards (enables + API key + pull cycle all together)
- Removed separate "Provider Pull Cycles" section
- Added help text (title attributes) explaining pull cycle behavior
- Every provider card now shows: Enable toggle, API Key field, Pull Cycle (seconds) input

### Safety & Confirmation Features (4/4/26)
- Unsaved changes detection with visual indicator (⊙ yellow circle)
- beforeunload warning prevents accidental navigation with pending changes
- Delete token confirmation dialog: "Delete token 'X'? This cannot be undone."
- All destructive operations now require explicit confirmation

### User Experience Improvements (4/4/26)
- Ctrl+S (Cmd+S on Mac) keyboard shortcut to save settings instantly
- Sticky Save/Discard buttons at top of form (always visible while scrolling)
- Discard Changes button reverts to last saved state with confirmation
- Copy to clipboard button for agent tokens (shows "✓ Copied!" feedback)
- "Test All" button tests only enabled providers (avoids wasting API calls)
- Per-field help text and better form organization with card-based layout

### Token Management (4/4/26)
- Token value shown once at creation with prominent warning
- Copy button appears immediately after creation
- Token list never shows full token value, only name/creation time/delete
- Expandable token details card with scopes, timestamps, security warning
- "Delete" button (clearer than "Revoke") with confirmation

## Task Status Delta
- Completed: Pull cycle controls integrated into provider cards
- Completed: Unsaved changes detection with visual feedback
- Completed: Delete confirmation dialogs for tokens
- Completed: Test All Providers button (enabled-only)
- Completed: Keyboard shortcut (Ctrl+S) for saving
- Completed: Copy to clipboard for tokens
- Completed: Persistent sticky Save/Discard buttons
- Completed: Help text on confusing fields
- Completed: Form state tracking with visual indicator
- Completed: Tests updated to reflect new structure (test_harness, frontend_smoke)

## Current Risks
- None at this phase; all features validated by test harness.

## Next Actions
1. Final documentation review and release notes generation.
2. Tag release and generate checksums.
3. Deploy to production and monitor stability before public announcement.
