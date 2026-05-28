# OkoNebo v1.5.0 — Security Release (2026-05-28)

## Critical Security Fix — CVE-2026-48710 (BadHost)

This release patches a **critical authentication bypass vulnerability** (CVE-2026-48710, "BadHost") in the Starlette framework that underlies FastAPI.

### What was the vulnerability?

Starlette versions before 1.0.1 construct `request.url` from the HTTP `Host` header. An attacker can craft a `Host` header such as:

```
Host: example.com/api/auth/?x=
```

This causes `request.url.path` to resolve to `/api/auth/` rather than the actual request path, silently bypassing any middleware that uses `request.url.path` to make authentication decisions.

OkoNebo's `api_auth_guard` and `api_rate_limiter` middleware both used `request.url.path`, making it possible for an unauthenticated attacker to access protected API endpoints by sending a single crafted request — **no credentials required**.

### What was fixed?

1. **Code fix** — Both middleware functions now use `request.scope["path"]` instead of `request.url.path`. The ASGI scope path is set by the server before request processing and cannot be poisoned by HTTP headers.

2. **Dependency upgrade** — Starlette upgraded from 0.46.2 → **1.2.0**, which also rejects malformed Host headers at the framework level (defense in depth). FastAPI upgraded from 0.115.12 → **0.136.3** to support the new Starlette.

3. **Regression tests** — Six new tests added in `tests/test_badhost_cve_2026_48710.py` verify:
   - Protected endpoints remain blocked without auth
   - Crafted `Host: .../api/auth/...` headers do not bypass the auth guard
   - Crafted `Host` headers targeting the `/api/capabilities` whitelist do not bypass auth
   - Rate limiter path is not injectable via the Host header
   - Valid authenticated requests continue to work normally

### Affected versions

All OkoNebo versions prior to v1.5.0 are affected if:
- Auth is enabled (`AUTH_ENABLED=true`), **and**
- The instance is directly exposed (no reverse proxy such as nginx or Caddy normalising the Host header before requests reach the app)

Self-hosted instances behind a properly configured reverse proxy (e.g. the Caddy/nginx configuration described in `INSTALL.md`) may have had the Host header normalised before it reached the app, reducing exposure.

### Recommended action

**Update immediately.** Pull this release and restart your container:

```bash
git pull
docker compose up -d --build
```

If you cannot update right now, configure your reverse proxy to reject or strip Host headers containing `/` or `?` characters.

## Other changes in this release

- `requirements.txt` now explicitly pins `starlette>=1.0.1` to prevent accidental downgrades.
- No changes to UI, weather providers, or configuration format.

## Acknowledgement

Vulnerability publicly disclosed as CVE-2026-48710 ("BadHost"). Fixed in Starlette 1.0.1.
