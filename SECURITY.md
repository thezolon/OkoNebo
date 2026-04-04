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
- Run `bash scripts/test_harness.sh` (or at minimum `python scripts/security_check.py`) before every release to scan for leaked secrets.
