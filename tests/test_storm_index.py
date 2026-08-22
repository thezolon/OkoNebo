"""Tests for the local storm heuristic.

The case that prompted the rewrite is first: a squall line directly overhead,
the station reporting "Thunderstorms and Rain", and the old client-side version
reporting "Storm: Low" because it looked only at alerts, gusts and a pressure
reading the station does not publish.
"""

import unittest

from app.storm import compute_storm_index


class TheCaseThatPromptedTheRewrite(unittest.TestCase):
    def test_thunderstorms_overhead_are_not_low(self):
        """Live values from the morning this was reported, verbatim."""
        result = compute_storm_index(
            current={
                "description": "Thunderstorms and Rain",
                "wind_speed_mph": 9.2,
                "wind_gust_mph": None,     # station reports no gust
                "pressure_inhg": None,     # station reports no pressure
            },
            alerts=[],                     # no warning issued for the point
            hourly=[{"precip_percent": 33}, {"precip_percent": 33}, {"precip_percent": 30}],
            pws={"stations": []},
        )
        self.assertNotEqual(result["level"], "low", "storms overhead must not read as Low")
        self.assertIn("thunderstorms observed", result["reasons"])

    def test_missing_pressure_does_not_disable_the_branch_silently(self):
        """The old code substituted 99 inHg, which no barometer can go below."""
        result = compute_storm_index(current={"description": "Clear", "pressure_inhg": None})
        self.assertFalse(
            any("pressure" in r for r in result["reasons"]),
            "absent pressure should contribute nothing and claim nothing",
        )

    def test_sustained_wind_is_not_scored_as_a_gust(self):
        """The old code fell back to sustained wind and weighted it as a gust."""
        breezy = compute_storm_index(current={"description": "Clear", "wind_speed_mph": 40, "wind_gust_mph": None})
        self.assertEqual(breezy["level"], "low")
        self.assertFalse(any("gust" in r for r in breezy["reasons"]))


class ConditionSignalTests(unittest.TestCase):
    def test_tornado_dominates(self):
        result = compute_storm_index(current={"description": "Tornado"})
        self.assertEqual(result["level"], "severe")

    def test_strongest_matching_signal_wins(self):
        """'Severe Thunderstorm' must not be scored as plain rain."""
        severe = compute_storm_index(current={"description": "Severe Thunderstorm"})
        plain = compute_storm_index(current={"description": "Light Rain"})
        self.assertGreater(severe["score"], plain["score"])

    def test_clear_conditions_score_nothing(self):
        result = compute_storm_index(current={"description": "Clear"})
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["level"], "low")
        self.assertIn("no storm signals in current readings", result["reasons"])

    def test_short_forecast_is_used_when_description_absent(self):
        result = compute_storm_index(current={"short_forecast": "Thunderstorms"})
        self.assertGreater(result["score"], 0)


class AlertScopeTests(unittest.TestCase):
    def test_viewport_only_alerts_are_ignored(self):
        """Advisories 300 miles away say nothing about conditions here."""
        result = compute_storm_index(
            current={"description": "Clear"},
            alerts=[
                {"event": "Heat Advisory", "severity": "Moderate", "monitored_locations": ["Viewport SW"]},
                {"event": "Heat Advisory", "severity": "Moderate", "monitored_locations": ["Viewport SE"]},
            ],
        )
        self.assertEqual(result["score"], 0, "viewport-only alerts must not raise the local index")

    def test_alerts_over_a_monitored_location_count(self):
        result = compute_storm_index(
            current={"description": "Clear"},
            alerts=[{"event": "Tornado Warning", "severity": "Extreme", "monitored_locations": ["Home"]}],
        )
        # A floor, not a sum: 50 points alone would land in "Elevated".
        self.assertEqual(result["level"], "extreme")
        self.assertIn("Tornado Warning in effect", result["reasons"])

    def test_untagged_alerts_are_treated_as_local(self):
        """Point queries carry no location tags."""
        result = compute_storm_index(
            current={"description": "Clear"},
            alerts=[{"event": "Severe Thunderstorm Warning", "severity": "Severe"}],
        )
        self.assertGreater(result["score"], 0)


class StationReadingTests(unittest.TestCase):
    def test_reported_gusts_count(self):
        result = compute_storm_index(current={"description": "Clear", "wind_gust_mph": 48})
        self.assertIn("gusts to 48 mph", result["reasons"])

    def test_pws_gusts_are_considered(self):
        result = compute_storm_index(
            current={"description": "Clear"},
            pws={"stations": [{"wind_gust_mph": 50}]},
        )
        self.assertGreater(result["score"], 0)

    def test_implausible_pressure_is_rejected(self):
        """A 99 inHg sentinel, or any nonsense, must not be treated as a reading."""
        result = compute_storm_index(current={"description": "Clear", "pressure_inhg": 99})
        self.assertFalse(any("pressure" in r for r in result["reasons"]))

    def test_genuine_low_pressure_registers(self):
        result = compute_storm_index(current={"description": "Clear", "pressure_inhg": 29.4})
        self.assertTrue(any("low pressure" in r for r in result["reasons"]))


class SeverityFloorTests(unittest.TestCase):
    """A warning must never be reportable as something mild."""

    def test_severe_alert_floors_at_severe(self):
        result = compute_storm_index(
            current={"description": "Clear"},
            alerts=[{"event": "Severe Thunderstorm Warning", "severity": "Severe", "monitored_locations": ["Home"]}],
        )
        self.assertEqual(result["level"], "severe")

    def test_observed_tornado_floors_at_severe_without_any_alert(self):
        result = compute_storm_index(current={"description": "Tornado"}, alerts=[])
        self.assertIn(result["level"], ("severe", "extreme"))

    def test_a_floor_never_lowers_a_higher_score(self):
        result = compute_storm_index(
            current={"description": "Tornado", "wind_gust_mph": 60, "pressure_inhg": 29.3},
            alerts=[{"event": "Tornado Warning", "severity": "Extreme", "monitored_locations": ["Home"]}],
        )
        self.assertEqual(result["level"], "extreme")

    def test_moderate_alerts_do_not_floor(self):
        result = compute_storm_index(
            current={"description": "Clear"},
            alerts=[{"event": "Heat Advisory", "severity": "Moderate", "monitored_locations": ["Home"]}],
        )
        self.assertEqual(result["level"], "guarded")


class ContractTests(unittest.TestCase):
    def test_every_result_explains_itself(self):
        """The old version offered no explanation anywhere in the product."""
        for payload in ({}, {"description": "Clear"}, {"description": "Tornado"}):
            result = compute_storm_index(current=payload)
            self.assertTrue(result["reasons"], "a score with no stated reason is untrustworthy")

    def test_result_disclaims_being_an_official_product(self):
        result = compute_storm_index(current={"description": "Clear"})
        self.assertIn("not an NWS product", result["basis"])

    def test_bands_are_ordered(self):
        calm = compute_storm_index(current={"description": "Clear"})["score"]
        rain = compute_storm_index(current={"description": "Rain"})["score"]
        storm = compute_storm_index(current={"description": "Thunderstorms and Rain"})["score"]
        tornado = compute_storm_index(current={"description": "Tornado"})["score"]
        self.assertLess(calm, rain)
        self.assertLess(rain, storm)
        self.assertLess(storm, tornado)

    def test_no_inputs_is_safe(self):
        result = compute_storm_index()
        self.assertEqual(result["level"], "low")
        self.assertEqual(result["score"], 0)


if __name__ == "__main__":
    unittest.main()
