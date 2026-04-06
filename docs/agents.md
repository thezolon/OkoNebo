# AI Agent Integration

OkoNebo is built to be consumed by AI agents — language models, MCP servers, REST clients, and home automation scripts. It provides a structured discovery layer, scoped bearer tokens, and a well-known profile endpoint for zero-config agent setup.

---

## Quick Start

1. Log in as admin and open **Admin → Agent Tokens**.
2. Create a token with the scopes you need (see table below).
3. Copy the token value — it is shown **once only**.
4. Configure your agent:

```
Base URL:  http://your-host:8888
Auth:      Authorization: Bearer <token>
Discovery: GET /.well-known/okonebo-agent.json
```

---

## Available Scopes

| Scope | What it grants access to |
|-------|--------------------------|
| `weather.read` | All weather endpoints: current, forecast, hourly, alerts, METAR, tides, PWS, history, astro, AQI |
| `config.read` | `/api/config` and `/api/bootstrap` — location info and provider state |
| `stats.read` | `/api/stats` — upstream call counts per provider |
| `debug.read` | `/api/debug` and `/api/support-bundle` — runtime diagnostics |

Tokens can have any combination of scopes. A token with no matching scope for a given endpoint receives `403 Forbidden`.

---

## Discovery

### Machine-readable profile

```
GET /.well-known/okonebo-agent.json
```

Returns a JSON profile with base URL, auth scheme, all available tools (name → endpoint → scope), and behavioral rules. Agents can load this once to self-configure.

### Human-readable instructions

```
GET /.well-known/okonebo-agent-instructions.txt
```

Plain-text instruction block suitable for pasting directly into an LLM system prompt.

### Capabilities manifest

```
GET /api/capabilities
Authorization: Bearer <token>
```

Lists all tools, their endpoints, and required scopes. Use this at agent start to validate that the token has the scopes it needs before making data calls.

---

## Tool → Endpoint Mapping

| Tool name | Endpoint | Scope |
|-----------|----------|-------|
| `get_current` | `GET /api/current` | `weather.read` |
| `get_current_multi` | `GET /api/current/multi` | `weather.read` |
| `get_history` | `GET /api/history?hours=6` | `weather.read` |
| `get_forecast` | `GET /api/forecast` | `weather.read` |
| `get_hourly` | `GET /api/hourly` | `weather.read` |
| `get_alerts` | `GET /api/alerts` | `weather.read` |
| `get_metar` | `GET /api/metar` | `weather.read` |
| `get_tides` | `GET /api/tides?days=2` | `weather.read` |
| `get_pws` | `GET /api/pws` | `weather.read` |
| `get_pws_trend` | `GET /api/pws/trend?hours=3` | `weather.read` |
| `get_config` | `GET /api/config` | `config.read` |
| `get_bootstrap` | `GET /api/bootstrap` | `config.read` |
| `get_stats` | `GET /api/stats` | `stats.read` |
| `get_debug` | `GET /api/debug` | `debug.read` |
| `get_support_bundle` | `GET /api/support-bundle` | `debug.read` |

---

## Token Management via API

Requires an admin session token (separate from agent tokens — see [authentication.md](authentication.md)).

### List tokens

```
GET /api/agent-tokens
Authorization: Bearer <admin_session_token>
```

Token values are never returned — only metadata (id, name, scopes, created/expiry, revoked status).

### Create a token

```
POST /api/agent-tokens
Authorization: Bearer <admin_session_token>
Content-Type: application/json

{
  "name": "My Home Assistant Agent",
  "scopes": ["weather.read", "config.read"],
  "ttl_hours": 720
}
```

Response includes the token value (shown **once only**):

```json
{
  "id": "abc123...",
  "token": "eyJ...",
  "name": "My Home Assistant Agent",
  "scopes": ["weather.read", "config.read"],
  "expires_at": 1234567890
}
```

`ttl_hours` range: 1 – 2160 (90 days). Default: 24.

### Revoke a token

```
DELETE /api/agent-tokens/{token_id}
Authorization: Bearer <admin_session_token>
```

The token is added to an in-memory denylist immediately. Revocations persist across restarts via the encrypted settings store.

---

## MCP Server

The repo includes `scripts/mcp_server.py`, a Model Context Protocol (MCP) server that wraps OkoNebo's weather endpoints as MCP tools. It is documented in the in-app **Agent Integrations** page at `/agent-integrations.html`.

---

## Behavioral Rules for Agents

These are also returned by the discovery profile:

- Prefer read-only endpoints unless the operator explicitly authorizes admin mutations.
- Never call token-management endpoints using an agent token.
- On `401` or `403`: report auth/scope mismatch and stop retry loops.
- On `502` from weather endpoints: report which providers were attempted and failed; do not silent-retry in a tight loop.
- Call `/api/capabilities` at session start to validate scope coverage before making data calls.
