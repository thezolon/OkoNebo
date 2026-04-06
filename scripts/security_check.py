#!/usr/bin/env python3
"""Check API responses for accidental secret leakage."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
ENV_PATH = ROOT / ".env"
SECURE_DB_PATH = ROOT / "secure_settings.db"
BASE = os.getenv("WEATHERAPP_BASE_URL", "http://localhost:8888")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from app.secure_settings import SecureSettingsStore
except Exception:
    SecureSettingsStore = None

ENDPOINTS = [
    "/api/config",
    "/api/current",
    "/api/forecast",
    "/api/hourly",
    "/api/alerts",
    "/api/owm",
    "/api/pws",
    "/api/pws/trend?hours=3",
    "/api/debug",
    "/api/settings",
]


def load_secrets() -> list[str]:
    secrets: list[str] = []

    if CONFIG_PATH.exists():
        cfg = yaml.safe_load(CONFIG_PATH.read_text()) or {}
        owm = str((cfg.get("openweather", {}) or {}).get("api_key") or "").strip()
        pws = str((cfg.get("pws", {}) or {}).get("api_key") or "").strip()
        if owm:
            secrets.append(owm)
        if pws:
            secrets.append(pws)

    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() in {
                "OWM_API_KEY",
                "PWS_API_KEY",
                "WEATHERAPI_API_KEY",
                "TOMORROW_API_KEY",
                "VISUALCROSSING_API_KEY",
                "METEOMATICS_API_KEY",
                "AUTH_TOKEN_SECRET",
            }:
                val = v.strip()
                if val:
                    secrets.append(val)

    if SecureSettingsStore is not None and CONFIG_PATH.exists() and SECURE_DB_PATH.exists():
        cfg = yaml.safe_load(CONFIG_PATH.read_text()) or {}
        key_seed = os.getenv("SETTINGS_ENCRYPTION_KEY") or str((cfg.get("auth", {}) or {}).get("token_secret") or cfg.get("user_agent") or "weatherapp-local")
        try:
            store = SecureSettingsStore(SECURE_DB_PATH, key_seed=key_seed)
            for pid in ["openweather", "pws", "tomorrow", "meteomatics", "weatherapi", "visualcrossing"]:
                sval = str(store.get_json(f"providers.{pid}.api_key", "") or "").strip()
                if sval:
                    secrets.append(sval)
        except Exception:
            pass

    # Avoid duplicate work.
    unique = []
    for s in secrets:
        if s not in unique:
            unique.append(s)
    return unique


def fetch_text(path: str) -> tuple[str, int]:
    url = f"{BASE}{path}"
    with httpx.Client(timeout=12, follow_redirects=True) as client:
        resp = client.get(url)
    return resp.text, int(resp.status_code)


def main() -> int:
    secrets = load_secrets()
    if not secrets:
        print("No configured secrets found in config/.env. Nothing to validate.")
        return 0

    failures: list[tuple[str, str]] = []
    warnings: list[tuple[str, str]] = []

    for endpoint in ENDPOINTS:
        try:
            body, status = fetch_text(endpoint)
        except Exception as exc:
            warnings.append((endpoint, f"request failed: {exc}"))
            continue

        for secret in secrets:
            if secret and secret in body:
                failures.append((endpoint, "secret value detected in response body"))
                break

        if status >= 400:
            warnings.append((endpoint, f"endpoint returned HTTP {status} (body still scanned)"))

    if failures:
        print("SECRET LEAK CHECK: FAILED")
        for endpoint, msg in failures:
            print(f"- {endpoint}: {msg}")
        return 1

    print("SECRET LEAK CHECK: OK")
    print(json.dumps({"checked_endpoints": len(ENDPOINTS), "secrets_checked": len(secrets)}))
    if warnings:
        print("Warnings:")
        for endpoint, msg in warnings:
            print(f"- {endpoint}: {msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
