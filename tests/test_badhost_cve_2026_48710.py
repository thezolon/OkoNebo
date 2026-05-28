"""
Regression tests for CVE-2026-48710 (BadHost) — Starlette Host-header auth bypass.

The vulnerability: Starlette < 1.0.1 constructs request.url from the Host header,
so a crafted Host like "example.com/api/auth/?x=" makes request.url.path return
"/api/auth/" while the real request targets a protected route. Any middleware that
gates on request.url.path can be bypassed.

The fix applied (2026-05-28):
  - app/main.py api_rate_limiter and api_auth_guard now use request.scope["path"],
    which comes directly from the ASGI scope and cannot be poisoned by a Host header.
  - starlette upgraded to >=1.0.1 (which also blocks malformed Host headers at the
    framework level, providing defense in depth).
"""

import copy
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import main


class _FakeStore:
    def __init__(self):
        self.data = {}

    def get_json(self, key, default=None):
        return copy.deepcopy(self.data.get(key, default))

    def set_json(self, key, value):
        self.data[key] = copy.deepcopy(value)

    def delete(self, key):
        self.data.pop(key, None)


class BadHostAuthBypassTests(unittest.TestCase):
    def setUp(self):
        self._orig = {
            "SECURE_STORE": main.SECURE_STORE,
            "_CONFIG_PATH": main._CONFIG_PATH,
            "AUTH_ENABLED": main.AUTH_ENABLED,
            "AUTH_REQUIRE_VIEWER_LOGIN": main.AUTH_REQUIRE_VIEWER_LOGIN,
            "AUTH_USERS": copy.deepcopy(main.AUTH_USERS),
            "AUTH_TOKEN_SECRET": main.AUTH_TOKEN_SECRET,
            "FIRST_RUN_COMPLETE": main.FIRST_RUN_COMPLETE,
            "_TOKEN_DENYLIST": copy.deepcopy(main._TOKEN_DENYLIST),
            "_TOKEN_DENYLIST_LOADED": main._TOKEN_DENYLIST_LOADED,
            "_LOGIN_ATTEMPT_BUCKETS": copy.deepcopy(main._LOGIN_ATTEMPT_BUCKETS),
            "_env_AUTH_ENABLED": os.environ.pop("AUTH_ENABLED", None),
            "_env_AUTH_REQUIRE_VIEWER_LOGIN": os.environ.pop("AUTH_REQUIRE_VIEWER_LOGIN", None),
        }

        self._tmpdir = tempfile.TemporaryDirectory()
        cfg = Path(self._tmpdir.name) / "config.yaml"
        cfg.write_text(
            "location:\n"
            "  lat: 36.1539\n"
            "  lon: -95.9928\n"
            "  label: Home\n"
            "  timezone: America/Chicago\n"
            "providers: {}\n"
        )

        main._CONFIG_PATH = cfg
        main.SECURE_STORE = _FakeStore()
        main.AUTH_ENABLED = False
        main.AUTH_REQUIRE_VIEWER_LOGIN = False
        main._TOKEN_DENYLIST.clear()
        main._TOKEN_DENYLIST_LOADED = False
        main._LOGIN_ATTEMPT_BUCKETS.clear()

        self.client = TestClient(main.app, raise_server_exceptions=False)

    def tearDown(self):
        main.SECURE_STORE = self._orig["SECURE_STORE"]
        main._CONFIG_PATH = self._orig["_CONFIG_PATH"]
        main.AUTH_ENABLED = self._orig["AUTH_ENABLED"]
        main.AUTH_REQUIRE_VIEWER_LOGIN = self._orig["AUTH_REQUIRE_VIEWER_LOGIN"]
        main.AUTH_USERS = self._orig["AUTH_USERS"]
        main.AUTH_TOKEN_SECRET = self._orig["AUTH_TOKEN_SECRET"]
        main.FIRST_RUN_COMPLETE = self._orig["FIRST_RUN_COMPLETE"]
        main._TOKEN_DENYLIST.clear()
        main._TOKEN_DENYLIST.update(self._orig["_TOKEN_DENYLIST"])
        main._TOKEN_DENYLIST_LOADED = self._orig["_TOKEN_DENYLIST_LOADED"]
        main._LOGIN_ATTEMPT_BUCKETS.clear()
        main._LOGIN_ATTEMPT_BUCKETS.update(self._orig["_LOGIN_ATTEMPT_BUCKETS"])
        for key, env_key in [
            ("_env_AUTH_ENABLED", "AUTH_ENABLED"),
            ("_env_AUTH_REQUIRE_VIEWER_LOGIN", "AUTH_REQUIRE_VIEWER_LOGIN"),
        ]:
            if self._orig[key] is not None:
                os.environ[env_key] = self._orig[key]
            else:
                os.environ.pop(env_key, None)
        self._tmpdir.cleanup()

    def test_protected_endpoint_blocked_without_auth(self):
        """Baseline: protected endpoints require auth when AUTH_REQUIRE_VIEWER_LOGIN is set."""
        main.AUTH_ENABLED = True
        main.AUTH_REQUIRE_VIEWER_LOGIN = True

        resp = self.client.get("/api/config")
        self.assertEqual(resp.status_code, 401)

        resp = self.client.get("/api/weather")
        self.assertEqual(resp.status_code, 401)

    def test_auth_endpoints_reachable_without_token(self):
        """Auth-prefix routes (/api/auth/*) must remain open — these are the login endpoints."""
        main.AUTH_ENABLED = True
        main.AUTH_REQUIRE_VIEWER_LOGIN = True

        resp = self.client.get("/api/auth/config")
        self.assertEqual(resp.status_code, 200)

    def test_host_header_injection_does_not_bypass_auth_guard(self):
        """CVE-2026-48710: crafted Host header must not unlock protected routes.

        Attacker sends GET /api/config with Host: localhost/api/auth/?x= hoping
        request.url.path resolves to /api/auth/ (the whitelisted prefix).
        With scope["path"] the guard sees the real path and rejects the request.
        """
        main.AUTH_ENABLED = True
        main.AUTH_REQUIRE_VIEWER_LOGIN = True

        # Inject /api/auth/ into the Host header — the classic BadHost payload
        crafted_headers = {"host": "localhost/api/auth/?bypass="}
        resp = self.client.get("/api/config", headers=crafted_headers)
        self.assertEqual(
            resp.status_code,
            401,
            "Host header injection bypassed auth guard (CVE-2026-48710)",
        )

    def test_host_header_injection_does_not_bypass_capabilities_whitelist(self):
        """/api/capabilities is whitelisted without auth; injection must not extend that."""
        main.AUTH_ENABLED = True
        main.AUTH_REQUIRE_VIEWER_LOGIN = True

        crafted_headers = {"host": "localhost/api/capabilities?x="}
        resp = self.client.get("/api/config", headers=crafted_headers)
        self.assertEqual(
            resp.status_code,
            401,
            "Capabilities whitelist injection bypassed auth guard (CVE-2026-48710)",
        )

    def test_rate_limiter_path_not_injectable_via_host(self):
        """Rate limiter uses scope['path'] — Host injection must not skip /api/ rate limiting."""
        main.AUTH_ENABLED = False

        # Non-api path with injected /api/ in Host — rate limiter should ignore
        # because scope["path"] is "/health", not "/api/..."
        resp = self.client.get("/health", headers={"host": "localhost/api/something"})
        # Should still reach the health endpoint normally (2xx or valid response)
        self.assertNotEqual(resp.status_code, 429, "Rate limiter incorrectly triggered on injected path")

    def test_authenticated_request_still_works_after_fix(self):
        """Valid token must still grant access — fix must not break legitimate auth."""
        main.AUTH_ENABLED = True
        main.AUTH_REQUIRE_VIEWER_LOGIN = True
        main.AUTH_TOKEN_SECRET = "regression-secret"
        main.SECURE_STORE.set_json(
            "auth.users",
            [{"username": "admin", "password": "secret123", "role": "admin"}],
        )

        login = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "secret123"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        token = login.json().get("token")
        self.assertTrue(token)

        resp = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("role"), "admin")


if __name__ == "__main__":
    unittest.main()
