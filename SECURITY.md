# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| v1.0.x  | Yes       |
| < v1.0  | No        |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report security issues privately by emailing **zolon@hackthemind.org** with:

- A clear subject line: `[SECURITY] OkoNebo — <short description>`
- A description of the vulnerability and its potential impact.
- Steps to reproduce or a proof-of-concept (if available).
- Your preferred disclosure timeline.

You will receive an acknowledgement within **48 hours**.  We aim to release a fix within **14 days** for critical issues and **30 days** for moderate issues.  We will credit you in the release notes unless you prefer anonymity.

## Scope

Items in scope:
- Authentication bypass or privilege escalation in the auth system
- API key / secret leakage in responses, logs, or error messages
- Server-Side Request Forgery (SSRF) via provider proxies
- Injection vulnerabilities (SQLi in settings/cache, XSS in rendered weather data)
- Insecure default configurations that expose secrets on a fresh install

Items out of scope:
- Denial-of-service via rate-limit exhaustion (documented behavior; configure limits)
- Theoretical vulnerabilities with no practical exploit path
- Issues in third-party weather provider APIs themselves

## Design Notes for Self-Hosters

- **API keys** are stored encrypted using Fernet symmetric encryption in `secure_settings.db`.  The encryption key is derived from the `SETTINGS_ENCRYPTION_KEY` env var (or `auth.token_secret` as fallback).  Keep this value secret.
- **Auth tokens** are HMAC-SHA256 signed with `AUTH_TOKEN_SECRET`.  Use a long random value in production.  Tokens are revocable via `POST /api/auth/logout`.
- **CORS** is currently set to `allow_origins=["*"]`.  Tighten this in production if the app is exposed on the public internet.
- **Support diagnostics** should be collected with `python scripts/support_bundle.py` or `GET /api/support-bundle` rather than raw logs when asking for help.
- Run `bash scripts/test_harness.sh` (or at minimum `python scripts/security_check.py`) before every release to scan for leaked secrets.

## Security Checks

### Automated (CI — every push and pull request)

| Check | Tool | Gate |
|-------|------|------|
| Secret leak scan | `scripts/security_check.py` | Fails CI if any configured key value appears in source or config files |
| Python syntax / compile check | `py_compile` | Catches import-time errors before deployment |
| Unit tests including auth guard and write-protection behaviour | `unittest` | 35 tests covering provider fallback, auth middleware, settings validation, and token lifecycle |
| Docker build | `docker build` | Ensures the image builds cleanly from a cold checkout |
| Container health + integration smoke | `curl` + `tests/integration_smoke.py` | Verifies all API endpoints respond correctly after a real container start |

### Local (full harness — run before every release)

```bash
bash scripts/test_harness.sh
```

Stages: compile → unit tests → Docker build/start → health check → integration smoke → frontend smoke → secret leak check.
All stages must report `OK` before tagging a release.

### Static analysis

[Bandit](https://bandit.readthedocs.io/) is used for Python static security analysis:

```bash
pip install bandit
bandit -r app/ scripts/ -ll
```

**v1.0.0 audit result:** 0 High, 0 Medium findings in `app/`.  
Remaining Low-severity findings are confirmed false positives (Bandit misidentifying token-type strings `"agent"` / `"user"` as passwords, and intentional `try/except pass` guards in cache and date-parsing code).

### Pre-release manual audit (v1.0.0)

The following was verified manually before the v1.0.0 tag:

- No API keys, credentials, or secrets present in any tracked file or git history.
- CORS `allow_credentials` not set (wildcard `allow_origins=["*"]` is safe without credentials).
- No debug mode or `reload=True` in production startup path.
- `/api/debug/client` payload size capped at 64 KB to prevent memory exhaustion.
- Agent profile endpoint updated to derive `base_url` from the live request host rather than a hardcoded `localhost` value.
