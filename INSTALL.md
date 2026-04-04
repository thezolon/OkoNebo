# OkoNebo — Fresh Install Walkthrough

A step-by-step guide from zero to a working dashboard on any supported platform.

**Python is not required on the host. Docker handles everything.**

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Docker Desktop (Windows / macOS) or Docker Engine (Linux) | 20.10+ | [docker.com/get-started](https://www.docker.com/get-started) |
| Docker Compose plugin | v2 | bundled with Docker Desktop; on Linux: `apt install docker-compose-plugin` |
| Open port | 8888 | Configurable in `docker-compose.yml` |

No Python, no Node.js, no build tools required on the host.

---

## Step 1 — Copy the config

**Linux / macOS:**
```bash
cp config.yaml.example config.yaml
```

**Windows (PowerShell):**
```powershell
Copy-Item config.yaml.example config.yaml
```

**Windows (Command Prompt):**
```bat
copy config.yaml.example config.yaml
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

**Linux / macOS:**
```bash
bash start.sh
```

**Windows (double-click or run from Command Prompt):**
```bat
start.bat
```

Or on all platforms directly via Docker:
```
docker compose up -d --build
```

Expected output (abbreviated):
```
[+] Building ...
 ✔ Container weather-app  Started
```

---

## Step 3 — Verify it is healthy

**Linux / macOS:**
```bash
bash health-check.sh
```

**Windows (PowerShell):**
```powershell
.\health-check.ps1
```

Expected output:
```
Config endpoint:    OK (200)
Bootstrap endpoint: OK (200)
Current conditions: OK (502)   <- 502 is normal before location is configured
...
All systems operational!
```

If the check fails, inspect logs:
```
docker compose logs weather-app
```

---

## Step 4 — Open the browser

Navigate to **http://localhost:8888**.

If this is a remote machine, replace `localhost` with that machine's IP.

### What you should see

A **first-run overlay** titled "Welcome to OkoNebo" covers the page. This overlay blocks the dashboard until a valid location is entered and saved.

---

## Step 5 — Complete the first-run overlay

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

Click **Save & Continue**. The overlay disappears and the dashboard loads.

> If you see a validation error ("Latitude must be between -90 and 90"), you entered degrees/minutes/seconds instead of decimal degrees.

Your settings are stored on the server in `secure_settings.db`. They survive every `docker compose up -d --build` — you will not be asked to complete setup again unless you deliberately reset.

---

## Step 6 — Verify data is flowing

After the overlay closes you should see:

1. **Current conditions** — temperature, feels-like, humidity, wind
2. **Active alerts** — empty if none active
3. **7-day forecast** strip
4. **Hourly trend** chart
5. **Radar** map centred on your location
6. **Diagnostics** row at the bottom (provider name, response time)

If any panel shows "No data" after 10 seconds, check logs. NWS is keyless and works immediately for US locations. For non-US, add a WeatherAPI or Tomorrow.io key via **Setup → Providers**.

---

## Step 7 (optional) — Enable authentication

Create a `.env` file before starting the container:

**Linux / macOS:**
```bash
cat > .env << 'EOF'
AUTH_ENABLED=true
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-me-strong-password
EOF
```

**Windows (PowerShell):**
```powershell
@"
AUTH_ENABLED=true
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-me-strong-password
"@ | Set-Content .env
```

Restart to apply:
```
docker compose down && docker compose up -d
```

---

## Confirming a healthy install — checklist

```
[ ] docker compose ps  shows  weather-app  running/healthy
[ ] health-check script exits 0 with "All systems operational"
[ ] http://localhost:8888 loads without console errors
[ ] First-run overlay appeared and was dismissed after saving lat/lon
[ ] Current conditions panel shows data
[ ] Diagnostics row shows a provider name and response time
[ ] Setup panel opens and shows the saved lat/lon values
```

---

## Factory reset

Normal rebuilds never wipe your data. To intentionally start over:

**Linux / macOS:**
```bash
bash scripts/reset.sh              # wipe DBs only (keeps config.yaml)
bash scripts/reset.sh --config     # wipe everything
```

**Windows (PowerShell):**
```powershell
.\reset.ps1              # wipe DBs only
.\reset.ps1 -Config      # wipe everything
```

---

## Upgrading

```
git pull
docker compose up -d --build
```

`config.yaml`, `secure_settings.db`, and `cache.db` are mounted from the host and are never touched by a rebuild.

Always read `RELEASE_NOTES_v*.md` for breaking changes before upgrading across major versions.

---

## Removing OkoNebo

**Linux / macOS:**
```bash
docker compose down
rm -f config.yaml secure_settings.db cache.db
```

**Windows (PowerShell):**
```powershell
docker compose down
Remove-Item -Force config.yaml, secure_settings.db, cache.db
```
