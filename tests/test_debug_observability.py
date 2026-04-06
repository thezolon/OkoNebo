import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.redaction import redact_text


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

    def test_debug_client_snapshot_redacts_secrets(self):
        secret_url = "https://api.example.test/data?api_key=super-secret-key&appid=owm-secret"
        payload = {
            "request_url": secret_url,
            "headers": {
                "Authorization": "Bearer super-token",
                "X-Api-Key": "top-secret",
            },
            "auth": {"enabled": True},
            "password": "letmein",
            "icon_health": {
                "last_failed_url": secret_url,
                "fallback_count": 1,
            },
        }

        post_resp = self.client.post("/api/debug/client", json=payload)
        self.assertEqual(post_resp.status_code, 200)

        resp = self.client.get("/api/debug")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        client = body.get("client", {})
        self.assertNotIn("super-secret-key", str(client))
        self.assertNotIn("super-token", str(client))
        self.assertEqual(client.get("password"), "[REDACTED]")
        self.assertIn("[REDACTED]", client.get("request_url", ""))
        self.assertIn("[REDACTED]", body.get("pws_icon_diagnostics", {}).get("last_failed_url", ""))

    def test_redact_text_scrubs_urls_and_bearer_tokens(self):
        raw = "GET https://example.test?api_key=abc123&password=hunter2 Authorization: Bearer token-123"
        redacted = redact_text(raw)
        self.assertNotIn("abc123", redacted)
        self.assertNotIn("hunter2", redacted)
        self.assertNotIn("token-123", redacted)
        self.assertIn("[REDACTED]", redacted)


if __name__ == "__main__":
    unittest.main()
