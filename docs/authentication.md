# Authentication

OkoNebo ships with authentication **disabled** by default. Enabling it adds a login screen, role-based access control, and JWT session tokens.

---

## Enabling authentication

Set the following in your `.env` file (copy `.env.example` if you haven't):

```env
AUTH_ENABLED=true

ADMIN_USERNAME=admin
ADMIN_PASSWORD=changeme

# Optional read-only viewer account
VIEWER_USERNAME=viewer
VIEWER_PASSWORD=viewerpass
```

Restart the container after changing `.env`:

```bash
docker compose down && docker compose up -d
```

You can also toggle auth in the in-app **Setup → Auth** panel — changes take effect immediately without a restart, except the initial `AUTH_ENABLED` flag which requires a container restart.

---

## Roles

| Role | Access |
|------|--------|
| `admin` | Read all data + write settings, manage agent tokens, manage webhooks and push |
| `viewer` | Read all weather data; cannot write settings or manage tokens |

When `AUTH_ENABLED=true` and `VIEWER_USERNAME` is not set, anonymous read access is still allowed. Set `AUTH_REQUIRE_VIEWER_LOGIN=true` in `.env` to require login even for weather reads.

---

## Login

```
POST /api/auth/login
Content-Type: application/json

{ "username": "admin", "password": "changeme" }
```

Response:

```json
{
  "token": "eyJ...",
  "user": { "username": "admin", "role": "admin" }
}
```

Include the token as a bearer header on all subsequent requests:

```
Authorization: Bearer eyJ...
```

---

## Logout / token revocation

```
POST /api/auth/logout
Authorization: Bearer eyJ...
```

The token is added to an in-memory denylist and rejected immediately. The denylist is cleared on container restart; tokens also expire naturally after their TTL (configurable via `AUTH_TOKEN_EXPIRY_HOURS`, default 24 h).

---

## Current identity

```
GET /api/auth/me
Authorization: Bearer eyJ...
```

Returns the authenticated username, role, and token expiry timestamp.

---

## Login rate limiting

Failed login attempts are tracked per source IP. After **10 failures within a 5-minute window** the endpoint returns `429 Too Many Requests` with `Retry-After: 300`. The window resets automatically; there is no manual unlock.

---

## Password hashing

Passwords are hashed with **bcrypt** (cost factor 12) the first time a plain-text password is used to authenticate. Subsequent logins use the stored hash. Passwords are never stored or returned in plain text.

---

## Agent tokens

Agent tokens are separate long-lived bearer tokens used by automated clients (AI agents, MCP servers, REST integrations). They are created in the **Admin → Agent Tokens** panel or via the API.

See [agents.md](agents.md) for the full agent token reference.

---

## Environment variable reference

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH_ENABLED` | `false` | Require login for admin operations when `true` |
| `AUTH_REQUIRE_VIEWER_LOGIN` | `false` | Require login even for read-only weather endpoints |
| `ADMIN_USERNAME` | `admin` | Admin account username |
| `ADMIN_PASSWORD` | *(none)* | Admin account password |
| `VIEWER_USERNAME` | *(none)* | Viewer account username (optional) |
| `VIEWER_PASSWORD` | *(none)* | Viewer account password |
| `AUTH_TOKEN_SECRET` | auto-generated | HMAC secret for signing JWTs — set a strong random value in production |
| `AUTH_TOKEN_EXPIRY_HOURS` | `24` | Token lifetime in hours |

> **Security note:** Use a long random value for `AUTH_TOKEN_SECRET` in production. Changing it
> invalidates all current sessions.
