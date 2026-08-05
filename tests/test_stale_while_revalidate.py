"""Regression tests for the stale-while-revalidate data-availability path.

These cover the defect where the viewer rendered an empty current-conditions
panel: an expired cache entry made the request wait on a slow upstream, and the
browser's 20s abort fired before the server ever answered. A recent reading was
sitting in the cache the whole time.
"""

import asyncio
import time
import unittest

from app import weather_client as wc


class StaleWhileRevalidateTests(unittest.TestCase):
    def setUp(self):
        wc.reset_runtime_telemetry()
        # These tests swap the module-global cache; restore it so they cannot
        # leak state into anything else running in the same process.
        self._real_cache = wc._cache
        self.addCleanup(self._restore_cache)

    def _restore_cache(self):
        for task in list(wc._BACKGROUND_REFRESH_TASKS):
            task.cancel()
        wc._BACKGROUND_REFRESH_TASKS.clear()
        wc._cache = self._real_cache
        wc.reset_runtime_telemetry()

    def _fresh_cache(self) -> wc.HybridTTLCache:
        # ":memory:" keeps each test isolated from the on-disk cache.
        return wc.HybridTTLCache(db_path=":memory:")

    def _seed_expired(self, cache: wc.HybridTTLCache, key: str, value, expired_by: float) -> None:
        """Put a value in the memory tier only, already expired by *expired_by* seconds.

        The two cache tiers expire independently: the memory tier honours the ttl
        passed to set(), while the SQLite tier applies its own policy TTL from
        resolve_ttl(). Writing through set() with a negative ttl would therefore
        leave a *fresh* SQLite row, and the ordinary get() path would answer from
        it before the stale path was ever reached. Seeding the memory tier
        directly reproduces the real situation: both tiers expired, a recent
        reading still in memory.
        """
        cache._store[key] = wc._Entry(value, -expired_by)

    def test_cold_key_waits_for_the_producer(self):
        """With nothing cached there is no stale answer, so the caller must block."""

        async def scenario():
            wc._cache = self._fresh_cache()

            async def producer():
                return {"temp": 10}

            result = await wc._get_or_refresh_shared("cold", "current", 60, producer)
            self.assertEqual(result, {"temp": 10})

        asyncio.run(scenario())

    def test_expired_key_answers_immediately_from_cache(self):
        """The whole point: an expired entry must not put a slow upstream on the request path."""

        async def scenario():
            cache = self._fresh_cache()
            wc._cache = cache
            self._seed_expired(cache, "warm", {"temp": 42}, expired_by=5)

            producer_started = asyncio.Event()

            async def slow_producer():
                producer_started.set()
                await asyncio.sleep(30)  # Far past the browser's 20s abort.
                return {"temp": 99}

            started = time.monotonic()
            result = await wc._get_or_refresh_shared("warm", "current", 60, slow_producer)
            elapsed = time.monotonic() - started

            self.assertEqual(result, {"temp": 42}, "should serve the cached reading")
            self.assertLess(elapsed, 1.0, "must not wait on the upstream")
            self.assertEqual(wc._CACHE_RUNTIME_STATS["stale_served"], 1)

            # The refresh should still have been kicked off in the background.
            await asyncio.wait_for(producer_started.wait(), timeout=2)

            for task in list(wc._BACKGROUND_REFRESH_TASKS):
                task.cancel()

        asyncio.run(scenario())

    def test_background_refresh_replaces_the_stale_value(self):
        """A served-stale request must still leave fresher data behind for the next one."""

        async def scenario():
            cache = self._fresh_cache()
            wc._cache = cache
            self._seed_expired(cache, "warm", {"temp": 42}, expired_by=5)

            async def producer():
                return {"temp": 55}

            first = await wc._get_or_refresh_shared("warm", "current", 60, producer)
            self.assertEqual(first, {"temp": 42})

            for task in list(wc._BACKGROUND_REFRESH_TASKS):
                await task

            second = await wc._get_or_refresh_shared("warm", "current", 60, producer)
            self.assertEqual(second, {"temp": 55}, "refreshed value should now be served")

        asyncio.run(scenario())

    def test_reading_older_than_the_cap_is_not_served(self):
        """Old weather must not be presented as current, however long the upstream takes."""

        async def scenario():
            cache = self._fresh_cache()
            wc._cache = cache
            self._seed_expired(
                cache, "ancient", {"temp": -100},
                expired_by=wc.STALE_WHILE_REVALIDATE_CAP_SEC + 600,
            )

            async def producer():
                return {"temp": 20}

            result = await wc._get_or_refresh_shared("ancient", "current", 60, producer)
            self.assertEqual(result, {"temp": 20}, "should fetch rather than serve a stale reading")
            self.assertEqual(wc._CACHE_RUNTIME_STATS["stale_served"], 0)

        asyncio.run(scenario())

    def test_upstream_failure_on_a_cold_key_still_raises(self):
        """No cached value and a failing upstream is a genuine error, not a silent blank."""

        async def scenario():
            wc._cache = self._fresh_cache()

            async def failing_producer():
                raise RuntimeError("upstream down")

            with self.assertRaises(RuntimeError):
                await wc._get_or_refresh_shared("cold", "current", 60, failing_producer)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
