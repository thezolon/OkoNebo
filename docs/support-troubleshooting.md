# Support and Troubleshooting

Before asking for help, run a health check and collect a support bundle — it contains everything needed to diagnose most issues without sharing any secrets.

---

## Health Check

```bash
bash health-check.sh
```

Windows:
```powershell
.\health-check.ps1
```

Expected output:
```
✓ Container running
✓ /health → 200
✓ /api/current → 200 or 502
✓ ...
✓ All systems operational!
```

Weather data endpoints report `OK (502)` on a fresh install before location is configured — this is normal. Configure your location through the first-run overlay or Setup panel to get live data.

---

## Support Bundle

When asking for help (GitHub issues, community forums) always collect a support bundle instead of pasting raw logs. The bundle is **redacted** — no API keys, passwords, or coordinates are included.

**Collect from the command line:**

```bash
python3 scripts/support_bundle.py

# With auth enabled:
python3 scripts/support_bundle.py --token YOUR_AGENT_TOKEN

# Save to a custom path:
python3 scripts/support_bundle.py --output /tmp/my-bundle.json

# Point at a non-localhost host:
python3 scripts/support_bundle.py --base-url http://192.168.2.22:8888
```

The script writes a timestamped JSON file to the current directory.

**Collect from the dashboard:**

Admin → State → **Download Support Bundle**

**Collect via the API:**

```
GET /api/support-bundle
Authorization: Bearer <agent_token_with_debug.read>
```

The bundle includes:
- Server version and uptime
- Provider enabled/configured status (keys redacted)
- Recent observability events
- Redacted last client snapshot (browser metrics)
- Alert monitoring location labels (no coordinates)

---

## Debug Endpoint

For real-time server internals:

```
GET /api/debug
Authorization: Bearer <agent_token_with_debug.read>
```

Returns the full runtime snapshot: request counts, error rates, last client-side metric snapshot, and the event timeline.

---

## Common Issues

### `502 Bad Gateway` from weather endpoints

This is expected when:
- No providers are configured (first install, no keys)
- All configured providers fail simultaneously (upstream outage)

The `502` body contains a `detail` object with `attempted` (list of providers tried) and `errors` (per-provider error messages). Check these to see which provider failed and why.

### `401 Unauthorized` on a provider API call

Go to Admin → Setup and use **Test Provider** to validate a key. Common causes:
- Wrong key copied (extra space, missing character)
- The key hasn't propagated yet after sign-up (wait 5–10 minutes for some providers)
- Plan/subscription lapsed
- For OpenWeather: One Call 3.0 requires a separate subscription even with a free account

### Dashboard shows stale data

The UI stores a last-known-good state in `localStorage`. If the server is down, the old data is shown with a staleness indicator. Once the server comes back, data refreshes automatically.

To force a full reload: Shift+Refresh (clear cache) in the browser.

### Push notifications not arriving

See [push-notifications.md](push-notifications.md) — browser permission, HTTPS requirement, and VAPID key notes.

### Settings not saving

- Check `docker logs okonebo` for write errors on `secure_settings.db`.
- Ensure the `./secure_settings.db` bind mount is writable by the container user.
- If you see `SETTINGS_ENCRYPTION_KEY mismatch`, the Fernet key in `.env` has changed since the DB was created. Either restore the old key or run a reset (`bash scripts/reset.sh`).

### Container starts but UI shows blank page

```bash
docker logs okonebo --tail 50
```

Look for Python import errors or missing dependencies (`ModuleNotFoundError`). A `docker compose down && docker compose up -d --build` usually fixes it after a code update.

### Auth locked out

If the admin password is lost:

```bash
# Stop the container
docker compose stop

# Reset via environment — edit .env with new credentials
# Then restart cleanly
docker compose down && docker compose up -d
```

Or use the reset script (destroys all stored settings):

```bash
bash scripts/reset.sh
```

---

## Log Access

```bash
# Live logs
docker logs -f okonebo

# Last 100 lines
docker logs okonebo --tail 100
```

All log output is automatically redacted — API keys, bearer tokens, and passwords are replaced with `[REDACTED]` before they reach the log. Safe to share.

---

## Reporting a Bug

1. Collect the support bundle (above).
2. Include the bundle in your GitHub issue.
3. Describe steps to reproduce and the expected vs. actual behavior.

**Do not paste raw log files or `.env` contents into issues.** Use the support bundle.

For security vulnerabilities see [SECURITY.md](../SECURITY.md).
