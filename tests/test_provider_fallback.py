import unittest
import asyncio
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app import main


class ProviderFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_falls_back_to_weatherapi(self):
        main.PROVIDERS = {
            "nws": {"enabled": True},
            "weatherapi": {"enabled": True},
            "tomorrow": {"enabled": False},
            "visualcrossing": {"enabled": False},
        }

        with (
            patch("app.main.wc.get_current", new=AsyncMock(side_effect=RuntimeError("nws down"))),
            patch("app.main.wc.get_weatherapi_current", new=AsyncMock(return_value={"temp_f": 70})),
            patch("app.main._provider_api_key", side_effect=lambda pid: "k" if pid == "weatherapi" else ""),
        ):
            payload = await main.api_current()

        self.assertEqual(payload.get("source"), "weatherapi")
        self.assertEqual(payload.get("temp_f"), 70)

    async def test_forecast_tags_source_for_list_payload(self):
        main.PROVIDERS = {
            "nws": {"enabled": True},
            "weatherapi": {"enabled": False},
            "tomorrow": {"enabled": False},
            "visualcrossing": {"enabled": False},
        }

        with patch("app.main.wc.get_forecast", new=AsyncMock(return_value=[{"name": "Today"}])):
            payload = await main.api_forecast()

        self.assertIsInstance(payload, list)
        self.assertEqual(payload[0].get("source"), "nws")

    async def test_hourly_falls_through_to_visualcrossing(self):
        main.PROVIDERS = {
            "nws": {"enabled": True},
            "weatherapi": {"enabled": True},
            "tomorrow": {"enabled": True},
            "visualcrossing": {"enabled": True},
        }

        with (
            patch("app.main.wc.get_hourly", new=AsyncMock(side_effect=RuntimeError("nws fail"))),
            patch("app.main.wc.get_weatherapi_hourly", new=AsyncMock(side_effect=RuntimeError("weatherapi fail"))),
            patch("app.main.wc.get_tomorrow_hourly", new=AsyncMock(side_effect=RuntimeError("tomorrow fail"))),
            patch("app.main.wc.get_visualcrossing_hourly", new=AsyncMock(return_value=[{"temp_f": 65}])),
            patch("app.main._provider_api_key", return_value="key"),
        ):
            payload = await main.api_hourly()

        self.assertEqual(payload[0].get("source"), "visualcrossing")
        self.assertEqual(payload[0].get("temp_f"), 65)

    async def test_current_raises_when_no_provider_succeeds(self):
        main.PROVIDERS = {
            "nws": {"enabled": True},
            "weatherapi": {"enabled": False},
            "tomorrow": {"enabled": False},
            "visualcrossing": {"enabled": False},
        }

        with patch("app.main.wc.get_current", new=AsyncMock(side_effect=RuntimeError("nws fail"))):
            with self.assertRaises(HTTPException) as ctx:
                await main.api_current()

        self.assertEqual(ctx.exception.status_code, 502)
        detail = ctx.exception.detail
        self.assertEqual(detail.get("detail"), "No enabled/working current-conditions provider")

    async def test_current_timeout_falls_back_to_weatherapi(self):
        main.PROVIDERS = {
            "nws": {"enabled": True},
            "weatherapi": {"enabled": True},
            "tomorrow": {"enabled": False},
            "visualcrossing": {"enabled": False},
        }

        with (
            patch("app.main.wc.get_current", new=AsyncMock(side_effect=asyncio.TimeoutError("nws timeout"))),
            patch("app.main.wc.get_weatherapi_current", new=AsyncMock(return_value={"temp_f": 71})),
            patch("app.main._provider_api_key", side_effect=lambda pid: "k" if pid == "weatherapi" else ""),
        ):
            payload = await main.api_current()

        self.assertEqual(payload.get("source"), "weatherapi")
        self.assertEqual(payload.get("temp_f"), 71)

    async def test_forecast_rate_limited_falls_to_tomorrow(self):
        main.PROVIDERS = {
            "nws": {"enabled": False},
            "weatherapi": {"enabled": True},
            "tomorrow": {"enabled": True},
            "visualcrossing": {"enabled": False},
        }

        with (
            patch("app.main.wc.get_weatherapi_forecast", new=AsyncMock(side_effect=RuntimeError("429 Too Many Requests"))),
            patch("app.main.wc.get_tomorrow_forecast", new=AsyncMock(return_value=[{"name": "Today"}])),
            patch("app.main._provider_api_key", side_effect=lambda pid: "k" if pid in {"weatherapi", "tomorrow"} else ""),
        ):
            payload = await main.api_forecast()

        self.assertEqual(payload[0].get("source"), "tomorrow")

    async def test_hourly_503_falls_through_to_visualcrossing(self):
        main.PROVIDERS = {
            "nws": {"enabled": False},
            "weatherapi": {"enabled": False},
            "tomorrow": {"enabled": True},
            "visualcrossing": {"enabled": True},
        }

        with (
            patch("app.main.wc.get_tomorrow_hourly", new=AsyncMock(side_effect=RuntimeError("503 Service Unavailable"))),
            patch("app.main.wc.get_visualcrossing_hourly", new=AsyncMock(return_value=[{"temp_f": 63}])),
            patch("app.main._provider_api_key", side_effect=lambda pid: "k" if pid in {"tomorrow", "visualcrossing"} else ""),
        ):
            payload = await main.api_hourly()

        self.assertEqual(payload[0].get("source"), "visualcrossing")
        self.assertEqual(payload[0].get("temp_f"), 63)


class FallbackErrorMetadataTests(unittest.IsolatedAsyncioTestCase):
    """502 error payloads must include 'attempted' list and 'errors' map."""

    async def test_forecast_502_includes_attempted_and_errors(self):
        main.PROVIDERS = {
            "nws": {"enabled": True},
            "weatherapi": {"enabled": True},
            "tomorrow": {"enabled": False},
            "visualcrossing": {"enabled": False},
        }

        with (
            patch("app.main.wc.get_forecast", new=AsyncMock(side_effect=RuntimeError("nws timeout"))),
            patch(
                "app.main.wc.get_weatherapi_forecast",
                new=AsyncMock(side_effect=RuntimeError("weatherapi 503")),
            ),
            patch("app.main._provider_api_key", return_value="k"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await main.api_forecast()

        detail = ctx.exception.detail
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("nws", detail.get("attempted", []))
        self.assertIn("weatherapi", detail.get("attempted", []))
        self.assertIn("nws", detail.get("errors", {}))
        self.assertIn("weatherapi", detail.get("errors", {}))

    async def test_hourly_502_includes_attempted_and_errors(self):
        main.PROVIDERS = {
            "nws": {"enabled": True},
            "weatherapi": {"enabled": False},
            "tomorrow": {"enabled": True},
            "visualcrossing": {"enabled": False},
        }

        with (
            patch("app.main.wc.get_hourly", new=AsyncMock(side_effect=RuntimeError("nws fail"))),
            patch(
                "app.main.wc.get_tomorrow_hourly",
                new=AsyncMock(side_effect=RuntimeError("tomorrow fail")),
            ),
            patch("app.main._provider_api_key", return_value="testkey"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await main.api_hourly()

        detail = ctx.exception.detail
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("nws", detail.get("attempted", []))
        self.assertIn("tomorrow", detail.get("attempted", []))
        self.assertEqual(detail.get("errors", {}).get("nws"), "nws fail")
        self.assertEqual(detail.get("errors", {}).get("tomorrow"), "tomorrow fail")

    async def test_current_502_includes_provider_error_strings(self):
        main.PROVIDERS = {
            "nws": {"enabled": True},
            "weatherapi": {"enabled": True},
            "tomorrow": {"enabled": True},
            "visualcrossing": {"enabled": True},
        }

        with (
            patch("app.main.wc.get_current", new=AsyncMock(side_effect=RuntimeError("nws offline"))),
            patch(
                "app.main.wc.get_weatherapi_current",
                new=AsyncMock(side_effect=RuntimeError("weatherapi quota")),
            ),
            patch(
                "app.main.wc.get_tomorrow_current",
                new=AsyncMock(side_effect=RuntimeError("tomorrow auth")),
            ),
            patch(
                "app.main.wc.get_visualcrossing_current",
                new=AsyncMock(side_effect=RuntimeError("vc down")),
            ),
            patch("app.main._provider_api_key", return_value="key"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await main.api_current()

        detail = ctx.exception.detail
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(detail.get("errors", {}).get("nws"), "nws offline")
        self.assertEqual(detail.get("errors", {}).get("weatherapi"), "weatherapi quota")
        self.assertEqual(detail.get("errors", {}).get("tomorrow"), "tomorrow auth")
        self.assertEqual(detail.get("errors", {}).get("visualcrossing"), "vc down")
        self.assertEqual(len(detail.get("attempted", [])), 4)

    async def test_disabled_provider_not_in_attempted(self):
        """Disabled providers must never appear in the attempted list."""
        main.PROVIDERS = {
            "nws": {"enabled": True},
            "weatherapi": {"enabled": False},
            "tomorrow": {"enabled": False},
            "visualcrossing": {"enabled": False},
        }

        with patch("app.main.wc.get_current", new=AsyncMock(side_effect=RuntimeError("nws fail"))):
            with self.assertRaises(HTTPException) as ctx:
                await main.api_current()

        detail = ctx.exception.detail
        self.assertEqual(detail.get("attempted"), ["nws"])
        self.assertNotIn("weatherapi", detail.get("attempted", []))
        self.assertNotIn("tomorrow", detail.get("attempted", []))
        self.assertNotIn("visualcrossing", detail.get("attempted", []))


class AdminWriteGuardTests(unittest.IsolatedAsyncioTestCase):
    """POST /api/settings must be blocked for non-admins when auth is enabled."""

    async def test_settings_post_allowed_when_auth_disabled(self):
        """When AUTH_ENABLED=False the middleware is a no-op; route executes freely."""
        main.AUTH_ENABLED = False
        # We only test the guard, not the full save logic; patch _apply_config + file I/O.
        with (
            patch("app.main._load_config_file", return_value={}),
            patch("app.main.yaml.safe_dump"),
            patch("app.main._apply_config"),
            patch.object(main.SECURE_STORE, "set_json"),
            patch.object(main.SECURE_STORE, "delete"),
        ):
            from httpx import AsyncClient
            from fastapi.testclient import TestClient

            client = TestClient(main.app)
            resp = client.post(
                "/api/settings",
                json={
                    "location": {"home": {"lat": 36.1, "lon": -96.0, "label": "Test"}},
                    "mark_first_run_complete": False,
                },
            )
        # 200 or 400 are both fine — we just confirm no 401/403
        self.assertNotIn(resp.status_code, (401, 403))

    async def test_settings_post_blocked_for_unauthenticated_when_auth_enabled(self):
        main.AUTH_ENABLED = True
        main.AUTH_REQUIRE_VIEWER_LOGIN = False

        from fastapi.testclient import TestClient

        client = TestClient(main.app, raise_server_exceptions=False)
        resp = client.post(
            "/api/settings",
            json={"location": {"home": {"lat": 36.1, "lon": -96.0, "label": "Test"}}},
        )
        self.assertEqual(resp.status_code, 401)
        self.assertTrue(resp.headers.get("X-Request-ID"))

    async def test_settings_post_blocked_for_viewer_role(self):
        main.AUTH_ENABLED = True
        main.AUTH_TOKEN_SECRET = "test-secret"

        viewer_token = main._make_token("testviewer", "viewer")

        from fastapi.testclient import TestClient

        client = TestClient(main.app, raise_server_exceptions=False)
        resp = client.post(
            "/api/settings",
            headers={"Authorization": f"Bearer {viewer_token}"},
            json={"location": {"home": {"lat": 36.1, "lon": -96.0, "label": "Test"}}},
        )
        self.assertEqual(resp.status_code, 403)

    async def test_settings_get_allowed_for_viewer(self):
        main.AUTH_ENABLED = True
        main.AUTH_REQUIRE_VIEWER_LOGIN = False

        from fastapi.testclient import TestClient

        client = TestClient(main.app, raise_server_exceptions=False)
        resp = client.get("/api/settings")
        # GET is not admin-only; must not return 401/403
        self.assertNotIn(resp.status_code, (401, 403))
        self.assertTrue(resp.headers.get("X-Request-ID"))


if __name__ == "__main__":
    unittest.main()
