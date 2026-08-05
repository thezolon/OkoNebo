# OkoNebo Remediation Plan

**Created:** 2026-08-05
**Scope:** full code review, AI-slop resolution, cleanup, and the outstanding findings from the 2026-08-05 frontend audit.

---

## What this plan is built on

| Source | Coverage | Status |
|---|---|---|
| Dependabot triage + MCP migration | `requirements*.txt`, `scripts/mcp_server.py`, CI | Done — PR #102 |
| Impeccable audit + critique (dual-agent) | `app/static/**` — 9061 lines | Done — `.impeccable/critique/2026-08-05T14-29-00Z__app-static.md` |
| Alert-safety fixes | `app.js`, `style.css` alert paths | Done — PR #103 |
| Reliability diagnosis + fix | `weather_client.py` cache/timeout path | Done — PR #105 |
| Backend review — auth, tokens, crypto, cache, redaction | `main.py` auth surface, `secure_settings.py`, `cache_db.py`, `redaction.py` | Done — see Phase 2 findings |
| **Backend review — remainder** | rest of `weather_client.py` (2473L), `astro.py`, input validation across ~40 more routes | **Outstanding** |

**Honest gap:** the backend review is partially complete. The auth/crypto/cache/redaction pass is done and its findings are recorded in Phase 2; the remaining routes and provider code are not yet reviewed, so item counts below remain a floor rather than a total.

**Scores at baseline:** design 19/40 (Poor) · technical audit 7/20 (Poor).

---

## Decisions taken (2026-08-05)

These were open questions at the end of the first draft. All are now settled and the plan below reflects them.

| # | Question | Decision |
|---|---|---|
| 1 | Branch-protection review requirement | The maintainer is the checkpoint. GitHub cannot express "approve your own PR", so required approvals moved 1 → 0 while **keeping** the required `ci` check, `strict` up-to-date enforcement, and the no-force-push/no-delete rules. Merging is a two-party agreement in conversation, not a GitHub approval click. `--admin` is *not* routine — it would bypass CI as well as review. |
| 2 | METAR and tides | **Render them**, as an optional user-selectable layer/choice rather than always-on. |
| 3 | Visual redesign vs mechanical fixes | *"Attractive, but form must follow function. If the data isn't good, making it look pretty means nothing."* → correctness, reliability and accessibility land **before** any visual pass. The visual work is then scoped as "make the fixed thing attractive", not "redesign the broken thing". |
| 4 | Backend review depth | **Full sweep**, not just auth/crypto. |
| 5 | The two monolith refactors | **Yes** — they are justified as v2 preparation. |

**Framing change:** the target is a **v2 release**, not maintenance. That is why the refactors are in scope.

**Direction added:** *"I am a fan of multiple sources that are aggregated."* — see Phase R.

---

## Phase R — Data availability and reliability  *(highest priority)*

Promoted above everything else by decision #3's own logic: a blank panel **is** the data not being good, so it outranks making anything look better. This is also the defect actually experienced in daily use.

**Diagnosis (measured, not inferred).** The viewer's empty current-conditions panel was a timeout budget mismatch. The browser aborts at 20s (`app.js:2097`); server-side, httpx allowed 15s per attempt × 3 attempts ≈ 46s per upstream call, `/api/current` chains three of those (~140s), and only then falls back **sequentially** through four more providers (~186s). The client always hung up first. Worse, `_get_or_refresh_shared` already had a serve-stale-on-error path — but it only ran *after* the upstream attempts finished, so the safety net was unreachable in exactly the scenario it was built for.

| # | Item | Status |
|---|---|---|
| R.1 | Bound per-attempt cost (connect 3.05s / read 6s / write 6s / pool 3s) | Done — PR #105 |
| R.2 | Stale-while-revalidate: serve the cached reading immediately, refresh off the request path | Done — PR #105 |
| R.3 | Bound stale age (6× TTL, floor 15 min, hard cap 1 hour) so old weather is never presented as current | Done — PR #105 |
| R.4 | **Parallel provider fan-out** replacing the sequential fallback chain — first good answer wins, blend when several return | **To do — the main aggregation work** |
| R.5 | Per-provider circuit breaker: skip recently-failed sources so a down provider stops costing latency. Telemetry to drive it already exists (`_track_provider_outcome`, retry stats) | To do |
| R.6 | Hard per-endpoint server deadline, comfortably inside the client abort | To do |
| R.7 | Surface freshness honestly in the UI when a served-stale value is shown (the per-source age grid already exists for this) | To do |

R.4 is the substantive delivery of what the UI already promises: **"Auto Blend" is the default source in the viewer today**, while the backend merely fails over one provider at a time. Sequential failover means more sources make the app *slower*; parallel aggregation means more sources make it *more reliable*.

**Effort:** R.4–R.6 are M–L. **Risk:** medium — touches the request path; needs the existing provider-fallback tests kept green.

---

## Phase 0 — Unblock the merge pipeline

**Status: complete.** The Dependabot backlog is cleared and zero PRs remain open.

| # | Item | Outcome |
|---|---|---|
| 0.1 | Review requirement | Resolved per decision #1 — approvals 1 → 0, `ci` check and `strict` retained |
| 0.2 | PR #102 | Merged — deps + MCP v2 + aggregate `ci` job |
| 0.3 | PR #103 | Merged — alert-safety P0s |
| 0.4 | #95, #88 | Merged — Actions bumps |
| 0.5 | #101, #100, #98, #96, #85, #99, #84 | Closed as superseded, each with a stated reason |

Root cause, for the record: branch protection required a status check named `ci`, but GitHub reports check names per **job**, and no job carried that name — so the required context was never reported and every PR sat `BLOCKED` no matter how green it was. #102 added an aggregate `ci` job that depends on the other three and asserts each result explicitly (`needs` alone is insufficient — with `if: always()` a skipped dependency would otherwise pass).

---

## Phase 1 — Safety and correctness

Defects where the product does the wrong thing, not merely an ugly thing. Ordered by consequence.

| # | Item | Evidence | Size |
|---|---|---|---|
| 1.1 | ~~Render NWS `instruction`~~ | Done — PR #103 | — |
| 1.2 | ~~Stop test alerts impersonating real ones~~ | Done — PR #103 | — |
| 1.3 | Alert badge and ticker disagree | `#alert-count` counts viewport-filtered alerts; ticker counts all effective alerts. Pan the map away → badge reads 0 while the ticker still warns. Pick one meaning. | S |
| 1.4 | Admin "Test All" cannot report failure | `testProvider` swallows its own errors and never rethrows, so `failed` is structurally always 0 (`admin.js:749` vs `831-861`). Always prints `✓ N passed`. Return a boolean and count on it. | S |
| 1.5 | SW update spam in the error channel | `sw.js:47` posts `SW_UPDATE` per revalidated asset; `app.js:128` routes it to `showError()` — up to six red error toasts per normal page load. Route to a neutral notice, fire once. | S |
| 1.6 | Timezone honored in exactly one render path | `renderOwmDaily` passes `timeZone` (with a literal `TODO`); `formatTime`/`formatHM` use browser locale everywhere else — **including alert expiry times**. | M |
| 1.7 | Celsius mode is half-metric | `displayPressure` always returns inHg; PWS cards hardcode `in`, `°F`, `inHg`; HTML placeholders hardcode `-- inHg` / `-- mi`. | M |
| 1.8 | `navigator.clipboard` undefined on plain-http LAN | The default self-hosted Pi deployment. "Copy Token" throws silently and the one-time-visible token is lost. Add a `execCommand` fallback + visible failure state. | S |
| 1.9 | Revoked agent tokens can never be deleted | Delete is `disabled` when `item.revoked` (`admin.js:581`). List grows unbounded. | S |
| 1.10 | Unsaved-changes guard excludes API keys and passwords | `hasFormChanged()` skips them while `markUnsaved` fires on them — the indicator and the exit guard disagree. Close the tab after typing a key → no warning. | S |
| 1.11 | `apple-touch-icon` 404 | Points at `/okonebo-icon-192.png`; there is not a single `.png` in the repo. `manifest.json` lists two more. iOS rejects SVG here → no home-screen icon. Generate PNGs (ffmpeg is available). | S |

**Effort:** M total. **Risk:** low — all narrow, all testable.

---

## Phase 2 — Backend + security code review

The unreviewed half. This is a review phase; it produces findings, then a fix batch.

**Targets and focus:**

| Area | Why it needs eyes |
|---|---|
| `main.py` auth middleware (`api_auth_guard`, `api_rate_limiter`) | Just carried CVE-2026-48710 (BadHost, Host-header auth bypass). The neighboring logic deserves the same scrutiny the CVE got. |
| Token lifecycle | `_make_token`, `_decode_token`, `_revoke_token`, denylist load/persist. Check expiry validation, denylist race conditions, revocation durability across restart. |
| Password handling | `_hash_password`, `_verify_password`, salt handling, `_validate_password_strength`. Confirm the KDF is not a bare hash. |
| `secure_settings.py` (Fernet) | Key derivation and storage, key rotation story, what happens when the key is lost. |
| VAPID keypair | `_generate_vapid_keypair`, `_get_or_create_push_vapid_keys` — private key at rest, permissions. |
| Provider fetch paths in `weather_client.py` | SSRF surface: are provider URLs ever influenced by user-supplied config? Timeouts, retry amplification, response-size bounds. |
| `redaction.py` | Verify secrets cannot reach logs or the support bundle; check it against the actual log call sites. |
| Input validation (`_sanitize_*`, `_validate_runtime_config`) | 53 routes; confirm the sanitizers are actually applied on every write path, not just the settings endpoint. |
| `cache_db.py` | SQL construction, concurrent access from the cache-warm loop. |
| **Anti-AI-poisoning** | Standing project requirement. Alert text, METAR, and firewatch descriptions are untrusted upstream content rendered into the UI and exposed via MCP tools to agent runtimes. Provenance and injection screening need to exist on that path. |

**Method:** targeted review per area, findings tagged P0–P3 with file:line, then a fix batch.

### Findings so far (auth / tokens / crypto / cache / redaction — complete)

**Verified sound, no action:** PBKDF2-SHA256 at 120k rounds with per-user salts and `compare_digest`; HMAC token signatures verified *before* the payload is parsed; agent-token revocation durable across restart (reloaded at `main.py:434`); a dedicated login brute-force limiter (10 / 5 min / IP) on top of the global one; webhooks properly admin-gated at handler level via `_require_admin_identity`; `cache_db.py` fully parameterised (its one `# nosec B608` interpolates only generated `?` placeholders) with WAL mode and a thread lock; `redaction.py` thorough and installed after `basicConfig`; **all provider base URLs are hardcoded constants** with query values passed through httpx `params=`, and lat/lon coerced via `_safe_float` — so there is no SSRF-via-config surface.

| # | Finding | Sev |
|---|---|---|
| 2.1 | **Push subscribe/unsubscribe are unauthenticated.** `api_push_subscribe` (`main.py:1634`) does not take `request` and so cannot check identity; it is absent from `admin_only`, and `AUTH_REQUIRE_VIEWER_LOGIN` defaults to False. Only validation is `startswith("https://")`. Enables outbound amplification (the server POSTs to every stored endpoint on each severe alert), unbounded store growth, and — worst — **silent alert suppression**, since anyone knowing a real subscriber's endpoint can unsubscribe them. | P1 |
| 2.2 | **Settings encryption key is not KDF-derived.** `secure_settings.py:22` is a single unsalted SHA-256 of the seed. The seed is a hand-set env var, so a human passphrase is the likely input, making the Fernet key offline-brute-forceable from the DB file — which holds provider API keys, password hashes and the VAPID private key. `_hash_password` in the same codebase does this correctly; the technique just was not applied here. Needs a migration path. | P1 |
| 2.3 | **Anti-poisoning: absent.** Grep across `app/*.py` and `scripts/mcp_server.py` for injection screening, provenance or untrusted-content handling returns **zero hits**. Alert text, METAR, PWS station names and firewatch descriptions flow upstream → UI *and* → MCP tools verbatim. XSS is handled (`escapeHtml`); prompt injection is not. Violates the standing project requirement, and the MCP path makes it concrete. | P1 |
| 2.4 | Rate limiting defeated behind a reverse proxy — keys on `request.client.host` with no proxy-header handling anywhere. All clients share one bucket. | P2 |
| 2.5 | `_RATE_LIMIT_BUCKETS` (`defaultdict(deque)`) never evicts keys; reading creates them. Slow unbounded growth. | P2 |
| 2.6 | No response size limit on `resp.json()`; only connection limits are set. | P3 |
| 2.7 | `_sanitize_push_subscription` raises bare `ValueError` for non-https → 500 instead of 400. | P3 |
| 2.8 | `station_id` from the NWS response interpolated unencoded into a URL path (`weather_client.py:458`). Upstream-controlled, fixed host, low impact. | P3 |
| 2.9 | `_derive_key`'s hardcoded `"weatherapi-default-key"` fallback is currently unreachable from `main.py` but is a latent footgun for other callers. | P3 |

**Remaining to review:** the rest of `weather_client.py`, `astro.py`, input-validation coverage across the other ~40 routes.

**Effort:** L. **Risk:** partially converted from unknown to known.

---

## Phase 3 — Accessibility

Currently scored **1/4**. This is a coherent block and is best done as one pass rather than scattered.

| # | Item | Standard |
|---|---|---|
| 3.1 | Lift `--t3` from `#4a6278` to `#7c93aa` | Fixes 19 classes at once. Verified 4.55:1 / 5.11:1 / 5.51:1 across `--bg-3` / `--bg-2` / `--bg-1`. WCAG 1.4.3. |
| 3.2 | Fix accent-on-white CTAs | `#fff` on `--accent` is 2.75:1; hover is 2.13:1. Ticker `#fff` on `--sev-extreme` is 3.48:1. Use a dark foreground or darken the accent. |
| 3.3 | Alert and fire cards keyboard-operable | `<button>` or `role="button" tabindex="0"` + Enter/Space + `aria-expanded`. Today: 30 click listeners, 1 keydown. WCAG 2.1.1. |
| 3.4 | Live regions | `role="alert"` on `#alert-ticker`, `aria-live` on alerts container, status pill, error toast. A tornado warning currently announces nothing. WCAG 4.1.3. |
| 3.5 | Modal semantics | Both modals: `role="dialog"`, `aria-modal`, focus move on open, focus trap, Esc to close, restore focus. Zero `focus()` and zero Escape handlers exist today. |
| 3.6 | Restore focus indicators | Delete the three `outline: none` rules; add a global `:focus-visible` ring. |
| 3.7 | Label the 95 unlabeled inputs | Across `index.html` + `admin.html` there are 95 inputs and 4 `<label for>`. Mechanical: `<span class="setup-lbl">` → `<label for>`; the IDs already exist. |
| 3.8 | Accessible names on icon-only buttons | `▸` and `<-` are the current accessible names. |
| 3.9 | `prefers-reduced-motion` | Zero occurrences today. **Scope it** — stop the 30s marquee and wrap text statically, drop radar autoplay to manual; keep the 0.12–0.15s color transitions. A blanket `0.01ms` kill would freeze the ticker mid-scroll with text clipped. |
| 3.10 | Heading hierarchy | `index.html` jumps h1→h3; `admin.html` has no `<h1>`. |

**Effort:** L. **Risk:** low-medium — 3.3 and 3.5 touch interaction, need care.

---

## Phase 4 — Cleanup

Structural debt. Highest ratio of benefit to risk in the whole plan.

| # | Item | Payoff |
|---|---|---|
| 4.1 | **Delete `style.css:1317-1733` + the `1739-1743` patch** | Removes 20% of the stylesheet, eliminates all 20 undefined custom properties (79 declarations), and repairs `.status-pill`, `.last-updated`, `.alerts-container` — which currently render from the *dead* rules because they sit later in the cascade at equal specificity. Verified: none of those ~40 class names appear in any HTML or JS. **Do this first.** |
| 4.2 | Vendor Leaflet + Chart.js locally | `sw.js` bails on cross-origin, so offline mode cannot render the radar or the chart — the two headline features of a product that advertises offline PWA. ~200KB. Also removes a third-party dependency from a self-hosted appliance. |
| 4.3 | Split `app.js` (4417 lines, global scope, ~5 labelled regions) | ES modules by concern: radar / alerts / forecast / pws / telemetry / bootstrap. Prerequisite for testing any of it. |
| 4.4 | Split `main.py` (3478 lines, 53 routes) | FastAPI routers by domain. Same rationale. |
| 4.5 | Extract `admin.html` inline styles | 147 inline `style=` attributes; `rgba(255,255,255,0.05)` repeated 20+ times. The dashboard and admin look like two products. |
| 4.6 | Unify cache-busting | `style.css?v=5` and `app.js?v=8` are hardcoded in both `index.html` and `sw.js`; `admin.html` loads the CSS with no version at all. Three conventions, one problem. |
| 4.7 | Dead-code sweep | `--sev-unknown` unused, empty `.sidebar-top {}`, `.status-pill.loading` declared twice, the orphaned 768px breakpoint targeting only dead selectors. |

**Effort:** 4.1/4.2/4.6/4.7 are S–M. 4.3/4.4 are L and should be separate PRs.
**Risk:** 4.1 is low *and* verified. 4.3/4.4 are the riskiest items in the plan — pure refactors, no behavior change, land them alone.

---

## Phase 5 — AI-slop resolution and design specificity

The detector is the small half of this. The real finding was the **design specificity verdict: ~40% product-specific, 60% category-interchangeable boilerplate — and the specific parts are the least visually prominent.**

### 5a. Mechanical (detector)

4 genuine findings of 9 reported. The other 5 are false positives and should be left alone or suppressed via `.impeccable/critique/ignore.md`:

| Item | Action |
|---|---|
| `.app-shell { transition: margin-top }` | Layout-property animation on the 100dvh root grid, firing exactly when a severe alert arrives and the map must stay responsive. Use `transform` or drop it. |
| `<img id="current-icon" src="">` | Browsers resolve `src=""` to the document URL, fetching `index.html` as an image before `onerror` binds. |
| `admin.js:598` raw `#ffc864` side-tab | Folds into 4.5. |
| `.alert-banner` side-tab on undefined `--alert-unknown` | Disappears with 4.1. |
| *False positives — do not "fix"* | The `border-left` on `.alert-card`/`.timeline-item` is a **functional NWS severity encoding**, not decoration. Both `flat-type-hierarchy` hits came from sampling only inline `style=` attributes and missing the stylesheet; the real scale runs 8→52px. |

### 5b. Structural (the actual slop)

| # | Item | Rationale |
|---|---|---|
| 5.1 | **Move System Status + Ops Timeline to admin** *(decided)* | Retry pressure, cache pressure, flap counts and upstream call totals are operator telemetry in a viewer whose user wants to know if it will rain. Reclaims the right rail. |
| 5.2 | **Persist all viewer preferences** *(decided — treated as a bug)* | Units, radar provider, overlay, opacity, speed, alert/forecast filters, refresh interval. Panel collapse already persists; inconsistent persistence is worse than none. |
| 5.3 | **Render METAR and tides as an optional user-selectable layer** *(decided)* | Both are configurable providers in first-run *and* admin with **zero rendering surface in the viewer** — while Retry Pressure gets a dedicated tile. The clearest symptom of "composition follows what the backend emits". Decision #2: build them as an opt-in layer/choice rather than always-on, so they earn space only when wanted. |
| 5.4 | Explain or remove "Storm: Elevated" | A locally-invented weighted index displayed as a peer to the NWS/OWM/PWS provenance dots, explained in no tooltip, no help page, nowhere. Either document it in-UI or stop giving it NWS-level authority. |
| 5.5 | Document Auto Blend | It is the *default* source, and its precedence rules appear nowhere in the UI. |
| 5.6 | Remove hardcoded `PWS_NAMES` | `{KOKPRAGU20:'ZNewHouse', KOKPRAGU2:'ZOldHouse'}` — the author's own station nicknames in shipped source. Every other user sees raw station IDs. Add a settings field. |
| 5.7 | Visual hierarchy pass | Every `.panel-sec-hdr h3` is 11px uppercase — "Active Alerts" and "Astronomy" carry identical weight. Alert severity is a 3px border; alert titles are 12px; the current temp is 52px. |
| 5.8 | Reduce the decision points | 11-tile stat grid, 16-control map toolbar, 10 right-rail sections, a 7-option overlay select, ~400 flat timezone options. 6 of 8 cognitive-load checks fail. |

**Effort:** 5.1/5.2/5.6 are S–M and well-specified. 5.3/5.7/5.8 are design work needing your direction first.

---

## Phase 6 — Responsive and mobile

| # | Item |
|---|---|
| 6.1 | **Stop deleting controls at ≤700px.** `.sidebar-controls` is `display:none` on mobile — taking Units, Storm mode, interval, Refresh Now, and **Enable Severe Alert Push**. The push opt-in is unreachable on the only device that can receive push. Relocate to a bottom sheet; don't hide. |
| 6.2 | Restore `feels-like` and a freshness indicator on mobile. |
| 6.3 | Invert the mobile height budget — alerts get 100px under a 240–420px map. |
| 6.4 | Touch targets. Nothing reaches 44px at any breakpoint; best case is 34px. Worse, the scale is **inverted** — `.panel-toggle` grows to 32px at ≤900px then shrinks to 28px at ≤480px. `.tab-btn` at ~22px fails even the 24px AA floor. |
| 6.5 | Toolbar clipping at 1025–1200px — `overflow: hidden` at a hard 50px while controls wrap to 2–3 rows. That is the 1280×720 / 1366×768 laptop band. |
| 6.6 | Wall-display tier. No `min-width` query and zero `clamp()` calls exist; at 4K the sidebar stays 220px and labels stay 9px. |
| 6.7 | `px`-only type on a 13px root ignores browser font-size preferences; fixed-height chrome then clips any scaling. WCAG 1.4.4. |

**Effort:** M–L.

---

## Phase 7 — Performance

| # | Item |
|---|---|
| 7.1 | Gate all four timers on `visibilitychange`. Zero guards exist in `app.js` — while `admin.js:296` already has the pattern. A phone in a pocket polls the Pi forever. |
| 7.2 | Stop rebuilding collapsed panels. `renderTimeline()` runs on the 30s loop and rebuilds the entire list, but `#timeline-section` is `data-default-collapsed` — a hidden DOM subtree rebuilt every 30 seconds, indefinitely. |
| 7.3 | `loading="lazy" decoding="async"` on forecast and hourly icons — 48 hourly icons load eagerly, ~40 off-screen. Zero `loading=`/`decoding=` attributes exist anywhere. |
| 7.4 | Diff-and-patch instead of `innerHTML = ''` + full rebuild (30 sites). |

**Already good — do not touch:** zero layout thrashing in 4417 lines (no geometry reads at all), no `will-change` overuse, debounced resize and viewport refresh, `AbortController` with timeouts and fetch dedupe.

**Effort:** 7.1–7.3 are S. 7.4 is L and depends on 4.3.

---

## Phase 8 — Guardrails

So none of the above silently regresses.

| # | Item |
|---|---|
| 8.1 | ~~MCP adapter smoke test in CI~~ | Done — PR #102. Closes the hole that let a breaking `mcp` bump pass green. |
| 8.2 | Impeccable detector in CI — `npx impeccable detect` as a PR check with the verified false positives suppressed. |
| 8.3 | Contrast/a11y check in CI (axe or pa11y) to hold Phase 3. |
| 8.4 | Frontend tests. `tests/frontend_smoke.py` exists at 154 lines; there is no JS unit testing at all. Depends on 4.3. |
| 8.5 | Anti-poisoning regression tests on the untrusted-content path (Phase 2 output). |

---

## Suggested sequence

```
Phase 0  ──► unblocks everything
   │
   ├─► Phase 2  (backend review — long pole, start early, runs independently)
   │
   └─► Phase 4.1  (delete dead CSS — do before any styling work)
          │
          ├─► Phase 3   (accessibility)
          ├─► Phase 1   (correctness)
          ├─► Phase 5b  (5.1, 5.2, 5.6 — the decided items)
          ├─► Phase 6   (mobile)
          └─► Phase 7.1-7.3
                 │
                 └─► Phase 4.3 / 4.4  (the big refactors, alone, last)
                        │
                        └─► Phase 8
```

**Two ordering rules that matter:**

1. **4.1 before any CSS work.** Three live selectors currently render from dead rules. Styling anything before that deletion means debugging a cascade you are about to remove.
2. **4.3/4.4 last and alone.** Pure refactors of a 4417-line and a 3478-line file. Landing them beside behavioral changes makes review impossible and bisection useless.

## PR batching

| PR | Contents |
|---|---|
| (open) #102 | Deps + MCP v2 + `ci` job |
| (open) #103 | Alert-safety P0s |
| A | 4.1 dead CSS + 4.7 dead-code sweep + 3.1 `--t3` contrast |
| B | Phase 3 remainder (accessibility block) |
| C | Phase 1 correctness bugs |
| D | 5.1 diagnostics → admin + 5.2 persistence + 5.6 PWS names |
| E | Phase 6 mobile |
| F | 4.2 vendored libs + 7.1–7.3 perf + 4.6 cache-busting |
| G+ | Phase 2 backend findings (scope unknown until reviewed) |
| H | 4.3 app.js modules — alone |
| I | 4.4 main.py routers — alone |
| J | Phase 8 guardrails |

## Open questions for you

1. **Phase 0.1** — drop the review requirement to 0, add a second reviewer, or treat `--admin` as routine?
2. **5.3** — render METAR and tides, or remove them from config? They are configurable today and invisible.
3. **5.7/5.8** — do you want a visual-hierarchy redesign of the viewer, or only the mechanical fixes? This is the difference between "fix the defects" and "fix the design."
4. **Phase 2 depth** — full security review, or focus on the auth/token/crypto surface only?
5. **Phase 4.3/4.4** — worth doing at all? They are the largest items here and buy maintainability, not user-visible improvement.
