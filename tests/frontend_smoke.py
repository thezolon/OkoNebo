#!/usr/bin/env python3
"""Frontend smoke checks for critical setup and map-provider UI flows."""

from __future__ import annotations

import os
import re
import sys
from urllib.error import URLError
from urllib.request import urlopen

BASE = os.getenv("WEATHERAPP_BASE_URL", "http://localhost:8888")


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def fetch_html(path: str = "/") -> str:
    url = f"{BASE}{path}"
    try:
        with urlopen(url, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            ensure(resp.status == 200, f"{path} must return 200")
            return body
    except URLError as exc:
        raise RuntimeError(f"Request failed for {url}: {exc}") from exc


def has_id(html: str, element_id: str) -> bool:
    return re.search(rf'id\s*=\s*"{re.escape(element_id)}"', html) is not None


def map_provider_options(html: str, select_id: str) -> set[str]:
    select_pattern = rf'<select[^>]*id\s*=\s*"{re.escape(select_id)}"[^>]*>(.*?)</select>'
    match = re.search(select_pattern, html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return set()
    block = match.group(1)
    return set(re.findall(r'value\s*=\s*"([^"]+)"', block, flags=re.IGNORECASE))


def main() -> int:
    html = fetch_html("/")

    # Setup panel critical controls.
    for required_id in [
        "setup-section",
        "setup-save-btn",
        "setup-map-provider",
        "setup-home-lat",
        "setup-home-lon",
        "setup-auth-enabled",
        "setup-auth-admin-user",
    ]:
        ensure(has_id(html, required_id), f"Missing setup control id: {required_id}")

    # First-run overlay critical controls.
    for required_id in [
        "firstrun-overlay",
        "firstrun-save-btn",
        "fr-home-lat",
        "fr-home-lon",
        "fr-map-provider",
    ]:
        ensure(has_id(html, required_id), f"Missing first-run control id: {required_id}")

    expected_map_options = {"esri_street", "osm", "carto_light", "carto_dark"}
    setup_options = map_provider_options(html, "setup-map-provider")
    firstrun_options = map_provider_options(html, "fr-map-provider")

    ensure(expected_map_options.issubset(setup_options), "Setup map provider options are incomplete")
    ensure(expected_map_options.issubset(firstrun_options), "First-run map provider options are incomplete")

    print("frontend smoke: setup controls OK")
    print("frontend smoke: first-run controls OK")
    print("frontend smoke: map provider options OK")
    print("frontend smoke: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
