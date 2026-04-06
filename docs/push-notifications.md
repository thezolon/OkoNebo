# Browser Push Notifications

OkoNebo can send **Web Push notifications** to browsers that have subscribed, triggered automatically when the weather threat level transitions. No third-party push service is required — push is delivered directly using the Web Push protocol and VAPID keys stored on your server.

---

## Prerequisites

- The server must be reachable over **HTTPS** (or `localhost`) for the browser to allow push subscriptions. Self-signed certs work for local use; Let's Encrypt or Caddy are recommended for LAN/WAN deployments.
- Auth must be enabled to manage push subscriptions via the API — see [authentication.md](authentication.md).
- The `py_vapid` or `pywebpush` library must be available in the container (`pywebpush` is listed in `requirements.txt`).

---

## How It Works

1. The server generates a **VAPID key pair** on first use and stores it in the encrypted settings store.
2. The browser fetches the VAPID public key from `GET /api/push/config`.
3. The browser subscribes using the Web Push API and posts the subscription object to `POST /api/push/subscribe`.
4. The server stores the subscription in the encrypted settings store.
5. When a threat-level transition is detected (see [webhooks.md](webhooks.md) for threat levels), the server sends a push message to all stored subscriptions.
6. The browser's service worker receives the push and shows a notification.

---

## Enabling Push in the Browser

The **Admin → Notifications** panel handles setup:

1. Click **Enable Push Notifications**.
2. Your browser prompts for notification permission — allow it.
3. The subscription is stored server-side automatically.
4. Click **Test Push** to send a test notification immediately.

No configuration beyond the in-app panel is required.

---

## API Endpoints

### Push configuration (public)

```
GET /api/push/config
```

```json
{
  "supported": true,
  "vapid_public_key": "BNabc...",
  "subscription_count": 2,
  "configured": true
}
```

### Subscribe a browser

```
POST /api/push/subscribe
Content-Type: application/json

{
  "endpoint": "https://fcm.googleapis.com/fcm/send/...",
  "keys": {
    "p256dh": "...",
    "auth": "..."
  }
}
```

This is typically called by the in-app JavaScript, not manually. Multiple subscriptions (different browsers/devices) are stored independently by endpoint URL.

### Unsubscribe a browser

```
DELETE /api/push/subscribe
Content-Type: application/json

{ "endpoint": "https://fcm.googleapis.com/fcm/send/..." }
```

---

## Push Notification Payload

Push messages sent on threat-level transitions include:

```json
{
  "event": "threat_level_transition",
  "current_level": "active",
  "previous_level": "approaching",
  "alerts_count": 2,
  "location": "Home",
  "timestamp": 1712345678
}
```

The browser's service worker is responsible for rendering the notification. The default service worker bundled with OkoNebo shows the location name and alert count as the notification body.

---

## VAPID Keys

VAPID keys are generated automatically on first push use and stored in `secure_settings.db`. They are tied to your server — if you reset the settings store, all existing browser subscriptions become invalid and browsers must re-subscribe.

To inspect push configuration:

```bash
docker exec okonebo python3 -c "
from app.secure_settings import SecureSettingsStore
s = SecureSettingsStore('secure_settings.db')
print(s.get('push.vapid_public_key'))
"
```

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| "Push not supported" in the UI | Browser or connection does not meet HTTPS requirement |
| Test push appears but live alerts don't | Confirm threat-level transitions are actually occurring (check `/api/alerts`) |
| Notification permission was denied | Re-enable in browser site settings; the server cannot re-prompt after denial |
| "subscription_count: 0" after subscribing | Check browser console for Web Push subscription errors; ensure VAPID public key round-trips correctly |
| Old devices no longer receive pushes | Subscriptions expire; re-subscribe from the admin panel |
