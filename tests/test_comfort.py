"""Tests for derived outdoor-conditions values.

These numbers are computed rather than measured, so the tests care most about
the boundaries where a naive implementation would mislead: the sun being up
after the provider says the "day period" ended, night not inventing solar gain,
and missing inputs declining to answer rather than guessing.
"""

import unittest
from datetime import datetime, timedelta, timezone

from app import comfort


class SolarElevationTests(unittest.TestCase):
    # Oklahoma City, roughly.
    LAT, LON = 35.4676, -97.5164
    CDT = timezone(timedelta(hours=-5))

    def test_midday_sun_is_high_in_august(self):
        elev = comfort.solar_elevation_deg(datetime(2026, 8, 9, 13, 30, tzinfo=self.CDT), self.LAT, self.LON)
        self.assertGreater(elev, 60, f"expected a high summer sun, got {elev}")

    def test_sun_is_still_up_after_the_provider_calls_it_night(self):
        """The bug this guards: NWS isDaytime flips at 18:00 while sunset is ~20:22."""
        elev = comfort.solar_elevation_deg(datetime(2026, 8, 9, 18, 0, tzinfo=self.CDT), self.LAT, self.LON)
        self.assertGreater(elev, 10, "18:00 in August is not dark; paving is still loading")

    def test_after_sunset_elevation_is_negative(self):
        elev = comfort.solar_elevation_deg(datetime(2026, 8, 9, 22, 0, tzinfo=self.CDT), self.LAT, self.LON)
        self.assertLess(elev, 0)

    def test_intensity_ramps_rather_than_switching(self):
        low = comfort.solar_intensity(10)
        high = comfort.solar_intensity(70)
        self.assertLess(low, high)
        self.assertEqual(comfort.solar_intensity(-5), 0.0)
        self.assertEqual(comfort.solar_intensity(0), 0.0)


class SurfaceTemperatureTests(unittest.TestCase):
    def test_full_sun_paving_runs_far_above_air(self):
        surface = comfort.estimate_surface_temp_f(95, "Sunny", "5 mph", sun_elevation_deg=70)
        self.assertGreater(surface, 125, "dark paving in full sun should be well above air temp")

    def test_night_surface_falls_back_to_air_temp(self):
        self.assertEqual(comfort.estimate_surface_temp_f(80, "Clear", "5 mph", sun_elevation_deg=-10), 80.0)

    def test_cloud_cover_reduces_gain(self):
        sunny = comfort.estimate_surface_temp_f(90, "Sunny", "0 mph", sun_elevation_deg=60)
        cloudy = comfort.estimate_surface_temp_f(90, "Mostly Cloudy", "0 mph", sun_elevation_deg=60)
        self.assertLess(cloudy, sunny)

    def test_wind_provides_some_relief(self):
        calm = comfort.estimate_surface_temp_f(95, "Sunny", "0 mph", sun_elevation_deg=70)
        windy = comfort.estimate_surface_temp_f(95, "Sunny", "20 mph", sun_elevation_deg=70)
        self.assertLess(windy, calm)
        self.assertGreater(windy, 95, "wind should not cool paving to below air temperature")

    def test_longest_sky_match_wins(self):
        """'mostly cloudy' must not be captured by the shorter 'cloudy' key."""
        self.assertGreater(comfort.solar_factor("Mostly Cloudy"), comfort.solar_factor("Cloudy"))

    def test_missing_temperature_declines_to_answer(self):
        self.assertIsNone(comfort.estimate_surface_temp_f(None, "Sunny", "5 mph", sun_elevation_deg=70))


class CanineRiskTests(unittest.TestCase):
    def test_mild_conditions_are_ok(self):
        self.assertEqual(comfort.canine_heat_risk(68, 40)["level"], "ok")

    def test_hot_and_humid_is_danger(self):
        self.assertEqual(comfort.canine_heat_risk(88, 70)["level"], "danger")

    def test_very_hot_but_dry_still_flags(self):
        """The sum alone would let a hot dry afternoon score deceptively low."""
        self.assertEqual(comfort.canine_heat_risk(95, 15)["level"], "danger")

    def test_missing_humidity_falls_back_to_temperature(self):
        result = comfort.canine_heat_risk(92, None)
        self.assertEqual(result["level"], "danger")
        self.assertIsNone(result["sum"])
        self.assertIn("humidity unavailable", result["basis"])

    def test_missing_temperature_is_unknown_not_safe(self):
        self.assertEqual(comfort.canine_heat_risk(None, 50)["level"], "unknown")

    def test_basis_is_labelled_as_a_rule_of_thumb(self):
        """It must never read as a validated index."""
        self.assertIn("rule of thumb", comfort.canine_heat_risk(85, 50)["basis"])


class AnnotateHourTests(unittest.TestCase):
    def test_annotation_adds_derived_fields(self):
        row = {
            "start_time": "2026-08-09T14:00:00-05:00",
            "temp_f": 99,
            "humidity": 33,
            "wind_speed": "10 mph",
            "short_forecast": "Sunny",
        }
        out = comfort.annotate_hour(dict(row), 35.4676, -97.5164)
        self.assertIn("surface_temp_f", out)
        self.assertIn("canine_risk", out)
        self.assertIsNotNone(out["sun_elevation_deg"])
        self.assertGreater(out["surface_temp_f"], row["temp_f"])

    def test_annotation_survives_a_bad_timestamp(self):
        out = comfort.annotate_hour({"start_time": "not-a-date", "temp_f": 70}, 35.0, -97.0)
        self.assertIsNone(out["sun_elevation_deg"])
        self.assertIsNotNone(out["surface_temp_f"])

    def test_annotation_without_position_still_works(self):
        out = comfort.annotate_hour({"start_time": "2026-08-09T14:00:00-05:00", "temp_f": 70})
        self.assertIsNone(out["sun_elevation_deg"])
        self.assertIsNotNone(out["surface_temp_f"])


if __name__ == "__main__":
    unittest.main()
