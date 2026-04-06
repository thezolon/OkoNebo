# Multi-Location Monitoring

OkoNebo supports monitoring multiple locations simultaneously — useful if you want to track weather at home **and** at a second location (a workplace, school, vacation property, etc.). Alerts are aggregated across all monitored locations; current conditions can be fetched per-location.

---

## Configuration

Add `alert_locations` to `config.yaml`:

```yaml
lat: 36.1539          # Primary (home) location
lon: -95.9928
timezone: America/Chicago

alert_locations:
  - lat: 36.1539
    lon: -95.9928
    label: Home
  - lat: 36.1540
    lon: -95.9929
    label: Office
  - lat: 35.4676
    lon: -97.5164
    label: Oklahoma City
```

If `alert_locations` is not set, only the primary `lat`/`lon` is monitored for alerts.

Changes can also be made in the **Setup → Locations** panel without restarting the container.

---

## How It Works

### Alerts (`/api/alerts`)

NWS alerts are fetched for every location in `alert_locations` simultaneously. Duplicate alerts (the same alert affecting multiple monitored points) are de-duplicated by alert ID. Each alert is tagged with which monitored locations it affects.

### Current conditions — multi-location (`/api/current/multi`)

Returns current conditions for each monitored location fetched in parallel:

```
GET /api/current/multi
```

```json
{
  "locations": [
    {
      "label": "Home",
      "role": "primary",
      "lat": 36.1539,
      "lon": -95.9928,
      "ok": true,
      "current": { "temp_f": 72.3, "source": "nws", ... },
      "error": null
    },
    {
      "label": "Office",
      "role": "secondary",
      "lat": 36.1540,
      "lon": -95.9929,
      "ok": true,
      "current": { "temp_f": 71.8, "source": "nws", ... },
      "error": null
    }
  ],
  "requested_count": 2,
  "success_count": 2,
  "failure_count": 0,
  "updated_at": 1712345678.0
}
```

Each location entry has an `ok` flag and an `error` field — partial failures (one location down) still return all other locations successfully.

### Threat level and webhooks

The threat level shown in the dashboard and used by webhooks / push notifications is determined by the **highest severity alert across all monitored locations**. A warning in OKC elevates the threat level for the whole install.

---

## The Dashboard UI

The dashboard shows alerts from all monitored locations. Each alert is tagged with the location(s) it affects. The multi-location current conditions widget shows a row per location.

---

## Legacy `work_lat` / `work_lon` config

Older configs used top-level `work_lat`/`work_lon`/`work_label` fields. These are still supported for backward compatibility and are merged into `alert_locations` automatically on load. Migrating to the `alert_locations` list format is recommended for more than two locations.

```yaml
# Old style (still works)
work_lat: 36.1540
work_lon: -95.9929
work_label: Office

# Preferred: use alert_locations list
alert_locations:
  - lat: 36.1539
    lon: -95.9928
    label: Home
  - lat: 36.1540
    lon: -95.9929
    label: Office
```
