# WeatherApp v1.0 Execution Board

## Release Objective
Ship a public, self-hostable, open-source WeatherApp `v1.0.0` with:
- first-run setup flow
- optional auth with admin/viewer roles
- encrypted runtime/provider secret storage
- global provider framework (keyless defaults + keyed opt-in)
- stable mobile/tablet UX
- hardened API usage controls and security checks

## Scope Model
- Must-Have (release blockers): required for `v1.0.0`
- Nice-to-Have (can slip to `v1.1`): valuable but not release blocking

## Milestones
- M1: Architecture + Provider Framework
- M2: First-Run + Setup + Auth UX
- M3: Provider Adapters + Data Behavior
- M4: Security + Quality + CI
- M5: OSS Packaging + Release

## Epic Board
| Epic ID | Epic | Priority | Status | Milestone |
|---|---|---|---|---|
| E1 | Core Refactor and Module Boundaries | Must-Have | Not Started | M1 |
| E2 | Provider Framework and Defaults | Must-Have | In Progress | M1 |
| E3 | First-Run Wizard + Settings Completion | Must-Have | In Progress | M2 |
| E4 | Optional Auth Roles and Access Guarding | Must-Have | In Progress | M2 |
| E5 | External Provider Adapter Implementation | Must-Have | Not Started | M3 |
| E6 | Security Hardening and Leak Prevention | Must-Have | In Progress | M4 |
| E7 | Test Strategy and CI Gates | Must-Have | Not Started | M4 |
| E8 | OSS Repo Readiness and Governance | Must-Have | Not Started | M5 |
| E9 | Release Engineering and v1.0 Cut | Must-Have | Not Started | M5 |
| E10 | Stretch UX/Operations Enhancements | Nice-to-Have | Not Started | M5+ |

## Task Backlog (Tracked)

### E1: Core Refactor and Module Boundaries
| Task ID | Task | Priority | Depends On | Acceptance Criteria |
|---|---|---|---|---|
| T1.1 | Split frontend monolith into modules (api/state/radar/setup/charts/ui) | Must-Have | - | No behavior regression; each module has focused responsibility |
| T1.2 | Split backend route concerns (weather/settings/auth/middleware) | Must-Have | - | Route files organized and imported cleanly |
| T1.3 | Extract config/runtime merge service | Must-Have | T1.2 | No route directly mutates global config state |
| T1.4 | Add typed provider capability schema | Must-Have | T1.2 | Provider metadata consumed from single source |

### E2: Provider Framework and Defaults
| Task ID | Task | Priority | Depends On | Acceptance Criteria |
|---|---|---|---|---|
| T2.1 | Finalize provider registry with keyless defaults ON | Must-Have | - | `nws/aviationweather/noaa_tides` enabled by default |
| T2.2 | Enforce provider gating in all related endpoints | Must-Have | T2.1 | Disabled provider returns graceful payloads |
| T2.3 | Implement provider key storage in encrypted SQLite | Must-Have | T2.1 | Keys no longer required in plain config |
| T2.4 | Add map provider registry and validation | Must-Have | - | Only supported map providers accepted |

### E3: First-Run Wizard + Settings Completion
| Task ID | Task | Priority | Depends On | Acceptance Criteria |
|---|---|---|---|---|
| T3.1 | Add first-run blocking setup UX flow | Must-Have | T2.3 | New install opens setup and requires save |
| T3.2 | Setup tab parity with first-run fields | Must-Have | T3.1 | Any first-run setting editable post-install |
| T3.3 | Persist first-run completion state securely | Must-Have | T3.1 | Bootstrap returns `first_run_required=false` after save |
| T3.4 | Add setup validation and user-friendly errors | Must-Have | T3.2 | Invalid fields prevented client+server side |

### E4: Optional Auth Roles and Access Guarding
| Task ID | Task | Priority | Depends On | Acceptance Criteria |
|---|---|---|---|---|
| T4.1 | Finalize auth config model (enabled/require_viewer_login) | Must-Have | - | Auth default OFF; config reflected in `/api/auth/config` |
| T4.2 | Add admin/viewer account management in setup | Must-Have | T3.2 | Admin + viewer creds can be changed safely |
| T4.3 | Protect admin-only operations (`/api/settings` POST) | Must-Have | T4.1 | Unauthenticated/unauthorized writes denied |
| T4.4 | Token lifecycle hardening (expiry, logout, invalid token handling) | Must-Have | T4.1 | Stable behavior across refresh/restart |

### E5: External Provider Adapter Implementation
| Task ID | Task | Priority | Depends On | Acceptance Criteria |
|---|---|---|---|---|
| T5.1 | Add Tomorrow.io adapter | Must-Have | T1.4 | Current/hourly (or documented subset) exposed |
| T5.2 | Add WeatherAPI adapter | Must-Have | T1.4 | Current/forecast mapping completed |
| T5.3 | Add Visual Crossing adapter | Must-Have | T1.4 | Forecast and fallback path verified |
| T5.4 | Add Meteomatics adapter | Must-Have | T1.4 | Adapter implemented with clear capability matrix |
| T5.5 | Add AviationWeather keyless adapter | Must-Have | T1.4 | Keyless data surfaced where relevant |
| T5.6 | Add NOAA Tides keyless adapter | Must-Have | T1.4 | Marine/tide fields available where configured |
| T5.7 | Implement provider precedence and fallback strategy | Must-Have | T5.1-T5.6 | Deterministic field sourcing and graceful failover |

### E6: Security Hardening and Leak Prevention
| Task ID | Task | Priority | Depends On | Acceptance Criteria |
|---|---|---|---|---|
| T6.1 | Keep secret leak scanner mandatory pre-release | Must-Have | - | Scanner passes before package/tag |
| T6.2 | Add auth endpoint rate protections | Must-Have | T4.1 | Login abuse controls in place |
| T6.3 | Ensure no key values in logs/payloads/errors | Must-Have | T2.3 | Manual + scripted verification passes |
| T6.4 | Add security policy document and disclosure process | Must-Have | - | SECURITY.md published |

### E7: Test Strategy and CI Gates
| Task ID | Task | Priority | Depends On | Acceptance Criteria |
|---|---|---|---|---|
| T7.1 | Unit tests for config/auth/provider gating | Must-Have | T1.2 | Core logic coverage present |
| T7.2 | Integration tests for setup + first-run + auth paths | Must-Have | T3.1, T4.1 | Green on CI |
| T7.3 | Frontend smoke tests for setup and map/provider selection | Must-Have | T3.2 | Tablet/mobile critical flows validated |
| T7.4 | CI workflow with lint/test/security gates | Must-Have | T7.1 | PRs blocked on failing checks |

### E8: OSS Repo Readiness and Governance
| Task ID | Task | Priority | Depends On | Acceptance Criteria |
|---|---|---|---|---|
| T8.1 | Add LICENSE and verify dependency/license compatibility | Must-Have | - | Licensing is explicit and compliant |
| T8.2 | Add CONTRIBUTING, CODE_OF_CONDUCT, issue/PR templates | Must-Have | - | Community workflow ready |
| T8.3 | Add architecture + provider matrix docs | Must-Have | T1.4, T5.x | New contributors can navigate quickly |
| T8.4 | Final docs pass for setup/auth/providers/security | Must-Have | T3.x, T4.x, T6.x | Fresh install succeeds via docs only |

### E9: Release Engineering and v1.0 Cut
| Task ID | Task | Priority | Depends On | Acceptance Criteria |
|---|---|---|---|---|
| T9.1 | Release candidate branch + freeze policy | Must-Have | E1-E8 mostly complete | Scope frozen except fixes |
| T9.2 | Final package checks (health + leak + CI green) | Must-Have | T7.4, T6.1 | All release gates pass |
| T9.3 | Tag `v1.0.0`, publish notes + checksums | Must-Have | T9.2 | Reproducible release published |
| T9.4 | 72-hour post-release triage and hotfix policy | Must-Have | T9.3 | Early adopter support plan active |

### E10: Stretch UX/Operations Enhancements
| Task ID | Task | Priority | Depends On | Acceptance Criteria |
|---|---|---|---|---|
| T10.1 | In-dashboard upstream counters/history charts | Nice-to-Have | T6.1 | Operator visibility improved |
| T10.2 | Role-based UI visibility (hide admin controls for viewers) | Nice-to-Have | T4.x | Cleaner viewer experience |
| T10.3 | Optional import/export of settings bundle | Nice-to-Have | T3.x | Easier migration between hosts |

## Must-Have Release Cut Line (`v1.0.0`)
All of the following must be complete:
- E1, E2, E3, E4, E5, E6, E7, E8, E9
- No open P0/P1 defects
- CI fully green on release branch
- Security leak scan passes
- Fresh-install first-run setup verified manually

## Nice-to-Have Cut Line (`v1.1` candidate)
- E10 tasks can slip without blocking `v1.0.0`

## Quality Gates (Hard)
- `python -m py_compile` for backend/scripts
- frontend syntax checks pass
- health check passes
- security leak check passes
- auth guard tests pass
- provider enable/disable tests pass

## Work Sequence (Recommended)
1. Complete E1 + E2 first (stabilize architecture and provider framework)
2. Complete E3 + E4 (first-run and auth UX)
3. Complete E5 (provider adapters)
4. Complete E6 + E7 in parallel
5. Complete E8 + E9 for release cut

## Risk Register
| Risk | Impact | Mitigation |
|---|---|---|
| Provider API contract drift | Medium/High | Adapter isolation + integration tests |
| Security regression in settings/auth | High | Scanner + auth tests + review checklist |
| Setup UX complexity | Medium | Step-based wizard + strict validation |
| Scope creep before v1.0 | High | Enforce must-have cut line |

## Owner Workflow (Execution)
- Weekly planning: prioritize next must-have tasks
- Daily: update task status + blockers
- PR policy: each PR references task IDs
- Definition of done per task: code + tests + docs updated

## Immediate Next 5 Tasks
1. T1.1 frontend module split
2. T1.2 backend route split
3. T3.1 first-run blocking setup UX completion
4. T4.3 strict admin-only settings write enforcement tests
5. T5.1 Tomorrow.io adapter implementation
