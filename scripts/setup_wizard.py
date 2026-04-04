#!/usr/bin/env python3
"""Interactive setup wizard for weatherapp config.yaml and encrypted settings store."""

from __future__ import annotations

import shutil
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
SECURE_DB_PATH = ROOT / "secure_settings.db"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.secure_settings import SecureSettingsStore

PROVIDER_ORDER = [
    "nws",
    "openweather",
    "pws",
    "tomorrow",
    "meteomatics",
    "weatherapi",
    "visualcrossing",
    "aviationweather",
    "noaa_tides",
]

PROVIDER_REQUIRES_KEY = {
    "nws": False,
    "openweather": True,
    "pws": True,
    "tomorrow": True,
    "meteomatics": True,
    "weatherapi": True,
    "visualcrossing": True,
    "aviationweather": False,
    "noaa_tides": False,
}

MAP_OPTIONS = ["esri_street", "osm", "carto_light", "carto_dark"]


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    return raw if raw else default


def ask_float(prompt: str, default: float) -> float:
    while True:
        raw = ask(prompt, str(default))
        try:
            return float(raw)
        except ValueError:
            print("Please enter a valid number.")


def parse_station_ids(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


def ask_bool(prompt: str, default: bool) -> bool:
    default_txt = "y" if default else "n"
    return ask(prompt, default_txt).lower().startswith("y")


def main() -> int:
    if not CONFIG_PATH.exists():
        print(f"Missing config file: {CONFIG_PATH}")
        return 1

    with CONFIG_PATH.open() as f:
        cfg = yaml.safe_load(f) or {}

    loc = cfg.get("location", {})
    pws = cfg.get("pws", {})

    print("\n== WeatherApp Setup Wizard ==")
    print("This updates config.yaml and encrypted secure_settings.db entries.\n")

    home_label = ask("Home label", str(loc.get("label", "Home")))
    home_lat = ask_float("Home latitude", float(loc.get("lat", 0.0)))
    home_lon = ask_float("Home longitude", float(loc.get("lon", 0.0)))
    timezone = ask("Timezone", str(loc.get("timezone", "UTC")))

    add_work = ask("Add work location? (y/n)", "y").lower().startswith("y")
    work = None
    if add_work:
        work_label = ask("Work label", "Work")
        work_lat = ask_float("Work latitude", home_lat)
        work_lon = ask_float("Work longitude", home_lon)
        work = {"label": work_label, "lat": work_lat, "lon": work_lon}

    user_agent = ask("User-Agent string", str(cfg.get("user_agent", "(weatherapp, local@example.com)")))
    pws_provider = ask("PWS provider", str(pws.get("provider", "weather.com")))
    pws_stations = parse_station_ids(ask("PWS station IDs (comma-separated)", ",".join(pws.get("stations", []))))

    map_provider = ask("Map provider (esri_street/osm/carto_light/carto_dark)", str((cfg.get("map", {}) or {}).get("provider", "esri_street")))
    if map_provider not in MAP_OPTIONS:
        map_provider = "esri_street"

    providers_cfg = cfg.get("providers", {}) if isinstance(cfg.get("providers", {}), dict) else {}
    provider_enabled: dict[str, bool] = {}
    provider_keys: dict[str, str] = {}

    print("\nProvider selection:")
    for pid in PROVIDER_ORDER:
        default_enabled = bool((providers_cfg.get(pid, {}) or {}).get("enabled", not PROVIDER_REQUIRES_KEY[pid]))
        provider_enabled[pid] = ask_bool(f"Enable {pid}? (y/n)", default_enabled)
        if PROVIDER_REQUIRES_KEY[pid]:
            provider_keys[pid] = ask(f"{pid} API key (blank to keep existing)", "")

    cfg["location"] = {
        "lat": home_lat,
        "lon": home_lon,
        "label": home_label,
        "timezone": timezone,
    }
    cfg["alert_locations"] = [{"lat": home_lat, "lon": home_lon, "label": home_label}]
    if work:
        cfg["alert_locations"].append({
            "lat": work["lat"],
            "lon": work["lon"],
            "label": work["label"],
        })

    cfg["user_agent"] = user_agent
    cfg.setdefault("pws", {})
    cfg["pws"]["provider"] = pws_provider
    cfg["pws"]["stations"] = pws_stations
    cfg["map"] = {"provider": map_provider}
    cfg["providers"] = {pid: {"enabled": provider_enabled[pid]} for pid in PROVIDER_ORDER}

    backup_path = CONFIG_PATH.with_suffix(".yaml.bak")
    shutil.copy2(CONFIG_PATH, backup_path)
    with CONFIG_PATH.open("w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)

    key_seed = str(((cfg.get("auth", {}) or {}).get("token_secret") or cfg.get("user_agent") or "weatherapp-local"))
    store = SecureSettingsStore(SECURE_DB_PATH, key_seed=key_seed)

    runtime_settings = {
        "location": cfg["location"],
        "alert_locations": cfg["alert_locations"],
        "user_agent": cfg["user_agent"],
        "pws": cfg["pws"],
        "providers": cfg["providers"],
        "map": cfg["map"],
        "auth": {
            "enabled": bool((cfg.get("auth", {}) or {}).get("enabled", False)),
            "require_viewer_login": bool((cfg.get("auth", {}) or {}).get("require_viewer_login", False)),
        },
    }
    store.set_json("settings.runtime", runtime_settings)

    for pid, key_value in provider_keys.items():
        if key_value:
            store.set_json(f"providers.{pid}.api_key", key_value)

    store.set_json("bootstrap.first_run_complete", True)

    print("\nSaved:")
    print(f"- {CONFIG_PATH}")
    print(f"- {SECURE_DB_PATH}")
    print(f"- backup: {backup_path}")
    print("\nNext step: docker compose up -d --build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
