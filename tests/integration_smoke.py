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

    checks.extend([
        ("/api/config", check_config),
        ("/api/current", check_current),
        ("/api/forecast", check_forecast),
        ("/api/hourly", check_hourly),
        ("/api/bootstrap", check_bootstrap),
    ])

    for name, fn in checks:
        fn()
        print(f"smoke: {name} OK")

    print("integration smoke: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
