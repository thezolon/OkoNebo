#!/usr/bin/env python3
"""UI behavior tests for collapsible panel layout controls (Compact/Expand/Reset)."""

from __future__ import annotations

import re
import unittest

from fastapi.testclient import TestClient

from app.main import app


class PanelLayoutUITests(unittest.TestCase):
    """Test panel layout controls in dashboard UI."""

    @classmethod
    def setUpClass(cls):
        """Create test client."""
        cls.client = TestClient(app)

    def test_dashboard_loads_with_panel_state(self):
        """Verify dashboard loads with collapsible panels initialized."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.text

        self.assertIn('id="compact-panel-layout-btn"', html)
        self.assertIn('id="reset-panel-layout-btn"', html)
        self.assertIn('id="panel-layout-status"', html)
        self.assertIn('id="debug-section"', html)
        self.assertIn('id="admin-section"', html)

    def test_compact_button_present(self):
        """Verify Compact button is accessible."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.text
        match = re.search(r'<button[^>]*id="compact-panel-layout-btn"', html, re.IGNORECASE)
        self.assertIsNotNone(match, "Compact button must exist")

    def test_layout_status_hint_present(self):
        """Verify layout status hint renders."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.text
        self.assertIn('id="panel-layout-status"', html)
        self.assertIn('Compact', html)

    def test_reset_button_present(self):
        """Verify Reset Layout button is present."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.text
        match = re.search(r'<button[^>]*id="reset-panel-layout-btn"', html, re.IGNORECASE)
        self.assertIsNotNone(match, "Reset Layout button must exist")

    def test_keyboard_shortcut_documented(self):
        """Verify Shift+C shortcut is documented in help."""
        resp = self.client.get("/viewer-help.html")
        self.assertEqual(resp.status_code, 200)
        html = resp.text
        self.assertIn('Shift', html)
        self.assertIn('+C', html)

    def test_toggle_buttons_have_aria(self):
        """Verify toggle buttons have aria-expanded attribute."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.text

        patterns = [
            r'id="toggle-debug-section"[^>]*aria-expanded="[^"]*"',
            r'id="toggle-admin-section"[^>]*aria-expanded="[^"]*"',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            self.assertIsNotNone(match, f"Button missing aria-expanded: {pattern}")

    def test_forecast_section_visible(self):
        """Verify 7-Day Forecast section exists."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.text
        self.assertIn('id="forecast-section"', html)
        self.assertNotIn('id="toggle-forecast-section"', html)

    def test_first_run_overlay_includes_pws_fields(self):
        """Verify first-run setup exposes PWS configuration inputs."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.text
        self.assertIn('id="fr-pws-enabled"', html)
        self.assertIn('id="fr-pws-key"', html)
        self.assertIn('id="fr-pws-provider"', html)
        self.assertIn('id="fr-pws-stations"', html)


if __name__ == '__main__':
    unittest.main()
