"""Humidity must reach the hourly payload from every provider that offers it.

The hourly chart plots humidity alongside temperature and precipitation. If a
provider's normaliser drops the field, the series silently disappears when that
provider is the one answering -- which looks like a chart bug rather than a
missing mapping.
"""

import unittest
from unittest.mock import AsyncMock, patch

from app import weather_client as wc


class NwsHourlyHumidityTests(unittest.IsolatedAsyncioTestCase):
    async def test_relative_humidity_is_extracted(self):
        raw = {
            "properties": {
                "periods": [
                    {
                        "startTime": "2026-08-05T14:00:00-05:00",
                        "temperature": 88,
                        "windSpeed": "10 mph",
                        "windDirection": "S",
                        "shortForecast": "Sunny",
                        "icon": "https://api.weather.gov/icons/land/day/skc",
                        "probabilityOfPrecipitation": {"value": 10},
                        "relativeHumidity": {"value": 64},
                    }
                ]
            }
        }

        with (
            patch.object(wc, "_resolve_point", new=AsyncMock(return_value={"forecast_hourly_url": "u"})),
            patch.object(wc, "_get", new=AsyncMock(return_value=raw)),
        ):
            # Unique coordinates keep this off any cached key.
            rows = await wc.get_hourly(11.111, 22.222, "test-agent")

        self.assertEqual(rows[0]["humidity"], 64)
        self.assertEqual(rows[0]["temp_f"], 88)
        self.assertEqual(rows[0]["precip_percent"], 10)

    async def test_missing_humidity_becomes_none_not_zero(self):
        """A provider omitting the field must not read as 0% RH."""
        raw = {
            "properties": {
                "periods": [
                    {
                        "startTime": "2026-08-05T15:00:00-05:00",
                        "temperature": 90,
                        "windSpeed": "5 mph",
                        "windDirection": "N",
                        "shortForecast": "Clear",
                        "icon": "https://api.weather.gov/icons/land/day/skc",
                        "probabilityOfPrecipitation": {"value": None},
                    }
                ]
            }
        }

        with (
            patch.object(wc, "_resolve_point", new=AsyncMock(return_value={"forecast_hourly_url": "u"})),
            patch.object(wc, "_get", new=AsyncMock(return_value=raw)),
        ):
            rows = await wc.get_hourly(33.333, 44.444, "test-agent")

        self.assertIsNone(rows[0]["humidity"], "absent humidity must be None, never 0")


class HourlyNormaliserCoverageTests(unittest.TestCase):
    """Every hourly normaliser should map humidity, so failover keeps the series."""

    def test_all_hourly_providers_map_humidity(self):
        import inspect

        source = inspect.getsource(wc)
        for func_name in (
            "get_hourly",
            "get_weatherapi_hourly",
            "get_tomorrow_hourly",
            "get_visualcrossing_hourly",
        ):
            start = source.index(f"async def {func_name}(")
            # Bound the slice at the next top-level def so we only read this function.
            nxt = source.find("\nasync def ", start + 1)
            body = source[start : nxt if nxt != -1 else len(source)]
            self.assertIn(
                '"humidity"',
                body,
                f"{func_name} does not map humidity; the chart series will vanish when it answers",
            )


if __name__ == "__main__":
    unittest.main()
