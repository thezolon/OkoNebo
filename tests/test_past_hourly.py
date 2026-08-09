"""Tests for the observed-hours strip that precedes the forecast on the chart.

The forecast begins at the current hour, which pinned the "Now" marker against
the left edge of the chart. These rows are real station observations, so the
tests care most about not letting an observation pretend to be a forecast: no
invented precipitation probability, no fabricated humidity, and hourly buckets
that pick the reading nearest the hour rather than whichever arrived last.
"""

import unittest
from unittest.mock import AsyncMock, patch

from app import weather_client as wc


def _obs(timestamp, temp_c=None, rh=None, dewpoint_c=None, text="Clear"):
    return {
        "properties": {
            "timestamp": timestamp,
            "temperature": {"value": temp_c},
            "relativeHumidity": {"value": rh},
            "dewpoint": {"value": dewpoint_c},
            "windSpeed": {"value": None},
            "windDirection": {"value": None},
            "textDescription": text,
            "icon": None,
        }
    }


class DewpointHumidityTests(unittest.TestCase):
    def test_humidity_derived_from_dewpoint(self):
        """Many stations publish temperature and dewpoint but leave RH null."""
        rh = wc._rh_from_dewpoint(30.0, 20.0)
        self.assertIsNotNone(rh)
        self.assertTrue(50 < rh < 60, f"expected roughly 55%, got {rh}")

    def test_saturated_air_is_about_one_hundred(self):
        self.assertAlmostEqual(wc._rh_from_dewpoint(20.0, 20.0), 100.0, delta=0.5)

    def test_missing_inputs_yield_none_not_a_guess(self):
        self.assertIsNone(wc._rh_from_dewpoint(None, 10.0))
        self.assertIsNone(wc._rh_from_dewpoint(25.0, None))


class PastHourlyTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, features, hours=6):
        raw = {"features": features}
        # The cache key is derived from coordinates, so every test needs its own
        # or the first one to run answers for all the others. This bit me: the
        # suite passed individually and failed together.
        seed = abs(hash(self.id())) % 100000
        lat, lon = 10 + seed / 100000, 60 + seed / 100000
        with (
            patch.object(wc, "_resolve_point", new=AsyncMock(return_value={"station_url": "https://x/stations/K/observations/latest"})),
            patch.object(wc, "_get", new=AsyncMock(return_value=raw)),
        ):
            return await wc.get_past_hourly(lat, lon, "test-agent", hours=hours)

    async def test_observations_are_bucketed_to_the_hour(self):
        rows = await self._run([
            _obs("2026-08-09T10:05:00+00:00", temp_c=20),
            _obs("2026-08-09T10:55:00+00:00", temp_c=25),
            _obs("2026-08-09T11:02:00+00:00", temp_c=30),
        ])
        stamps = [r["start_time"][11:16] for r in rows]
        self.assertEqual(stamps, ["10:00", "11:00"], "one row per hour")

    async def test_bucket_keeps_the_observation_nearest_the_hour(self):
        """10:05 is closer to the hour than 10:55, so it should win."""
        rows = await self._run([
            _obs("2026-08-09T10:05:00+00:00", temp_c=20),
            _obs("2026-08-09T10:55:00+00:00", temp_c=25),
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["temp_f"], 68.0, "expected the 10:05 reading (20C)")

    async def test_precip_probability_is_never_invented(self):
        """An observation cannot carry a forecast probability."""
        rows = await self._run([_obs("2026-08-09T10:00:00+00:00", temp_c=20)])
        self.assertIsNone(rows[0]["precip_percent"])

    async def test_rows_are_marked_as_past(self):
        rows = await self._run([_obs("2026-08-09T10:00:00+00:00", temp_c=20)])
        self.assertTrue(rows[0]["is_past"], "consumers must be able to tell observation from forecast")

    async def test_humidity_backfilled_from_dewpoint_when_absent(self):
        rows = await self._run([_obs("2026-08-09T10:00:00+00:00", temp_c=30, rh=None, dewpoint_c=20)])
        self.assertIsNotNone(rows[0]["humidity"])

    async def test_humidity_stays_none_when_station_reports_neither(self):
        rows = await self._run([_obs("2026-08-09T10:00:00+00:00", temp_c=30, rh=None, dewpoint_c=None)])
        self.assertIsNone(rows[0]["humidity"], "a gap is better than a fabricated reading")

    async def test_result_is_capped_to_requested_hours(self):
        features = [_obs(f"2026-08-09T{h:02d}:00:00+00:00", temp_c=20 + h) for h in range(0, 20)]
        rows = await self._run(features, hours=6)
        self.assertLessEqual(len(rows), 6)

    async def test_rows_are_chronological(self):
        features = [
            _obs("2026-08-09T12:00:00+00:00", temp_c=25),
            _obs("2026-08-09T10:00:00+00:00", temp_c=20),
            _obs("2026-08-09T11:00:00+00:00", temp_c=22),
        ]
        rows = await self._run(features)
        stamps = [r["start_time"] for r in rows]
        self.assertEqual(stamps, sorted(stamps))

    async def test_malformed_timestamps_are_skipped_not_fatal(self):
        rows = await self._run([
            _obs("not-a-timestamp", temp_c=20),
            _obs("2026-08-09T10:00:00+00:00", temp_c=22),
        ])
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
