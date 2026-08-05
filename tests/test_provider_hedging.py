"""Tests for hedged provider selection.

Providers used to be tried strictly one after another, so several degraded
upstreams stacked their timeouts and the browser aborted before the chain
finished. Hedging overlaps them, but only as far as it needs to: most of these
providers are paid or quota-limited, so a healthy primary must still cost
exactly one upstream call.
"""

import asyncio
import unittest

from app import main


class HedgedProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.attempted: list[str] = []
        self.errors: dict[str, str] = {}
        self._real_hedge = main.PROVIDER_HEDGE_DELAY_SEC
        self._real_deadline = main.PROVIDER_DEADLINE_SEC
        # Keep the tests fast; the behaviour under test is the ordering, not the
        # wall-clock constants.
        main.PROVIDER_HEDGE_DELAY_SEC = 0.05
        main.PROVIDER_DEADLINE_SEC = 2.0

    def tearDown(self):
        main.PROVIDER_HEDGE_DELAY_SEC = self._real_hedge
        main.PROVIDER_DEADLINE_SEC = self._real_deadline

    async def test_healthy_primary_costs_exactly_one_upstream_call(self):
        """The quota guarantee: a fast primary must never trigger a secondary."""
        called: list[str] = []

        async def fast_primary():
            called.append("primary")
            return {"temp": 1}

        async def secondary():
            called.append("secondary")
            return {"temp": 2}

        result = await main._fetch_hedged(
            "current",
            [("primary", fast_primary), ("secondary", secondary)],
            self.attempted,
            self.errors,
        )

        self.assertEqual(result["source"], "primary")
        self.assertEqual(called, ["primary"], "secondary must not be called when primary answers")

    async def test_slow_primary_brings_in_the_next_provider(self):
        """A stalled primary must not hold the whole request hostage."""
        called: list[str] = []

        async def slow_primary():
            called.append("primary")
            await asyncio.sleep(10)
            return {"temp": 1}

        async def secondary():
            called.append("secondary")
            return {"temp": 2}

        result = await main._fetch_hedged(
            "current",
            [("primary", slow_primary), ("secondary", secondary)],
            self.attempted,
            self.errors,
        )

        self.assertEqual(result["source"], "secondary", "should answer from the hedge")
        self.assertIn("secondary", called)

    async def test_failing_primary_falls_through(self):
        async def broken_primary():
            raise RuntimeError("primary down")

        async def secondary():
            return {"temp": 2}

        result = await main._fetch_hedged(
            "current",
            [("primary", broken_primary), ("secondary", secondary)],
            self.attempted,
            self.errors,
        )

        self.assertEqual(result["source"], "secondary")
        self.assertIn("primary", self.errors, "the failure should still be recorded")

    async def test_preference_order_is_respected_when_both_are_ready(self):
        """With both already resolved, the higher-priority provider wins."""

        async def primary():
            return {"src": "primary"}

        async def secondary():
            return {"src": "secondary"}

        result = await main._fetch_hedged(
            "current",
            [("primary", primary), ("secondary", secondary)],
            self.attempted,
            self.errors,
        )
        self.assertEqual(result["source"], "primary")

    async def test_all_failing_returns_none(self):
        async def broken():
            raise RuntimeError("down")

        result = await main._fetch_hedged(
            "current",
            [("a", broken), ("b", broken)],
            self.attempted,
            self.errors,
        )
        self.assertIsNone(result)
        self.assertEqual(sorted(self.errors), ["a", "b"])

    async def test_no_candidates_returns_none(self):
        self.assertIsNone(await main._fetch_hedged("current", [], self.attempted, self.errors))

    async def test_total_time_is_bounded_by_the_slowest_not_the_sum(self):
        """The whole point: four stalled providers must not stack their timeouts."""

        async def stalled():
            await asyncio.sleep(30)

        started = asyncio.get_running_loop().time()
        result = await main._fetch_hedged(
            "current",
            [(f"p{i}", stalled) for i in range(4)],
            self.attempted,
            self.errors,
        )
        elapsed = asyncio.get_running_loop().time() - started

        self.assertIsNone(result)
        self.assertLess(elapsed, main.PROVIDER_DEADLINE_SEC + 0.5, "must honour the overall deadline")

    async def test_losing_requests_are_cancelled(self):
        """A hedge that loses must not be left running against the upstream."""
        cancelled = asyncio.Event()

        async def slow_loser():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        async def fast_winner():
            return {"temp": 2}

        # Loser first so it is still in flight when the winner resolves.
        result = await main._fetch_hedged(
            "current",
            [("loser", slow_loser), ("winner", fast_winner)],
            self.attempted,
            self.errors,
        )
        self.assertEqual(result["source"], "winner")
        await asyncio.sleep(0)  # let the cancellation propagate
        self.assertTrue(cancelled.is_set(), "the losing request should be cancelled")


if __name__ == "__main__":
    unittest.main()
