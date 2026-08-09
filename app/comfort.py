"""Derived outdoor-conditions values.

Everything here is *computed*, not measured, and the API labels it that way. The
distinction matters: this dashboard already displays a locally-invented "Storm
Index" with the same visual authority as National Weather Service data, which is
the sort of thing that teaches a reader to trust a number nobody validated.
These values are presented as estimates and guidance, never as observations.

Two things are modelled, both aimed at the same question -- is it reasonable to
be outside right now, with dogs:

**Surface temperature.** Air temperature is measured around five feet up. A dog
walks on the ground, and dark paving in direct sun runs far hotter than the air
above it. This is the number that burns paws, and no air-temperature reading
will ever show it.

**Canine heat risk.** Human "feels like" is the wrong instrument here: the heat
index models sweat evaporating from human skin. Dogs shed heat by panting, which
humidity degrades on a different curve, so the human number does not merely
mis-scale for a dog -- it bends the wrong way. There is no official canine
equivalent of the heat index, so what is offered is an explicitly-labelled rule
of thumb, not a standard.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

# Rough solar gain of dark asphalt in full sun over the air temperature, in
# Fahrenheit. Field measurements commonly land in the +40 to +60 range; the lower
# bound is used so the estimate errs toward under-alarming rather than crying
# wolf. Grass and light concrete sit far below this -- the figure describes the
# worst common surface a dog is walked on, which is the one worth planning around.
_FULL_SUN_ASPHALT_GAIN_F = 45.0

# Wind carries some of that load away. Capped because a breeze does not turn
# asphalt into grass.
_WIND_RELIEF_PER_MPH = 0.9
_MAX_WIND_RELIEF_F = 14.0

# Fraction of full solar gain reaching the surface, by sky description. Keys are
# matched as substrings against the provider's short forecast text.
_SKY_SOLAR_FACTOR: tuple[tuple[str, float], ...] = (
    ("sunny", 1.0),
    ("clear", 1.0),
    ("mostly sunny", 0.9),
    ("mostly clear", 0.9),
    ("partly sunny", 0.7),
    ("partly cloudy", 0.7),
    ("mostly cloudy", 0.4),
    ("cloudy", 0.3),
    ("overcast", 0.25),
    ("fog", 0.2),
    ("rain", 0.15),
    ("shower", 0.15),
    ("thunderstorm", 0.15),
    ("snow", 0.1),
)


def _wind_mph(raw: Any) -> float:
    """Provider wind is free text such as '10 mph' or '5 to 10 mph'."""
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    numbers = re.findall(r"\d+(?:\.\d+)?", str(raw))
    if not numbers:
        return 0.0
    # Use the upper bound of a range: more wind means more relief, so the lower
    # bound would overstate the surface temperature.
    return float(numbers[-1])


def solar_elevation_deg(when: datetime, lat: float, lon: float) -> float:
    """Sun's angle above the horizon, in degrees. Negative after sunset.

    Deliberately not using the provider's isDaytime flag. That field marks
    forecast *periods* -- it flips to False at 18:00 on a day the sun does not
    set until 20:22 -- so trusting it would report paving at air temperature
    through two hours of strong evening sun. Elevation also gives a gradual ramp
    rather than a switch, which is how solar load actually behaves.
    """
    utc = when.astimezone(timezone.utc)
    day_of_year = int(utc.strftime("%j"))
    frac_hour = utc.hour + utc.minute / 60 + utc.second / 3600

    # Declination and equation of time (NOAA low-precision approximations).
    gamma = 2 * math.pi / 365 * (day_of_year - 1 + (frac_hour - 12) / 24)
    eqtime = 229.18 * (
        0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma)
    )
    decl = (
        0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma)
    )

    time_offset = eqtime + 4 * lon
    true_solar_time = (frac_hour * 60 + time_offset) % 1440
    hour_angle = math.radians(true_solar_time / 4 - 180)
    lat_rad = math.radians(lat)

    cos_zenith = (
        math.sin(lat_rad) * math.sin(decl)
        + math.cos(lat_rad) * math.cos(decl) * math.cos(hour_angle)
    )
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    return round(90.0 - math.degrees(math.acos(cos_zenith)), 2)


def solar_intensity(elevation_deg: float) -> float:
    """Fraction of peak solar load at a given sun elevation, 0.0-1.0.

    Load scales roughly with the sine of elevation. A low sun spreads the same
    energy over more ground, which is why late afternoon paving is hot but not
    as hot as noon.
    """
    if elevation_deg <= 0:
        return 0.0
    return round(min(1.0, math.sin(math.radians(elevation_deg))), 4)


def solar_factor(short_forecast: Any, is_daytime: bool = True) -> float:
    """How much of full solar gain the sky condition lets through, 0.0-1.0."""
    if not is_daytime:
        return 0.0
    text = str(short_forecast or "").lower()
    # Longest match wins, so "mostly cloudy" is not captured by "cloudy".
    best = None
    for token, factor in _SKY_SOLAR_FACTOR:
        if token in text and (best is None or len(token) > len(best[0])):
            best = (token, factor)
    if best:
        return best[1]
    return 0.6 if text else 0.0


def estimate_surface_temp_f(
    air_temp_f: float | None,
    short_forecast: Any = None,
    wind: Any = None,
    is_daytime: bool = True,
    sun_elevation_deg: float | None = None,
) -> float | None:
    """Estimated temperature of dark paving in the open.

    Returns None when air temperature is unknown. At night the surface is taken
    as the air temperature: paving does hold heat after dark, but modelling that
    properly needs the preceding hours' load, and guessing would be worse than
    declining to answer.
    """
    if air_temp_f is None:
        return None

    sky = solar_factor(short_forecast, True)
    # Fall back to the coarse day/night flag only when position is unavailable.
    intensity = solar_intensity(sun_elevation_deg) if sun_elevation_deg is not None else (1.0 if is_daytime else 0.0)
    factor = sky * intensity
    if factor <= 0:
        return round(float(air_temp_f), 1)

    gain = _FULL_SUN_ASPHALT_GAIN_F * factor
    relief = min(_wind_mph(wind) * _WIND_RELIEF_PER_MPH, _MAX_WIND_RELIEF_F)
    return round(float(air_temp_f) + max(gain - relief, 0.0), 1)


# Canine heat-risk banding.
#
# The temperature-plus-humidity sum is a rule of thumb circulated in working-dog
# and canine-sport communities, not a validated index, and it is labelled as such
# wherever it surfaces. An absolute-temperature guard sits alongside it because
# the sum alone lets a very dry, very hot afternoon score deceptively low.
_RISK_SUM_CAUTION = 120.0
_RISK_SUM_DANGER = 150.0
_RISK_TEMP_CAUTION_F = 82.0
_RISK_TEMP_DANGER_F = 90.0


def canine_heat_risk(air_temp_f: float | None, humidity_percent: float | None) -> dict[str, Any]:
    """Coarse risk band for a dog outdoors. Guidance, not a measurement."""
    if air_temp_f is None:
        return {"level": "unknown", "sum": None, "basis": "no temperature reading"}

    temp = float(air_temp_f)
    if humidity_percent is None:
        total = None
        level = (
            "danger" if temp >= _RISK_TEMP_DANGER_F
            else "caution" if temp >= _RISK_TEMP_CAUTION_F
            else "ok"
        )
        return {"level": level, "sum": None, "basis": "temperature only; humidity unavailable"}

    total = round(temp + float(humidity_percent), 1)
    if total >= _RISK_SUM_DANGER or temp >= _RISK_TEMP_DANGER_F:
        level = "danger"
    elif total >= _RISK_SUM_CAUTION or temp >= _RISK_TEMP_CAUTION_F:
        level = "caution"
    else:
        level = "ok"

    return {
        "level": level,
        "sum": total,
        "basis": "temperature + relative humidity, rule of thumb",
    }


def annotate_hour(row: dict[str, Any], lat: float | None = None, lon: float | None = None) -> dict[str, Any]:
    """Attach derived outdoor values to one hourly row, in place."""
    temp = row.get("temp_f")

    elevation = None
    if lat is not None and lon is not None and row.get("start_time"):
        try:
            when = datetime.fromisoformat(str(row["start_time"]))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            elevation = solar_elevation_deg(when, lat, lon)
        except (ValueError, TypeError):
            elevation = None
    row["sun_elevation_deg"] = elevation

    row["surface_temp_f"] = estimate_surface_temp_f(
        temp,
        short_forecast=row.get("short_forecast"),
        wind=row.get("wind_speed"),
        is_daytime=bool(row.get("is_daytime", True)),
        sun_elevation_deg=elevation,
    )
    row["canine_risk"] = canine_heat_risk(temp, row.get("humidity"))["level"]
    return row
