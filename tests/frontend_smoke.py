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
    admin_html = fetch_html("/admin.html")
    integrations_html = fetch_html("/agent-integrations.html")
    manual_html = fetch_html("/agent-manual.html")
    viewer_help_html = fetch_html("/viewer-help.html")
    admin_help_html = fetch_html("/admin-help.html")
    profile_json = fetch_html("/.well-known/okonebo-agent.json")
    instructions_txt = fetch_html("/.well-known/okonebo-agent-instructions.txt")

    # Dashboard should link to admin page.
    ensure(has_id(html, "admin-section"), "Missing admin section on dashboard")
    ensure(has_id(html, "viewer-help-section"), "Missing viewer help section on dashboard")
    ensure(has_id(html, "viewer-help-toolbar-btn"), "Missing toolbar help button on dashboard")

    forecast_pos = html.find('id="forecast-section"')
    compare_pos = html.find('id="multi-current-section"')
    debug_pos = html.find('id="debug-section"')
    pws_pos = html.find('id="pws-section"')
    ensure(forecast_pos != -1, "Missing 7-day forecast section")
    ensure(compare_pos != -1, "Missing location compare section")
    ensure(pws_pos != -1, "Missing PWS section")
    ensure(debug_pos != -1, "Missing system status section")
    ensure(forecast_pos < debug_pos, "7-day forecast section must appear before system status")
    ensure(forecast_pos < compare_pos < pws_pos, "Location compare section must appear between forecast and PWS")

    for required_id in [
        "push-toggle-btn",
        "push-status",
        "compact-panel-layout-btn",
        "panel-layout-status",
        "debug-observability",
        "debug-pressure",
        "debug-stability",
        "debug-trend",
        "debug-guidance",
        "reset-panel-layout-btn",
        "toggle-debug-section",
        "toggle-admin-section",
        "toggle-viewer-help-section",
        "toggle-timeline-section",
    ]:
        ensure(has_id(html, required_id), f"Missing dashboard debug field id: {required_id}")

    # Setup/admin controls now live on /admin.html.
    for required_id in [
        "setup-section",
        "setup-save-btn",
        "setup-discard-btn",
        "obs-overall",
        "obs-refresh-btn",
        "obs-retry",
        "obs-cache",
        "obs-rate",
        "obs-stale",
        "obs-actions",
        "obs-history",
        "setup-map-provider",
        "setup-home-lat",
        "setup-home-lon",
        "setup-auth-enabled",
        "setup-auth-admin-user",
        "test-all-providers",
        "agent-token-section",
        "agent-token-create-btn",
    ]:
        ensure(has_id(admin_html, required_id), f"Missing admin/setup control id: {required_id}")

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
    setup_options = map_provider_options(admin_html, "setup-map-provider")
    firstrun_options = map_provider_options(html, "fr-map-provider")

    ensure(expected_map_options.issubset(setup_options), "Setup map provider options are incomplete")
    ensure(expected_map_options.issubset(firstrun_options), "First-run map provider options are incomplete")

    ensure("MCP" in integrations_html and "ACP" in integrations_html, "Integration guide must mention MCP and ACP")
    ensure("okonebo-agent.json" in integrations_html, "Integration guide must include auto-config profile link")
    ensure("agent-manual.html" in integrations_html, "Integration guide must include manual instructions link")

    ensure("Agent Manual Instructions" in manual_html, "Manual instruction page must be available")
    ensure("Copy/Paste Prompt Template" in manual_html, "Manual page should include prompt template section")
    ensure("Viewer Help" in viewer_help_html, "Viewer help page must be available")
    ensure("Admin Help" in admin_help_html, "Admin help page must be available")

    ensure('"service":"okonebo"' in profile_json.replace(" ", ""), "Auto-config profile must identify service")
    ensure('"tools"' in profile_json, "Auto-config profile must include tool definitions")
    ensure("OkoNebo Agent Instructions" in instructions_txt, "Plain-text instructions endpoint must be available")

    print("frontend smoke: admin/setup controls OK")
    print("frontend smoke: first-run controls OK")
    print("frontend smoke: map provider options OK")
    print("frontend smoke: integration guide page OK")
    print("frontend smoke: auto/manual agent instruction pages OK")
    print("frontend smoke: viewer/admin help pages OK")
    print("frontend smoke: right-panel forecast ordering OK")
    print("frontend smoke: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
