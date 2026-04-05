"""Astronomical calculations for sunrise/sunset and moon phase."""

from __future__ import annotations

import math
from datetime import date, datetime, time as dtime, timezone
from zoneinfo import ZoneInfo


_SYNODIC_MONTH_DAYS = 29.53058867
_KNOWN_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)


def _normalize_deg(value: float) -> float:
    return value % 360.0


def _normalize_hours(value: float) -> float:
    value %= 24.0
    if value < 0:
        value += 24.0
    return value


def _sun_event_utc(day: date, lat: float, lon: float, is_sunrise: bool, zenith: float = 90.833) -> datetime | None:
    n = day.timetuple().tm_yday
    lng_hour = lon / 15.0
    t = n + ((6 - lng_hour) / 24.0) if is_sunrise else n + ((18 - lng_hour) / 24.0)

    m = (0.9856 * t) - 3.289
    l = _normalize_deg(m + (1.916 * math.sin(math.radians(m))) + (0.020 * math.sin(math.radians(2 * m))) + 282.634)

    ra = math.degrees(math.atan(0.91764 * math.tan(math.radians(l))))
    ra = _normalize_deg(ra)

    l_quadrant = math.floor(l / 90.0) * 90.0
    ra_quadrant = math.floor(ra / 90.0) * 90.0
    ra = (ra + (l_quadrant - ra_quadrant)) / 15.0

    sin_dec = 0.39782 * math.sin(math.radians(l))
    cos_dec = math.cos(math.asin(sin_dec))

    cos_h = (math.cos(math.radians(zenith)) - (sin_dec * math.sin(math.radians(lat)))) / (
        cos_dec * math.cos(math.radians(lat))
    )

    if cos_h > 1 or cos_h < -1:
        return None

    h = 360.0 - math.degrees(math.acos(cos_h)) if is_sunrise else math.degrees(math.acos(cos_h))
    h /= 15.0

    local_t = h + ra - (0.06571 * t) - 6.622
    utc_hour = _normalize_hours(local_t - lng_hour)

    hour = int(utc_hour)
    minute = int((utc_hour - hour) * 60)
    second = int(round((((utc_hour - hour) * 60) - minute) * 60))
    if second == 60:
        second = 0
        minute += 1
    if minute == 60:
        minute = 0
        hour = (hour + 1) % 24

    return datetime.combine(day, dtime(hour=hour, minute=minute, second=second), tzinfo=timezone.utc)


def _moon_phase(now_utc: datetime) -> tuple[str, float, float]:
    days = (now_utc - _KNOWN_NEW_MOON).total_seconds() / 86400.0
    phase = (days % _SYNODIC_MONTH_DAYS) / _SYNODIC_MONTH_DAYS
    illumination = (1.0 - math.cos(2.0 * math.pi * phase)) / 2.0
    pct = round(illumination * 100.0, 1)

    if phase < 0.03 or phase >= 0.97:
        name = "New Moon"
    elif phase < 0.22:
        name = "Waxing Crescent"
    elif phase < 0.28:
        name = "First Quarter"
    elif phase < 0.47:
        name = "Waxing Gibbous"
    elif phase < 0.53:
        name = "Full Moon"
    elif phase < 0.72:
        name = "Waning Gibbous"
    elif phase < 0.78:
        name = "Last Quarter"
    else:
        name = "Waning Crescent"

    return name, pct, round(phase, 4)


def compute_astro(lat: float, lon: float, timezone_name: str, now_utc: datetime | None = None) -> dict[str, object]:
    tz = ZoneInfo(timezone_name)
    ref = now_utc.astimezone(timezone.utc) if now_utc else datetime.now(timezone.utc)
    local_day = ref.astimezone(tz).date()

    sunrise_utc = _sun_event_utc(local_day, lat, lon, is_sunrise=True, zenith=90.833)
    sunset_utc = _sun_event_utc(local_day, lat, lon, is_sunrise=False, zenith=90.833)

    golden_start_utc = _sun_event_utc(local_day, lat, lon, is_sunrise=True, zenith=94.0)
    golden_end_utc = _sun_event_utc(local_day, lat, lon, is_sunrise=False, zenith=94.0)

    solar_noon_utc = None
    if sunrise_utc is not None and sunset_utc is not None:
        solar_noon_utc = sunrise_utc + (sunset_utc - sunrise_utc) / 2

    moon_name, moon_illum, moon_phase_fraction = _moon_phase(ref)

    def _iso_local(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(tz).isoformat()

    return {
        "source": "local-astro",
        "timezone": timezone_name,
        "day": str(local_day),
        "sunrise": _iso_local(sunrise_utc),
        "sunset": _iso_local(sunset_utc),
        "solar_noon": _iso_local(solar_noon_utc),
        "golden_hour_start": _iso_local(golden_start_utc),
        "golden_hour_end": _iso_local(golden_end_utc),
        "moon_phase": moon_name,
        "moon_illumination": moon_illum,
        "moon_phase_fraction": moon_phase_fraction,
    }
