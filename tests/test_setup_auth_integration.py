import copy
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


class SetupAuthIntegrationTests(unittest.TestCase):
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
            "_LOGIN_ATTEMPT_BUCKETS": copy.deepcopy(main._LOGIN_ATTEMPT_BUCKETS),
        }

        self._tmpdir = tempfile.TemporaryDirectory()
        self._cfg_path = Path(self._tmpdir.name) / "config.yaml"
        self._cfg_path.write_text(
            "location:\n"
            "  lat: 36.1539\n"
            "  lon: -95.9928\n"
            "  label: Home\n"
            "  timezone: America/Chicago\n"
            "providers: {}\n"
        )

        main._CONFIG_PATH = self._cfg_path
        main.SECURE_STORE = _FakeStore()
        main._TOKEN_DENYLIST.clear()
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
        main._LOGIN_ATTEMPT_BUCKETS.clear()
        main._LOGIN_ATTEMPT_BUCKETS.update(self._orig["_LOGIN_ATTEMPT_BUCKETS"])
        self._tmpdir.cleanup()

    def test_bootstrap_first_run_flips_false_after_settings_save(self):
        main.AUTH_ENABLED = False
        main.AUTH_REQUIRE_VIEWER_LOGIN = False
        main.FIRST_RUN_COMPLETE = False

        bootstrap_before = self.client.get("/api/bootstrap")
        self.assertEqual(bootstrap_before.status_code, 200)
        self.assertTrue(bootstrap_before.json().get("first_run_required"))

        save_resp = self.client.post(
            "/api/settings",
            json={
                "location": {
                    "home": {"lat": 36.1539, "lon": -95.9928, "label": "Home"},
                    "timezone": "America/Chicago",
                },
                "providers": {
                    "nws": {"enabled": True},
                    "aviationweather": {"enabled": True},
                    "noaa_tides": {"enabled": True},
                },
                "mark_first_run_complete": True,
            },
        )
        self.assertEqual(save_resp.status_code, 200, save_resp.text)

        bootstrap_after = self.client.get("/api/bootstrap")
        self.assertEqual(bootstrap_after.status_code, 200)
        self.assertFalse(bootstrap_after.json().get("first_run_required"))

    def test_auth_config_reflects_runtime_flags(self):
        main.AUTH_ENABLED = True
        main.AUTH_REQUIRE_VIEWER_LOGIN = True

        resp = self.client.get("/api/auth/config")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body.get("enabled"))
        self.assertTrue(body.get("require_viewer_login"))

    def test_auth_login_me_logout_revokes_token(self):
        main.AUTH_ENABLED = True
        main.AUTH_REQUIRE_VIEWER_LOGIN = True
        main.AUTH_TOKEN_SECRET = "integration-secret"
        main.AUTH_USERS = [{"username": "admin", "password": "secret123", "role": "admin"}]

        login = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "secret123"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        token = login.json().get("token")
        self.assertTrue(token)

        me = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json().get("role"), "admin")

        logout = self.client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(logout.status_code, 200)

        me_after = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me_after.status_code, 401)

    def test_auth_guard_requires_viewer_login_when_enabled(self):
        main.AUTH_ENABLED = True
        main.AUTH_REQUIRE_VIEWER_LOGIN = True

        resp = self.client.get("/api/config")
        self.assertEqual(resp.status_code, 401)
        self.assertIn("Authentication required", resp.text)


if __name__ == "__main__":
    unittest.main()
