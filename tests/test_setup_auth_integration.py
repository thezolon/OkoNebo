import copy
import tempfile
import unittest
from pathlib import Path
import os

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
            "_TOKEN_DENYLIST_LOADED": main._TOKEN_DENYLIST_LOADED,
            "_LOGIN_ATTEMPT_BUCKETS": copy.deepcopy(main._LOGIN_ATTEMPT_BUCKETS),
            # Capture env var state so _apply_config doesn't pick up production .env
            "_env_AUTH_ENABLED": os.environ.pop("AUTH_ENABLED", None),
            "_env_AUTH_REQUIRE_VIEWER_LOGIN": os.environ.pop("AUTH_REQUIRE_VIEWER_LOGIN", None),
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
        # Restore env vars removed in setUp
        for key, env_key in [("_env_AUTH_ENABLED", "AUTH_ENABLED"), ("_env_AUTH_REQUIRE_VIEWER_LOGIN", "AUTH_REQUIRE_VIEWER_LOGIN")]:
            if self._orig[key] is not None:
                os.environ[env_key] = self._orig[key]
            else:
                os.environ.pop(env_key, None)
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

        me = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json().get("role"), "admin")

        logout = self.client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(logout.status_code, 200)

        me_after = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me_after.status_code, 401)

    def test_user_token_revocation_survives_restart_reload(self):
        main.AUTH_ENABLED = True
        main.AUTH_REQUIRE_VIEWER_LOGIN = True
        main.AUTH_TOKEN_SECRET = "integration-secret"
        main.SECURE_STORE.set_json(
            "auth.users",
            [{"username": "admin", "password_hash": main._hash_password("secret123"), "role": "admin"}],
        )

        login = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "secret123"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        token = login.json().get("token")
        self.assertTrue(token)

        logout = self.client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(logout.status_code, 200)

        # Simulate restart: clear in-memory denylist and force reload from SECURE_STORE.
        main._TOKEN_DENYLIST.clear()
        main._TOKEN_DENYLIST_LOADED = False

        me_after = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me_after.status_code, 401)

    def test_auth_guard_requires_viewer_login_when_enabled(self):
        main.AUTH_ENABLED = True
        main.AUTH_REQUIRE_VIEWER_LOGIN = True

        resp = self.client.get("/api/config")
        self.assertEqual(resp.status_code, 401)
        self.assertIn("Authentication required", resp.text)

    def test_first_run_settings_save_allowed_when_auth_enabled(self):
        main.AUTH_ENABLED = True
        main.AUTH_REQUIRE_VIEWER_LOGIN = True
        main.FIRST_RUN_COMPLETE = False

        resp = self.client.post(
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

        self.assertEqual(resp.status_code, 200, resp.text)
        bootstrap = self.client.get("/api/bootstrap")
        self.assertEqual(bootstrap.status_code, 200)
        self.assertFalse(bootstrap.json().get("first_run_required"))

    def test_env_credentials_ignored_when_sqlite_users_exist(self):
        os.environ["AUTH_ENABLED"] = "true"
        os.environ["ADMIN_USERNAME"] = "env-admin"
        os.environ["ADMIN_PASSWORD"] = "env-password-123"
        try:
            main.SECURE_STORE.set_json(
                "auth.users",
                [{
                    "username": "db-admin",
                    "role": "admin",
                    "password_hash": main._hash_password("db-password-123"),
                }],
            )

            cfg = main._load_config_file()
            main._apply_config(cfg)

            login_env = self.client.post(
                "/api/auth/login",
                json={"username": "env-admin", "password": "env-password-123"},
            )
            self.assertEqual(login_env.status_code, 401)

            login_db = self.client.post(
                "/api/auth/login",
                json={"username": "db-admin", "password": "db-password-123"},
            )
            self.assertEqual(login_db.status_code, 200, login_db.text)
        finally:
            os.environ.pop("ADMIN_USERNAME", None)
            os.environ.pop("ADMIN_PASSWORD", None)
            os.environ.pop("AUTH_ENABLED", None)

    def test_login_refreshes_users_after_store_update(self):
        main.AUTH_ENABLED = True
        main.AUTH_REQUIRE_VIEWER_LOGIN = False
        main.AUTH_USERS = [
            {
                "username": "admin",
                "role": "admin",
                "password_hash": main._hash_password("old-password-123"),
            }
        ]
        main.SECURE_STORE.set_json(
            "auth.users",
            [
                {
                    "username": "admin",
                    "role": "admin",
                    "password_hash": main._hash_password("new-password-123"),
                }
            ],
        )

        login = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "new-password-123"},
        )
        self.assertEqual(login.status_code, 200, login.text)

    def test_settings_rejects_invalid_timezone(self):
        main.AUTH_ENABLED = False
        resp = self.client.post(
            "/api/settings",
            json={
                "location": {
                    "home": {"lat": 36.1539, "lon": -95.9928, "label": "Home"},
                    "timezone": "Bad/Timezone",
                },
                "providers": {"nws": {"enabled": True}},
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Invalid timezone", resp.text)

    def test_settings_rejects_weak_admin_password(self):
        main.AUTH_ENABLED = False
        resp = self.client.post(
            "/api/settings",
            json={
                "location": {
                    "home": {"lat": 36.1539, "lon": -95.9928, "label": "Home"},
                    "timezone": "America/Chicago",
                },
                "auth": {
                    "admin_username": "admin-local",
                    "admin_password": "short",
                },
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("admin password", resp.text)

    def test_settings_rejects_invalid_viewer_username(self):
        main.AUTH_ENABLED = False
        resp = self.client.post(
            "/api/settings",
            json={
                "location": {
                    "home": {"lat": 36.1539, "lon": -95.9928, "label": "Home"},
                    "timezone": "America/Chicago",
                },
                "auth": {
                    "viewer_username": "x",
                    "viewer_password": "viewer123!",
                },
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("viewer username", resp.text)

    def test_settings_rejects_too_many_pws_stations(self):
        main.AUTH_ENABLED = False
        stations = [f"STATION-{i}" for i in range(11)]
        resp = self.client.post(
            "/api/settings",
            json={
                "location": {
                    "home": {"lat": 36.1539, "lon": -95.9928, "label": "Home"},
                    "timezone": "America/Chicago",
                },
                "pws": {
                    "provider": "weather.com",
                    "stations": stations,
                },
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("up to 10", resp.text)

    def test_settings_keeps_runtime_admin_password_when_blank(self):
        main.AUTH_ENABLED = True
        main.AUTH_REQUIRE_VIEWER_LOGIN = False
        main.FIRST_RUN_COMPLETE = False
        main.AUTH_USERS = [
            {
                "username": "admin",
                "role": "admin",
                "password_hash": main._hash_password("existing-password-123"),
            }
        ]

        resp = self.client.post(
            "/api/settings",
            json={
                "location": {
                    "home": {"lat": 36.1539, "lon": -95.9928, "label": "Home"},
                    "timezone": "America/Chicago",
                },
                "auth": {
                    "enabled": True,
                    "require_viewer_login": False,
                    "admin_username": "admin",
                    "admin_password": "",
                },
                "mark_first_run_complete": True,
            },
        )

        self.assertEqual(resp.status_code, 200, resp.text)
        stored_users = main.SECURE_STORE.get_json("auth.users", [])
        self.assertTrue(any(u.get("role") == "admin" and u.get("password_hash") for u in stored_users))

    def test_test_provider_supports_pws(self):
        main.AUTH_ENABLED = False
        main.PROVIDERS["pws"]["enabled"] = True

        original = main.wc.get_pws_observations

        async def fake_get_pws_observations(provider: str, station_ids: list[str], api_key: str) -> dict:
            self.assertEqual(provider, "weather.com")
            self.assertEqual(station_ids, ["KOKPRAGU2", "KOKPRAGU20"])
            self.assertEqual(api_key, "test-key")
            return {
                "provider": provider,
                "stations": [{"station_id": station_ids[0], "temp_f": 72.0}],
                "errors": [],
            }

        main.wc.get_pws_observations = fake_get_pws_observations
        try:
            # First configure PWS via settings
            settings_resp = self.client.post(
                "/api/settings",
                json={
                    "location": {"home": {"lat": 36.15, "lon": -95.99}, "timezone": "UTC"},
                    "pws": {
                        "provider": "weather.com",
                        "stations": ["KOKPRAGU2", "KOKPRAGU20"],
                        "api_key": "test-key",
                    },
                    "providers": {"pws": {"enabled": True}},
                },
            )
            self.assertEqual(settings_resp.status_code, 200, settings_resp.text)
            
            # Now test provider should work with stored config
            resp = self.client.get(
                "/api/test-provider",
                params={
                    "provider": "pws",
                    "api_key": "test-key",
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            payload = resp.json()
            self.assertTrue(payload.get("ok"))
            self.assertEqual(payload.get("provider"), "pws")
            self.assertIn("PWS API responding", payload.get("message", ""))
        finally:
            main.wc.get_pws_observations = original

    def test_test_provider_pws_uses_query_overrides(self):
        main.AUTH_ENABLED = False
        main.PROVIDERS["pws"]["enabled"] = True

        original = main.wc.get_pws_observations

        async def fake_get_pws_observations(provider: str, station_ids: list[str], api_key: str) -> dict:
            self.assertEqual(provider, "weather.com")
            self.assertEqual(station_ids, ["KOKPRAGU20", "KOKPRAGU2"])
            self.assertEqual(api_key, "test-key")
            return {
                "provider": provider,
                "stations": [{"station_id": station_ids[0], "temp_f": 72.0}],
                "errors": [],
            }

        main.wc.get_pws_observations = fake_get_pws_observations
        try:
            resp = self.client.get(
                "/api/test-provider",
                params={
                    "provider": "pws",
                    "api_key": "test-key",
                    "pws_provider": "weather.com",
                    "pws_stations": "KOKPRAGU20, KOKPRAGU2",
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            payload = resp.json()
            self.assertTrue(payload.get("ok"))
            self.assertEqual(payload.get("provider"), "pws")
        finally:
            main.wc.get_pws_observations = original

    def test_test_provider_uses_client_error_status_for_openweather(self):
        main.AUTH_ENABLED = False
        main.PROVIDERS["openweather"] = {"enabled": True}

        original = main.wc.test_provider

        async def fake_test_provider(**kwargs):
            self.assertEqual(kwargs.get("provider_id"), "openweather")
            return {
                "ok": False,
                "provider": "openweather",
                "error": "OpenWeather rejected the API key (401 Unauthorized). Verify the key and that it has One Call access enabled.",
                "status_code": 400,
            }

        main.wc.test_provider = fake_test_provider
        try:
            resp = self.client.get(
                "/api/test-provider",
                params={
                    "provider": "openweather",
                    "enabled": "true",
                    "api_key": "bad-key",
                },
            )
            self.assertEqual(resp.status_code, 400, resp.text)
            self.assertIn("401 Unauthorized", resp.text)
        finally:
            main.wc.test_provider = original

    def test_test_provider_post_body_supports_pws_overrides(self):
        main.AUTH_ENABLED = False
        main.PROVIDERS["pws"] = {"enabled": True}

        original = main.wc.get_pws_observations

        async def fake_get_pws_observations(provider: str, station_ids: list[str], api_key: str) -> dict:
            self.assertEqual(provider, "weather.com")
            self.assertEqual(station_ids, ["KOKPRAGU20", "KOKPRAGU2"])
            self.assertEqual(api_key, "test-key")
            return {
                "provider": provider,
                "stations": [{"station_id": station_ids[0], "temp_f": 72.0}],
                "errors": [],
            }

        main.wc.get_pws_observations = fake_get_pws_observations
        try:
            resp = self.client.post(
                "/api/test-provider",
                json={
                    "provider": "pws",
                    "enabled": True,
                    "api_key": "test-key",
                    "pws_provider": "weather.com",
                    "pws_stations": "KOKPRAGU20, KOKPRAGU2",
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            payload = resp.json()
            self.assertTrue(payload.get("ok"))
            self.assertEqual(payload.get("provider"), "pws")
        finally:
            main.wc.get_pws_observations = original

    def test_test_provider_redacts_secret_values_in_error_detail(self):
        main.AUTH_ENABLED = False
        main.PROVIDERS["openweather"] = {"enabled": True}

        original = main.wc.test_provider

        async def fake_test_provider(**kwargs):
            return {
                "ok": False,
                "provider": "openweather",
                "error": "https://api.example.test/onecall?appid=super-secret-key Authorization: Bearer token-123",
                "status_code": 400,
            }

        main.wc.test_provider = fake_test_provider
        try:
            resp = self.client.post(
                "/api/test-provider",
                json={
                    "provider": "openweather",
                    "enabled": True,
                    "api_key": "unused",
                },
            )
            self.assertEqual(resp.status_code, 400, resp.text)
            self.assertNotIn("super-secret-key", resp.text)
            self.assertNotIn("token-123", resp.text)
            self.assertIn("[REDACTED]", resp.text)
        finally:
            main.wc.test_provider = original


if __name__ == "__main__":
    unittest.main()
