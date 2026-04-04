import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main


class DebugObservabilityTests(unittest.TestCase):
    def setUp(self):
        self._auth_enabled = main.AUTH_ENABLED
        self._auth_require_viewer_login = main.AUTH_REQUIRE_VIEWER_LOGIN
        main.AUTH_ENABLED = False
        main.AUTH_REQUIRE_VIEWER_LOGIN = False
        main._reset_observability_runtime()
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def tearDown(self):
        main.AUTH_ENABLED = self._auth_enabled
        main.AUTH_REQUIRE_VIEWER_LOGIN = self._auth_require_viewer_login

    def test_debug_observability_healthy_when_no_pressure(self):
        with patch(
            "app.main.wc.get_upstream_call_stats",
            return_value={
                "counts": {},
                "retries": {"nws": {"attempted": 0, "exhausted": 0}},
                "cache_runtime": {"memory_hit": 8, "sqlite_hit": 2, "miss": 1},
            },
        ):
            resp = self.client.get("/api/debug")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("observability", body)
        self.assertEqual(body["observability"]["overall"], "healthy")
        self.assertEqual(body["observability"]["retry_pressure"], "normal")
        self.assertEqual(body["observability"]["cache_pressure"], "normal")
        self.assertEqual(body["observability"].get("stability"), "stable")
        self.assertTrue(body["observability"].get("recommendations"))

    def test_debug_observability_degraded_on_high_retry_exhaustion(self):
        with patch(
            "app.main.wc.get_upstream_call_stats",
            return_value={
                "counts": {},
                "retries": {
                    "nws": {"attempted": 6, "exhausted": 2},
                    "weatherapi": {"attempted": 9, "exhausted": 3},
                },
                "cache_runtime": {"memory_hit": 2, "sqlite_hit": 1, "miss": 12},
            },
        ):
            resp = self.client.get("/api/debug")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        obs = body.get("observability", {})
        self.assertEqual(obs.get("overall"), "degraded")
        self.assertEqual(obs.get("retry_pressure"), "high")
        self.assertEqual(obs.get("cache_pressure"), "high")
        self.assertGreaterEqual(obs.get("retry_exhausted_total", 0), 5)
        self.assertTrue(any("High retry pressure" in line for line in obs.get("recommendations", [])))

    def test_observability_runtime_tracks_transitions(self):
        main._reset_observability_runtime()
        obs_1 = {"overall": "healthy", "retry_pressure": "normal", "cache_pressure": "normal", "rate_limit_pressure": "normal"}
        main._record_observability_state(obs_1)
        obs_2 = {"overall": "degraded", "retry_pressure": "high", "cache_pressure": "normal", "rate_limit_pressure": "normal"}
        main._record_observability_state(obs_2)

        self.assertGreaterEqual(obs_2.get("transitions_total", 0), 1)
        self.assertIn(obs_2.get("stability"), {"stable", "watch", "flapping"})
        self.assertIn("seconds_since_last_change", obs_2)


if __name__ == "__main__":
    unittest.main()
