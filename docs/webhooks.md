# Webhooks

OkoNebo can fire outgoing HTTP POST webhooks when the **weather threat level changes**. This is useful for integrating with home automation, alerting systems, Slack/Discord, or any HTTP endpoint.

Webhooks are managed in the **Admin → Integrations** panel or via the API. Authentication must be enabled to manage webhooks — see [authentication.md](authentication.md).

---

## Threat Levels

Threat level is computed from active NWS weather alerts:

| Level | Meaning |
|-------|---------|
| `default` | No active alerts |
| `approaching` | Advisory or watch-level alert active |
| `active` | Warning-level or higher alert active |

A webhook fires whenever the level **transitions** — `default → approaching`, `approaching → active`, `active → approaching`, etc. Repeated fetches with the same level do not re-fire.

---

## Setting Up a Webhook

### Via the Admin panel

1. Go to **Admin → Integrations → Webhooks**.
2. Enter an HTTPS (or HTTP for local targets) URL.
3. Click **Add Webhook**.
4. Use **Test** to send a `webhook_test` payload and verify delivery.

### Via the API

```
POST /api/webhooks
Authorization: Bearer <admin_session_token>
Content-Type: application/json

{ "url": "https://your-endpoint.example.com/weather-hook" }
```

Response:

```json
{
  "id": "a1b2c3d4",
  "url": "https://your-endpoint.example.com/weather-hook",
  "enabled": true,
  "created_at": 1234567890
}
```

---

## Event Payload Format

All webhook deliveries use `POST` with `Content-Type: application/json`.

### Threat-level transition

```json
{
  "event": "threat_level_transition",
  "timestamp": 1712345678,
  "previous_level": "default",
  "current_level": "active",
  "alerts_count": 2,
  "location": {
    "lat": 36.1539,
    "lon": -95.9928,
    "label": "Home"
  }
}
```

### Webhook test delivery

```json
{
  "event": "webhook_test",
  "timestamp": 1712345678,
  "location": {
    "lat": 36.1539,
    "lon": -95.9928,
    "label": "Home"
  },
  "message": "This is a webhook test payload"
}
```

---

## Viewing Delivery Statistics

```
GET /api/webhooks
Authorization: Bearer <admin_session_token>
```

Returns all configured webhooks (URLs truncated to 50 chars) plus a `stats` map with delivery counts per webhook ID.

---

## Testing a Webhook

```
POST /api/webhooks/{webhook_id}/test
Authorization: Bearer <admin_session_token>
```

Sends a `webhook_test` event payload to the target URL. Returns `502` if delivery fails.

---

## Deleting a Webhook

```
DELETE /api/webhooks/{webhook_id}
Authorization: Bearer <admin_session_token>
```

---

## URL Constraints

- Must be a valid `http://` or `https://` URL.
- Maximum URL length: 512 characters.
- Deliveries time out if the target doesn't respond promptly. Failed deliveries are logged but do not block alert processing.

---

## Example: Receiving webhooks in Node.js

```js
const express = require('express');
const app = express();
app.use(express.json());

app.post('/weather-hook', (req, res) => {
  const { event, current_level, alerts_count } = req.body;
  if (event === 'threat_level_transition') {
    console.log(`Threat level → ${current_level} (${alerts_count} alerts)`);
  }
  res.sendStatus(200);
});

app.listen(3000);
```

## Example: Home Assistant automation trigger

Point the webhook URL at a Home Assistant [webhook automation trigger](https://www.home-assistant.io/docs/automation/trigger/#webhook-trigger). The `event` and `current_level` fields are available as template variables.
