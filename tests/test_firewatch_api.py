import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main


class FireWatchApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def test_firewatch_success_payload(self):
        mock_payload = {
            "source": "nifc",
            "radius_miles": 250,
            "updated_at": "2026-04-07T00:00:00+00:00",
            "incidents": [
                {
                    "id": "{ABC}",
                    "name": "Sample Fire",
                    "acres": 1234.0,
                    "containment_percent": 20.0,
                    "nearest_distance_miles": 42.5,
                    "nearest_location": "Home",
                    "monitored_locations": ["Home"],
                    "location": {"lat": 35.5, "lon": -97.6},
                }
            ],
        }

        with patch("app.main.wc.get_fire_incidents_multi", return_value=mock_payload):
            response = self.client.get("/api/firewatch")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("source"), "nifc")
        self.assertEqual(data.get("radius_miles"), 250)
        self.assertEqual(len(data.get("incidents", [])), 1)
        self.assertEqual(data["incidents"][0].get("name"), "Sample Fire")

    def test_firewatch_upstream_error_returns_502(self):
        with patch("app.main.wc.get_fire_incidents_multi", side_effect=Exception("upstream failed")):
            response = self.client.get("/api/firewatch")

        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertIn("detail", payload)


if __name__ == "__main__":
    unittest.main()
