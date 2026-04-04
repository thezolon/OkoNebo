# OkoNebo — Fresh Install Walkthrough

A step-by-step guide from zero to a working dashboard. Nothing beyond what is listed here is required.

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Docker Engine | 20.10+ | `docker --version` |
| Docker Compose | v2 (plugin) | `docker compose version` |
| Open port | 8888 | Configurable in `docker-compose.yml` |

No Python, no Node.js, no build tools required.
For a direct-Python install (Raspberry Pi, etc.) see [Direct Python / Raspberry Pi](#direct-python--raspberry-pi) at the bottom.

---

## Step 1 — Copy the config

```bash
cp config.yaml.example config.yaml
```

Open `config.yaml` and set your location (the only required fields):

```yaml
lat: 36.1539       # your latitude  (-90 to 90)
lon: -95.9928      # your longitude (-180 to 180)
timezone: America/Chicago
```

All other fields are optional; API keys can be added later through the UI.

---

## Step 2 — Start the container

```bash
docker compose up -d --build
```

Expected output (abbreviated):

```
[+] Building ...
[+] Running 1/1
 ✔ Container weather-app  Started
```

Verify it is healthy:

```bash
bash health-check.sh
```

Expected:

```
[health] container is running
[health] /api/bootstrap returned HTTP 200
[health] all checks passed
```

If health-check fails, inspect logs:

```bash
docker compose logs weather-app
```

---

## Step 3 — Open the browser

Navigate to **http://localhost:8888**.

If this is a remote machine, replace `localhost` with that machine's IP.

### What you should see

A **first-run overlay** titled "Welcome to OkoNebo" covers the page. This overlay blocks the dashboard until a valid location is entered and saved.

---

## Step 4 — Complete the first-run overlay

The overlay has two required fields and several optional ones.

### Required

| Field | What to enter |
|-------|--------------|
| Home Latitude | Decimal degrees, e.g. `36.15` |
| Home Longitude | Decimal degrees, e.g. `-95.99` |

### Optional (can be added later in Setup)

| Field | Purpose |
|-------|---------|
| Work Latitude / Longitude | Second monitoring location |
| Map Provider | Esri (default), OSM, CARTO Light, CARTO Dark |
| Provider API keys | WeatherAPI, Tomorrow.io, Visual Crossing, etc. |

Click **Save & Continue**. The overlay should disappear and the dashboard should load.

> If you see a validation error ("Latitude must be between -90 and 90"), check that you entered decimal degrees, not degrees/minutes/seconds.

---

## Step 5 — Verify data is flowing

After the overlay closes you should see:

1. **Current conditions** — temperature, feels-like, humidity, wind (may show "No data" for a few seconds while the first request completes)
2. **Active alerts** — empty if no alerts are active
3. **7-day forecast** strip
4. **Hourly trend** chart
5. **Radar** map centred on your location
6. **Diagnostics** row at the bottom (provider name, response time, cache age)

If any panel shows "No data" or an error after 10 seconds, open the browser developer console and check for errors, then check:

```bash
docker compose logs weather-app --tail=50
```

The most common cause is an unreachable upstream provider. NWS is keyless and should work immediately for US locations. For non-US locations, add a WeatherAPI or Tomorrow.io key through **Setup → Providers**.

---

## Step 6 — Explore the Setup panel

Click the **⚙ Setup** tab in the navigation. Here you can change:

- Home/work location and labels
- Timezone
- Map base layer
- Provider API keys (stored encrypted; never logged)
- Authentication settings

Changes take effect immediately — no container restart needed.

---

## Step 7 (optional) — Enable authentication

If the dashboard will be accessible from outside your local network, enable login protection.

Create a `.env` file (one-time):

```bash
cat > .env << 'EOF'
AUTH_ENABLED=true
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-me-strong-password
# Optional read-only viewer account:
# VIEWER_USERNAME=viewer
# VIEWER_PASSWORD=another-strong-password
EOF
```

Restart the container to apply:

```bash
docker compose down && docker compose up -d
```

The dashboard will now require login. Log in with the admin credentials to reach Setup.

---

## Confirming a healthy install — checklist

```
[ ] docker compose ps  shows  weather-app  State=running / healthy
[ ] bash health-check.sh  exits 0 with "all checks passed"
[ ] http://localhost:8888  loads without errors in browser console
[ ] First-run overlay appeared and was dismissed after saving valid lat/lon
[ ] Current conditions panel shows data (or loading spinner, then data)
[ ] Diagnostics row shows a provider name and response time
[ ] Setup panel opens, shows saved lat/lon values
```

All boxes checked → install is complete.

---

## Direct Python / Raspberry Pi

If Docker is not available:

```bash
# Requires Python 3.11+
bash start.sh
bash health-check.sh
```

`start.sh` creates a virtualenv, installs dependencies from `requirements.txt`, and launches the Uvicorn server on port 8000 (not 8888 — Docker maps 8888→8000; direct Python always uses 8000).

On a Raspberry Pi with a self-contained release tarball, the workflow is identical but a convenience wrapper is included:

```bash
cd weatherapp-release-*/
bash deploy-on-pi.sh
```

---

## Upgrading

```bash
git pull
docker compose up -d --build
```

`config.yaml` and `secure_settings.db` are not touched by upgrades.
Always read `RELEASE_NOTES_v*.md` for breaking changes before upgrading across major versions.

---

## Removing OkoNebo

```bash
docker compose down -v        # stops container, removes volumes
rm config.yaml secure_settings.db cache.db   # optional: remove runtime data
```
