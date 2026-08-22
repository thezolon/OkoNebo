"""Local storm activity heuristic.

This replaces a client-side version that could not see the weather. It scored
three inputs -- NWS alert severities, wind gust, and barometric pressure -- and
on a morning with a squall line directly overhead it reported "Storm: Low",
because there was no warning issued for the point, the station reported no gust,
and the pressure term was structurally dead: a missing reading fell through
`|| 99`, a sentinel no real barometer can go below, so the pressure branch could
never fire on hardware that does not publish sea-level pressure.

Nothing about precipitation, radar, or the observed conditions text reached it,
even though the dashboard was displaying "Thunderstorms and Rain" two lines
above the badge.

What this is: a coarse, explainable summary of *local* storm activity, built
from readings the application actually has. What it is not: a forecast product,
and not anything the National Weather Service publishes. Every result carries
the reasons that produced it so the number can be argued with rather than
trusted blindly -- the previous version offered no explanation anywhere in the
product, which is precisely how it kept a straight face while being wrong.

Alerts are counted only when they affect a monitored location. A viewport sweep
can return advisories hundreds of miles away, and those say nothing about
whether it is storming here.
"""

from __future__ import annotations

import re
from typing import Any

# Severity weights for alerts affecting a monitored location.
_ALERT_WEIGHTS = {
    "extreme": 50,
    "severe": 30,
    "moderate": 15,
    "minor": 8,
    "unknown": 4,
}

# Observed-conditions text, strongest match first. This is the signal the old
# version ignored while the app displayed it on screen.
_CONDITION_SIGNALS: tuple[tuple[re.Pattern[str], int, str], ...] = (
    (re.compile(r"tornado|funnel", re.I), 70, "tornado reported in observed conditions"),
    (re.compile(r"hail", re.I), 45, "hail in observed conditions"),
    (re.compile(r"squall|severe thunderstorm", re.I), 45, "severe thunderstorm observed"),
    (re.compile(r"thunderstorm|t-?storm|lightning", re.I), 30, "thunderstorms observed"),
    (re.compile(r"freezing rain|ice storm|blizzard", re.I), 35, "winter storm conditions observed"),
    (re.compile(r"heavy rain|downpour", re.I), 18, "heavy rain observed"),
    (re.compile(r"rain|shower|drizzle", re.I), 10, "rain observed"),
    (re.compile(r"snow|sleet", re.I), 12, "frozen precipitation observed"),
)

_BANDS = (
    (80, "extreme", "Extreme"),
    (55, "severe", "Severe"),
    (32, "elevated", "Elevated"),
    (15, "guarded", "Guarded"),
)

_LEVEL_ORDER = ("low", "guarded", "elevated", "severe", "extreme")
_LEVEL_LABELS = {
    "low": "Low",
    "guarded": "Guarded",
    "elevated": "Elevated",
    "severe": "Severe",
    "extreme": "Extreme",
}

# Some conditions must not be reportable as anything mild, whatever the
# arithmetic says. An Extreme-severity warning over a monitored location scored
# 50 under pure summation, which landed in "Elevated" -- a tornado warning
# displayed as elevated is the same failure this module exists to correct. These
# are floors, not additions: they raise a result, never lower it.
_ALERT_SEVERITY_FLOORS = {"extreme": "extreme", "severe": "severe"}
_OBSERVED_TORNADO_FLOOR = "severe"


def _raise_to(level: str, floor: str) -> str:
    return floor if _LEVEL_ORDER.index(floor) > _LEVEL_ORDER.index(level) else level


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _affects_monitored_location(alert: dict[str, Any]) -> bool:
    """Viewport sweeps tag alerts with pseudo-locations such as 'Viewport SW'."""
    locations = alert.get("monitored_locations")
    if not isinstance(locations, list):
        # Point queries carry no location tags; those are already local.
        return True
    if not locations:
        return True
    return any(not str(name).lower().startswith("viewport") for name in locations)


def _severity_class(severity: Any) -> str:
    value = str(severity or "").strip().lower()
    return value if value in _ALERT_WEIGHTS else "unknown"


def compute_storm_index(
    current: dict[str, Any] | None = None,
    alerts: list[dict[str, Any]] | None = None,
    hourly: list[dict[str, Any]] | None = None,
    pws: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score local storm activity and explain the score."""
    score = 0
    reasons: list[str] = []
    current = current or {}

    # 1. Alerts, but only those affecting a monitored location.
    floor = "low"
    local_alerts = [a for a in (alerts or []) if _affects_monitored_location(a)]
    for alert in local_alerts:
        severity = _severity_class(alert.get("severity"))
        score += _ALERT_WEIGHTS[severity]
        if severity in _ALERT_SEVERITY_FLOORS:
            floor = _raise_to(floor, _ALERT_SEVERITY_FLOORS[severity])
        event = str(alert.get("event") or "alert").strip()
        reasons.append(f"{event} in effect")

    # 2. What the station is actually reporting right now. The old version never
    #    looked at this, which is how a squall line overhead scored zero.
    description = str(current.get("description") or current.get("short_forecast") or "")
    for pattern, weight, reason in _CONDITION_SIGNALS:
        if pattern.search(description):
            score += weight
            reasons.append(reason)
            if "tornado" in reason:
                floor = _raise_to(floor, _OBSERVED_TORNADO_FLOOR)
            break

    # 3. Imminent precipitation from the forecast's next few hours.
    upcoming = [h for h in (hourly or [])[:3]]
    pops = [p for p in (_to_float(h.get("precip_percent")) for h in upcoming) if p is not None]
    if pops:
        peak = max(pops)
        if peak >= 70:
            score += 15
            reasons.append(f"{int(peak)}% precipitation chance within 3 hours")
        elif peak >= 40:
            score += 8
            reasons.append(f"{int(peak)}% precipitation chance within 3 hours")

    # 4. Gusts. Only a reported gust counts. The old version fell back to
    #    sustained wind and scored it as though it were a gust.
    gusts = [_to_float(current.get("wind_gust_mph"))]
    for station in (pws or {}).get("stations", []) or []:
        gusts.append(_to_float(station.get("wind_gust_mph")))
    reported = [g for g in gusts if g is not None]
    if reported:
        peak_gust = max(reported)
        for threshold, weight in ((45, 35), (35, 25), (25, 15), (15, 8)):
            if peak_gust >= threshold:
                score += weight
                reasons.append(f"gusts to {int(peak_gust)} mph")
                break

    # 5. Pressure. Absent readings contribute nothing and say so, rather than
    #    being replaced by a sentinel that silently disables the whole branch.
    pressures = [_to_float(current.get("pressure_inhg"))]
    for station in (pws or {}).get("stations", []) or []:
        pressures.append(_to_float(station.get("pressure_inhg")))
    # A plausible sea-level pressure; anything outside it is a bad reading.
    valid = [p for p in pressures if p is not None and 25.0 <= p <= 32.0]
    if valid:
        lowest = min(valid)
        if lowest < 29.6:
            score += 20
            reasons.append(f"low pressure {lowest:.2f} inHg")
        elif lowest < 29.8:
            score += 12
            reasons.append(f"falling pressure {lowest:.2f} inHg")

    level = "low"
    for threshold, band_level, _band_label in _BANDS:
        if score >= threshold:
            level = band_level
            break
    level = _raise_to(level, floor)
    label = _LEVEL_LABELS[level]

    if not reasons:
        reasons.append("no storm signals in current readings")

    return {
        "score": score,
        "level": level,
        "label": label,
        "reasons": reasons,
        # Stated in the payload so no consumer mistakes this for an official
        # product. The UI repeats it in the badge tooltip.
        "basis": "local heuristic from observed conditions, alerts, forecast and station readings; not an NWS product",
    }
