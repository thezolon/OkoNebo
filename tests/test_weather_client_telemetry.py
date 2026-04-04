import unittest
import time
from unittest.mock import patch

import httpx

from app import weather_client as wc


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.request = httpx.Request("GET", "https://example.test")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=self.request,
                response=self,
            )

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, responses):
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None):
        if not self._responses:
            raise RuntimeError("no fake responses left")
        next_item = self._responses.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item


class WeatherClientTelemetryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        wc.reset_runtime_telemetry()

    async def test_retry_stats_record_attempted_and_exhausted(self):
        responses = [
            _FakeResponse(429, {"error": "rate"}),
            _FakeResponse(503, {"error": "still down"}),
            _FakeResponse(503, {"error": "down"}),
        ]

        with (
            patch("app.weather_client.httpx.AsyncClient", return_value=_FakeClient(responses)),
        ):
            with self.assertRaises(httpx.HTTPStatusError):
                await wc._json_get_with_retry("https://example.test", {"x": 1}, "weatherapi")

        stats = wc.get_upstream_call_stats()
        retry_stats = stats.get("retries", {}).get("weatherapi", {})
        self.assertEqual(retry_stats.get("attempted"), 2)
        self.assertEqual(retry_stats.get("exhausted"), 1)

    async def test_cache_runtime_stats_track_hits_and_misses(self):
        key = f"telemetry-test-cache-key-{time.time_ns()}"
        missing = await wc._cache.get(key, cache_type="default")
        self.assertIsNone(missing)

        await wc._cache.set(key, {"ok": True}, ttl=60, cache_type="default")
        found = await wc._cache.get(key, cache_type="default")
        self.assertEqual(found, {"ok": True})

        stats = wc.get_upstream_call_stats().get("cache_runtime", {})
        self.assertGreaterEqual(stats.get("miss", 0), 1)
        self.assertGreaterEqual(stats.get("set", 0), 1)
        self.assertGreaterEqual(stats.get("memory_hit", 0), 1)


if __name__ == "__main__":
    unittest.main()
