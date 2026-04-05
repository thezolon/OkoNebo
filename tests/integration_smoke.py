#!/usr/bin/env python3
"""Lightweight API smoke checks for local/docker runtime."""

from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

BASE = os.getenv("WEATHERAPP_BASE_URL", "http://localhost:8888")


def fetch_json(path: str) -> tuple[int, object]:
    url = f"{BASE}{path}"
    try:
        with urlopen(url, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return int(resp.status), json.loads(body)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"raw": body}
        return int(exc.code), parsed
    except URLError as exc:
        raise RuntimeError(f"Request failed for {url}: {exc}") from exc


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    checks: list[tuple[str, callable]] = []

    def check_config() -> None:
        status, payload = fetch_json("/api/config")
        ensure(status == 200, "config status must be 200")
        ensure(isinstance(payload, dict), "config payload must be object")
        ensure("lat" in payload and "lon" in payload, "config must include lat/lon")

    def check_current() -> None:
        status, payload = fetch_json("/api/current")
        # 502 is accepted when no providers are configured (e.g. fresh install with lat=0,lon=0).
        ensure(status in (200, 502), f"current status must be 200 or 502, got {status}")
        ensure(isinstance(payload, dict), "current payload must be object")
        if status == 200:
            ensure("source" in payload, "current payload must include source")
            ensure("temp_f" in payload, "current payload must include temp_f")

    def check_current_multi() -> None:
        status, payload = fetch_json("/api/current/multi")
        ensure(status == 200, f"current/multi status must be 200, got {status}")
        ensure(isinstance(payload, dict), "current/multi payload must be object")
        ensure(isinstance(payload.get("locations"), list), "current/multi must include locations array")
        ensure("success_count" in payload and "failure_count" in payload, "current/multi must include summary counts")
        if payload["locations"]:
            first = payload["locations"][0]
            ensure(isinstance(first, dict), "current/multi location must be object")
            ensure("label" in first and "ok" in first, "current/multi location must include label and ok")

    def check_history() -> None:
        status, payload = fetch_json("/api/history?hours=6")
        ensure(status == 200, f"history status must be 200, got {status}")
        ensure(isinstance(payload, dict), "history payload must be object")
        ensure(isinstance(payload.get("points"), list), "history must include points array")
        ensure(int(payload.get("hours") or 0) == 6, "history must echo bounded hours")

    def check_forecast() -> None:
        status, payload = fetch_json("/api/forecast")
        ensure(status in (200, 502), f"forecast status must be 200 or 502, got {status}")
        if status == 200:
            ensure(isinstance(payload, list), "forecast payload must be array")
            if payload:
                first = payload[0]
                ensure(isinstance(first, dict), "forecast item must be object")
                ensure("source" in first, "forecast items must include source")

    def check_hourly() -> None:
        status, payload = fetch_json("/api/hourly")
        ensure(status in (200, 502), f"hourly status must be 200 or 502, got {status}")
        if status == 200:
            ensure(isinstance(payload, list), "hourly payload must be array")
            if payload:
                first = payload[0]
                ensure(isinstance(first, dict), "hourly item must be object")
                ensure("source" in first, "hourly items must include source")

    def check_bootstrap() -> None:
        status, payload = fetch_json("/api/bootstrap")
        ensure(status == 200, "bootstrap status must be 200")
        ensure(isinstance(payload, dict), "bootstrap payload must be object")
        providers = payload.get("providers")
        ensure(isinstance(providers, dict), "bootstrap providers must be object")
        nws = providers.get("nws", {}) if isinstance(providers.get("nws", {}), dict) else {}
        ensure("capabilities" in nws, "provider metadata must include capabilities")

    def check_astro() -> None:
        status, payload = fetch_json("/api/astro")
        ensure(status == 200, "astro status must be 200")
        ensure(isinstance(payload, dict), "astro payload must be object")
        ensure("sunrise" in payload and "sunset" in payload, "astro must include sunrise/sunset")
        ensure("moon_phase" in payload and "moon_illumination" in payload, "astro must include moon fields")

    def check_aqi() -> None:
        status, payload = fetch_json("/api/aqi")
        ensure(status == 200, "aqi status must be 200")
        ensure(isinstance(payload, dict), "aqi payload must be object")
        # AQI may not be available if OWM is not configured, but endpoint should still return 200
        if payload.get("available"):
            ensure("aqi" in payload, "aqi payload must include aqi field")
            ensure("components" in payload, "aqi payload must include components")

    def check_ha_sensor() -> None:
        status, payload = fetch_json("/api/ha/sensor")
        ensure(status == 200, "ha sensor status must be 200")
        ensure(isinstance(payload, dict), "ha sensor payload must be object")
        ensure("state" in payload, "ha sensor must include state")
        ensure("threat_level" in payload, "ha sensor must include threat_level")
        ensure("alerts_count" in payload, "ha sensor must include alerts_count")

    def check_ha_weather() -> None:
        status, payload = fetch_json("/api/ha/weather")
        ensure(status == 200, "ha weather status must be 200")
        ensure(isinstance(payload, dict), "ha weather payload must be object")
        ensure("condition" in payload, "ha weather must include condition")
        ensure("forecast" in payload, "ha weather must include forecast")

    checks.extend([
        ("/api/config", check_config),
        ("/api/current", check_current),
        ("/api/current/multi", check_current_multi),
        ("/api/history", check_history),
        ("/api/forecast", check_forecast),
        ("/api/hourly", check_hourly),
        ("/api/bootstrap", check_bootstrap),
        ("/api/astro", check_astro),
        ("/api/aqi", check_aqi),
        ("/api/ha/sensor", check_ha_sensor),
        ("/api/ha/weather", check_ha_weather),
    ])

    for name, fn in checks:
        fn()
        print(f"smoke: {name} OK")

    print("integration smoke: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
