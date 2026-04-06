"""
weather_client.py — Async weather.gov + OpenWeather API client with hybrid TTL caching.
Uses in-memory cache for speed + SQLite for persistence across restarts with adaptive TTLs.
"""

import asyncio
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

import httpx

from . import cache_db

BASE = "https://api.weather.gov"

_UPSTREAM_STATS_STARTED_AT = int(time.time())
_UPSTREAM_CALL_STATS: dict[str, int] = {
    "nws": 0,
    "owm": 0,
    "weatherapi": 0,
    "tomorrow": 0,
    "visualcrossing": 0,
    "meteomatics": 0,
    "aviationweather": 0,
    "noaa_tides": 0,
    "pws_current": 0,
    "pws_history": 0,
}
_RETRY_RUNTIME_STATS: dict[str, dict[str, int]] = {}
_CACHE_RUNTIME_STATS: dict[str, int] = {
    "memory_hit": 0,
    "sqlite_hit": 0,
    "miss": 0,
    "set": 0,
    "stale_hit": 0,
    "singleflight_wait": 0,
    "refresh": 0,
    "refresh_error": 0,
}

PROVIDER_PULL_CYCLE_DEFAULTS: dict[str, int] = {
    "nws": 300,
    "openweather": 600,
    "pws": 120,
    "tomorrow": 300,
    "meteomatics": 300,
    "weatherapi": 300,
    "visualcrossing": 300,
    "aviationweather": 600,
    "noaa_tides": 1800,
}

PROVIDER_PULL_CYCLE_BOUNDS: dict[str, int] = {
    "min_seconds": 60,
    "max_seconds": 86400,
}

PROVIDER_PULL_CYCLE_CACHE_TYPES: dict[str, list[str]] = {
    "nws": ["current_nws", "forecast_nws", "hourly_nws", "alerts_nws"],
    "openweather": ["owm_onecall"],
    "pws": ["pws_current", "pws_trend"],
    "tomorrow": ["current_tomorrow", "forecast_tomorrow", "hourly_tomorrow"],
    "meteomatics": ["current_meteomatics"],
    "weatherapi": ["current_weatherapi", "forecast_weatherapi", "hourly_weatherapi"],
    "visualcrossing": ["current_visualcrossing", "forecast_visualcrossing", "hourly_visualcrossing"],
    "aviationweather": ["current_aviationweather"],
    "noaa_tides": ["tides_noaa"],
}

_ACTIVE_PROVIDER_PULL_CYCLES = dict(PROVIDER_PULL_CYCLE_DEFAULTS)


def _bump_upstream_call(name: str) -> None:
    _UPSTREAM_CALL_STATS[name] = _UPSTREAM_CALL_STATS.get(name, 0) + 1


def record_upstream_call(name: str) -> None:
    """Public helper for other modules (for example, tile proxy calls)."""
    _bump_upstream_call(name)


def get_upstream_call_stats() -> dict[str, Any]:
    counts = dict(_UPSTREAM_CALL_STATS)
    return {
        "started_at": _UPSTREAM_STATS_STARTED_AT,
        "uptime_seconds": int(time.time()) - _UPSTREAM_STATS_STARTED_AT,
        "counts": counts,
        "retries": {name: dict(values) for name, values in _RETRY_RUNTIME_STATS.items()},
        "cache_runtime": dict(_CACHE_RUNTIME_STATS),
        "total": sum(counts.values()),
    }


def reset_runtime_telemetry() -> None:
    """Testing helper: reset transient runtime counters."""
    for key in list(_UPSTREAM_CALL_STATS.keys()):
        _UPSTREAM_CALL_STATS[key] = 0
    _RETRY_RUNTIME_STATS.clear()
    for key in list(_CACHE_RUNTIME_STATS.keys()):
        _CACHE_RUNTIME_STATS[key] = 0


def _mark_retry_stat(upstream_name: str, key: str) -> None:
    bucket = _RETRY_RUNTIME_STATS.setdefault(upstream_name, {"attempted": 0, "exhausted": 0})
    bucket[key] = bucket.get(key, 0) + 1


def get_provider_pull_cycle_defaults() -> dict[str, int]:
    return dict(PROVIDER_PULL_CYCLE_DEFAULTS)


def get_provider_pull_cycle_bounds() -> dict[str, int]:
    return dict(PROVIDER_PULL_CYCLE_BOUNDS)


def get_provider_pull_cycles() -> dict[str, int]:
    return dict(_ACTIVE_PROVIDER_PULL_CYCLES)


def _sanitize_pull_cycle_seconds(value: Any, fallback: int) -> int:
    try:
        n = int(value)
    except Exception:
        n = int(fallback)
    n = max(PROVIDER_PULL_CYCLE_BOUNDS["min_seconds"], n)
    n = min(PROVIDER_PULL_CYCLE_BOUNDS["max_seconds"], n)
    return n

# ---------------------------------------------------------------------------
# Hybrid cache: async-safe in-memory + SQLite persistence
# ---------------------------------------------------------------------------

class _Entry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, ttl: float):
        self.value = value
        self.expires_at = time.monotonic() + ttl


class HybridTTLCache:
    """
    Hybrid cache that prioritizes in-memory speed with SQLite fallback + persistence.
    - Memory cache: Fast, expires via monotonic timer (in-process only)
    - SQLite cache: Survives app restarts, adaptive TTLs based on threat level
    """

    def __init__(self, db_path: str = "cache.db"):
        self._store: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()
        self._refresh_locks: dict[str, asyncio.Lock] = {}
        self._refresh_locks_guard = asyncio.Lock()
        self._db = cache_db.WeatherCache(db_path)
        self._threat_level = "default"
        self._current_alerts: list[dict] = []

    def set_cache_type_ttl_overrides(self, overrides: dict[str, int]) -> None:
        self._db.set_ttl_overrides(overrides)

    def effective_ttl(self, cache_type: str, fallback_ttl: int) -> int:
        return self._db.resolve_ttl(cache_type, self._threat_level, fallback_ttl)

    async def get_refresh_lock(self, key: str) -> asyncio.Lock:
        """Return a stable per-key lock used to coalesce cache refreshes."""
        async with self._refresh_locks_guard:
            lock = self._refresh_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._refresh_locks[key] = lock
            return lock

    async def get(self, key: str, cache_type: str = "default") -> Optional[Any]:
        """
        Try to get from memory cache first, then SQLite (respecting adaptive TTL).
        """
        async with self._lock:
            entry = self._store.get(key)
            if entry and time.monotonic() < entry.expires_at:
                _CACHE_RUNTIME_STATS["memory_hit"] += 1
                return entry.value

        # Not in memory or expired; try SQLite
        try:
            db_value = self._db.get(key, cache_type=cache_type, threat_level=self._threat_level)
            if db_value is not None:
                # Cache it in memory for fast subsequent access
                async with self._lock:
                    self._store[key] = _Entry(db_value, self.effective_ttl(cache_type, 300))
                _CACHE_RUNTIME_STATS["sqlite_hit"] += 1
                return db_value
        except Exception:
            pass  # SQLite read error; continue to stale fallback

        _CACHE_RUNTIME_STATS["miss"] += 1
        return None

    async def get_stale(self, key: str) -> Optional[Any]:
        """
        Get cached value regardless of expiration (for fallback).
        Checks memory first, then SQLite.
        """
        async with self._lock:
            entry = self._store.get(key)
            if entry:
                _CACHE_RUNTIME_STATS["stale_hit"] += 1
                return entry.value

        try:
            stale = self._db.get(key, threat_level="default")
            if stale is not None:
                _CACHE_RUNTIME_STATS["stale_hit"] += 1
            return stale
        except Exception:
            return None

    async def set(self, key: str, value: Any, ttl: float, cache_type: str = "default"):
        """
        Store to both memory and SQLite.
        """
        async with self._lock:
            self._store[key] = _Entry(value, ttl)
        _CACHE_RUNTIME_STATS["set"] += 1

        try:
            self._db.set(key, value, cache_type=cache_type, threat_level="default")
        except Exception:
            pass  # Non-fatal; memory cache is still valid

    def set_threat_level(self, alerts: list[dict]):
        """
        Update threat level based on current alerts.
        Affects how long we wait before considering SQLite data stale.
        """
        self._current_alerts = alerts
        self._threat_level = self._db.get_threat_level(alerts)

    def get_stats(self) -> dict:
        """Get cache statistics."""
        return self._db.stats()


_cache = HybridTTLCache()


def set_provider_pull_cycles(cycles: dict[str, Any] | None) -> dict[str, int]:
    global _ACTIVE_PROVIDER_PULL_CYCLES

    merged = dict(PROVIDER_PULL_CYCLE_DEFAULTS)
    incoming = cycles or {}
    for provider, default_seconds in PROVIDER_PULL_CYCLE_DEFAULTS.items():
        merged[provider] = _sanitize_pull_cycle_seconds(incoming.get(provider), default_seconds)

    cache_overrides: dict[str, int] = {}
    for provider, seconds in merged.items():
        for cache_type in PROVIDER_PULL_CYCLE_CACHE_TYPES.get(provider, []):
            cache_overrides[cache_type] = int(seconds)

    _ACTIVE_PROVIDER_PULL_CYCLES = merged
    _cache.set_cache_type_ttl_overrides(cache_overrides)
    return dict(_ACTIVE_PROVIDER_PULL_CYCLES)


set_provider_pull_cycles(None)

# ---------------------------------------------------------------------------
# NWS HTTP helpers
# ---------------------------------------------------------------------------

_HTTP_CLIENTS: dict[str, httpx.AsyncClient] = {}


def _get_http_client(client_key: str, headers: dict[str, str] | None = None) -> httpx.AsyncClient:
    client = _HTTP_CLIENTS.get(client_key)
    if client is not None:
        return client

    client = httpx.AsyncClient(
        headers=headers,
        timeout=15,
        follow_redirects=True,
        limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
    )
    _HTTP_CLIENTS[client_key] = client
    return client


async def close_http_clients() -> None:
    for client in list(_HTTP_CLIENTS.values()):
        try:
            await client.aclose()
        except Exception:
            continue
    _HTTP_CLIENTS.clear()


def _retry_sleep_seconds(exc: Exception, attempt: int) -> float:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None and exc.response.status_code == 429:
        retry_after = (exc.response.headers.get("Retry-After") or "").strip()
        if retry_after:
            try:
                # Respect upstream rate-limit hints with a safety cap.
                return min(max(float(retry_after), 0.0), 60.0)
            except ValueError:
                pass
    return 0.4 * attempt + random.uniform(0.0, 0.3)


async def _http_get_with_retry(
    *,
    url: str,
    upstream_name: str,
    client_key: str,
    retries: int,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    retryable_status = {429, 500, 502, 503, 504}
    last_exc: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            client = _get_http_client(client_key, headers=headers)
            _bump_upstream_call(upstream_name)
            resp = await client.get(url, params=params)
            if resp.status_code in retryable_status:
                raise httpx.HTTPStatusError(
                    f"{upstream_name} upstream status: {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            resp.raise_for_status()
            return resp.json()
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            is_retryable_http = (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response is not None
                and exc.response.status_code in retryable_status
            )
            is_retryable = isinstance(exc, (httpx.TimeoutException, httpx.TransportError)) or is_retryable_http
            if attempt < retries and is_retryable:
                _mark_retry_stat(upstream_name, "attempted")
                await asyncio.sleep(_retry_sleep_seconds(exc, attempt))
                continue
            if is_retryable:
                _mark_retry_stat(upstream_name, "exhausted")
            raise

    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"{upstream_name} request failed unexpectedly")


async def _get(user_agent: str, url: str, retries: int = 3) -> dict:
    return await _http_get_with_retry(
        url=url,
        upstream_name="nws",
        client_key=f"nws:{user_agent}",
        retries=retries,
        headers={"User-Agent": user_agent, "Accept": "application/geo+json"},
    )


async def _get_or_refresh_shared(
    key: str,
    cache_type: str,
    ttl: float,
    producer: Callable[[], Awaitable[Any]],
) -> Any:
    """Single-flight cache refresh: one upstream fetch per key across concurrent requests."""
    cached = await _cache.get(key, cache_type=cache_type)
    if cached is not None:
        return cached

    refresh_lock = await _cache.get_refresh_lock(key)
    if refresh_lock.locked():
        _CACHE_RUNTIME_STATS["singleflight_wait"] += 1
    async with refresh_lock:
        cached = await _cache.get(key, cache_type=cache_type)
        if cached is not None:
            return cached

        try:
            _CACHE_RUNTIME_STATS["refresh"] += 1
            value = await producer()
            effective_ttl = _cache.effective_ttl(cache_type, int(ttl))
            await _cache.set(key, value, ttl=effective_ttl, cache_type=cache_type)
            return value
        except Exception:
            _CACHE_RUNTIME_STATS["refresh_error"] += 1
            stale = await _cache.get_stale(key)
            if stale is not None:
                return stale
            raise


async def get_current_history(lat: float, lon: float, hours: int = 6) -> dict[str, Any]:
    safe_hours = max(1, min(int(hours), 24))
    keys = {
        f"current:{lat},{lon}": "nws",
        f"weatherapi-current:{lat},{lon}": "weatherapi",
        f"tomorrow-current:{lat},{lon}": "tomorrow",
        f"visualcrossing-current:{lat},{lon}": "visualcrossing",
        f"meteomatics-current:{lat},{lon}": "meteomatics",
    }
    points = _cache._db.get_history(list(keys.keys()), hours=safe_hours)

    normalized: list[dict[str, Any]] = []
    for item in points:
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        key = str(item.get("key") or "")
        normalized.append(
            {
                "timestamp": item.get("timestamp"),
                "source": keys.get(key) or str(item.get("cache_type") or "current"),
                "temp_f": data.get("temp_f"),
                "feels_like_f": data.get("feels_like_f"),
                "humidity": data.get("humidity"),
                "pressure_inhg": data.get("pressure_inhg"),
                "wind_speed_mph": data.get("wind_speed_mph"),
                "wind_direction": data.get("wind_direction"),
                "wind_gust_mph": data.get("wind_gust_mph"),
                "dewpoint_f": data.get("dewpoint_f"),
                "visibility_miles": data.get("visibility_miles"),
                "description": data.get("description"),
                "station": data.get("station"),
            }
        )

    return {
        "hours": safe_hours,
        "points": normalized,
        "updated_at": time.time(),
    }


# ---------------------------------------------------------------------------
# Point resolution (cached 24 h)
# ---------------------------------------------------------------------------

async def _resolve_point(lat: float, lon: float, user_agent: str) -> dict:
    key = f"point:{lat},{lon}"
    async def _producer() -> dict:
        data = await _get(user_agent, f"{BASE}/points/{lat},{lon}")
        props = data["properties"]
        station_data = await _get(user_agent, props["observationStations"])
        station_id = station_data["features"][0]["properties"]["stationIdentifier"]
        station_url = f"{BASE}/stations/{station_id}/observations/latest"
        return {
            "forecast_url": props["forecast"],
            "forecast_hourly_url": props["forecastHourly"],
            "station_url": station_url,
            "grid_id": props["gridId"],
            "grid_x": props["gridX"],
            "grid_y": props["gridY"],
        }

    return await _get_or_refresh_shared(key, cache_type="point_nws", ttl=86400, producer=_producer)


# ---------------------------------------------------------------------------
# NWS public functions
# ---------------------------------------------------------------------------

async def get_current(lat: float, lon: float, user_agent: str) -> dict:
    key = f"current:{lat},{lon}"

    async def _producer() -> dict:
        point = await _resolve_point(lat, lon, user_agent)
        raw = await _get(user_agent, point["station_url"])
        props = raw["properties"]

        def _val(obj):
            return obj.get("value") if isinstance(obj, dict) else None

        def _c_to_f(c):
            return round(c * 9 / 5 + 32, 1) if c is not None else None

        temp_c    = _val(props.get("temperature"))
        dewpoint_c = _val(props.get("dewpoint"))
        feels_c   = _val(props.get("windChill")) or _val(props.get("heatIndex")) or temp_c

        return {
            "station":        props.get("station", "").split("/")[-1],
            "timestamp":      props.get("timestamp"),
            "description":    props.get("textDescription"),
            "icon":           props.get("icon"),
            "temp_f":         _c_to_f(temp_c),
            "feels_like_f":   _c_to_f(feels_c),
            "dewpoint_f":     _c_to_f(dewpoint_c),
            "humidity":       _val(props.get("relativeHumidity")),
            "wind_speed_mph": round(_val(props.get("windSpeed")) * 0.621371, 1)
                              if _val(props.get("windSpeed")) is not None else None,
            "wind_direction": _val(props.get("windDirection")),
            "wind_gust_mph":  round(_val(props.get("windGust")) * 0.621371, 1)
                              if _val(props.get("windGust")) is not None else None,
            "pressure_inhg":  round(_val(props.get("seaLevelPressure")) / 3386.39, 2)
                              if _val(props.get("seaLevelPressure")) is not None else None,
            "visibility_miles": round(_val(props.get("visibility")) * 0.000621371, 1)
                                if _val(props.get("visibility")) is not None else None,
            "cloud_layers": [
                {
                    "amount":   cl.get("amount"),
                    "base_ft":  round(cl["base"]["value"] * 3.28084)
                                if cl.get("base", {}).get("value") is not None else None,
                }
                for cl in props.get("cloudLayers", [])
            ],
        }

    return await _get_or_refresh_shared(key, cache_type="current_nws", ttl=300, producer=_producer)


async def get_forecast(lat: float, lon: float, user_agent: str) -> list[dict]:
    key = f"forecast:{lat},{lon}"

    async def _producer() -> list[dict]:
        point = await _resolve_point(lat, lon, user_agent)
        raw = await _get(user_agent, point["forecast_url"])
        periods = raw["properties"]["periods"]
        return [
            {
                "number":          p["number"],
                "name":            p["name"],
                "start_time":      p["startTime"],
                "end_time":        p["endTime"],
                "is_daytime":      p["isDaytime"],
                "temp_f":          p["temperature"],
                "temp_trend":      p.get("temperatureTrend"),
                "wind_speed":      p["windSpeed"],
                "wind_direction":  p["windDirection"],
                "icon":            p["icon"],
                "short_forecast":  p["shortForecast"],
                "detailed_forecast": p["detailedForecast"],
                "precip_percent":  p.get("probabilityOfPrecipitation", {}).get("value"),
            }
            for p in periods
        ]

    return await _get_or_refresh_shared(key, cache_type="forecast_nws", ttl=900, producer=_producer)


async def get_hourly(lat: float, lon: float, user_agent: str) -> list[dict]:
    key = f"hourly:{lat},{lon}"

    async def _producer() -> list[dict]:
        point = await _resolve_point(lat, lon, user_agent)
        raw = await _get(user_agent, point["forecast_hourly_url"])
        periods = raw["properties"]["periods"][:48]
        return [
            {
                "start_time":     p["startTime"],
                "temp_f":         p["temperature"],
                "wind_speed":     p["windSpeed"],
                "wind_direction": p["windDirection"],
                "short_forecast": p["shortForecast"],
                "icon":           p["icon"],
                "precip_percent": p.get("probabilityOfPrecipitation", {}).get("value"),
            }
            for p in periods
        ]

    return await _get_or_refresh_shared(key, cache_type="hourly_nws", ttl=900, producer=_producer)


async def get_alerts(lat: float, lon: float, user_agent: str) -> list[dict]:
    key = f"alerts:{lat},{lon}"

    async def _producer() -> list[dict]:
        raw = await _get(user_agent, f"{BASE}/alerts/active?point={lat},{lon}")
        return [
            {
                "id":            f["id"],
                "event":         f["properties"]["event"],
                "severity":      f["properties"]["severity"],
                "urgency":       f["properties"]["urgency"],
                "certainty":     f["properties"]["certainty"],
                "headline":      f["properties"].get("headline"),
                "description":   f["properties"].get("description"),
                "instruction":   f["properties"].get("instruction"),
                "sent":          f["properties"]["sent"],
                "effective":     f["properties"]["effective"],
                "expires":       f["properties"].get("expires"),
                "ends":          f["properties"].get("ends"),
                "areas_affected": f["properties"].get("areaDesc"),
                "geometry":      f.get("geometry"),
                "geocode":       f["properties"].get("geocode"),
            }
            for f in raw.get("features", [])
        ]

    return await _get_or_refresh_shared(key, cache_type="alerts_nws", ttl=300, producer=_producer)


async def get_alerts_multi(locations: list[dict], user_agent: str) -> list[dict]:
    normalized_locations = [
        {
            "lat": float(loc["lat"]),
            "lon": float(loc["lon"]),
            "label": loc.get("label") or f"{loc['lat']},{loc['lon']}",
        }
        for loc in locations
    ]
    cache_key = "alerts-multi:" + "|".join(
        f"{loc['label']}@{loc['lat']:.4f},{loc['lon']:.4f}" for loc in normalized_locations
    )
    async def _producer() -> list[dict]:
        point_alerts = await asyncio.gather(
            *(get_alerts(loc["lat"], loc["lon"], user_agent) for loc in normalized_locations)
        )

        merged: dict[str, dict] = {}
        for loc, alerts in zip(normalized_locations, point_alerts):
            for alert in alerts:
                if alert["id"] not in merged:
                    merged[alert["id"]] = {
                        **alert,
                        "monitored_locations": [loc["label"]],
                    }
                elif loc["label"] not in merged[alert["id"]]["monitored_locations"]:
                    merged[alert["id"]]["monitored_locations"].append(loc["label"])

        result = sorted(
            merged.values(),
            key=lambda alert: alert.get("effective") or alert.get("sent") or "",
            reverse=True,
        )
        _cache.set_threat_level(result)
        return result

    return await _get_or_refresh_shared(cache_key, cache_type="alerts_nws", ttl=300, producer=_producer)


# ---------------------------------------------------------------------------
# OpenWeather One Call 3.0
# ---------------------------------------------------------------------------

OWM_BASE = "https://api.openweathermap.org/data/3.0"
OWM_AQI_BASE = "https://api.openweathermap.org/data/2.5"
PWS_BASE = "https://api.weather.com/v2/pws/observations/current"
PWS_HISTORY_BASE = "https://api.weather.com/v2/pws/observations/all/1day"
WEATHERAPI_BASE = "https://api.weatherapi.com/v1"
TOMORROW_BASE = "https://api.tomorrow.io/v4"
VISUALCROSSING_BASE = "https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline"

_TOMORROW_CODE_TEXT = {
    0: "Unknown",
    1000: "Clear",
    1100: "Mostly Clear",
    1101: "Partly Cloudy",
    1102: "Mostly Cloudy",
    1001: "Cloudy",
    2000: "Fog",
    2100: "Light Fog",
    4000: "Drizzle",
    4001: "Rain",
    4200: "Light Rain",
    4201: "Heavy Rain",
    5000: "Snow",
    5001: "Flurries",
    5100: "Light Snow",
    5101: "Heavy Snow",
    6000: "Freezing Drizzle",
    6001: "Freezing Rain",
    6200: "Light Freezing Rain",
    6201: "Heavy Freezing Rain",
    7000: "Ice Pellets",
    7101: "Heavy Ice Pellets",
    7102: "Light Ice Pellets",
    8000: "Thunderstorm",
}


async def _json_get_with_retry(url: str, params: dict[str, Any], upstream_name: str) -> dict[str, Any]:
    return await _http_get_with_retry(
        url=url,
        params=params,
        upstream_name=upstream_name,
        client_key=f"provider:{upstream_name}",
        retries=3,
    )


def _normalize_weatherapi_current(payload: dict[str, Any]) -> dict[str, Any]:
    location = payload.get("location", {}) if isinstance(payload.get("location", {}), dict) else {}
    current = payload.get("current", {}) if isinstance(payload.get("current", {}), dict) else {}
    condition = current.get("condition", {}) if isinstance(current.get("condition", {}), dict) else {}
    icon = str(condition.get("icon") or "")
    if icon.startswith("//"):
        icon = f"https:{icon}"

    return {
        "station": location.get("name") or "weatherapi",
        "timestamp": current.get("last_updated"),
        "description": condition.get("text"),
        "icon": icon or None,
        "temp_f": current.get("temp_f"),
        "feels_like_f": current.get("feelslike_f"),
        "dewpoint_f": current.get("dewpoint_f"),
        "humidity": current.get("humidity"),
        "wind_speed_mph": current.get("wind_mph"),
        "wind_direction": current.get("wind_dir") or current.get("wind_degree"),
        "wind_gust_mph": current.get("gust_mph"),
        "pressure_inhg": current.get("pressure_in"),
        "visibility_miles": current.get("vis_miles"),
        "cloud_layers": [],
    }


def _normalize_tomorrow_current(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data", {}) if isinstance(payload.get("data", {}), dict) else {}
    values = data.get("values", {}) if isinstance(data.get("values", {}), dict) else {}

    return {
        "station": "tomorrow.io",
        "timestamp": data.get("time"),
        "description": None,
        "icon": None,
        "temp_f": values.get("temperature"),
        "feels_like_f": values.get("temperatureApparent"),
        "dewpoint_f": values.get("dewPoint"),
        "humidity": values.get("humidity"),
        "wind_speed_mph": values.get("windSpeed"),
        "wind_direction": values.get("windDirection"),
        "wind_gust_mph": values.get("windGust"),
        "pressure_inhg": values.get("pressureSeaLevel"),
        "visibility_miles": values.get("visibility"),
        "cloud_layers": [],
    }


def _to_iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _weatherapi_icon(raw: str) -> str | None:
    icon = str(raw or "")
    if not icon:
        return None
    if icon.startswith("//"):
        return f"https:{icon}"
    return icon


def _tomorrow_text(code: Any) -> str:
    try:
        code_int = int(code)
    except Exception:
        return "Unknown"
    return _TOMORROW_CODE_TEXT.get(code_int, f"Weather code {code_int}")


def _vc_icon(icon: Any) -> str | None:
    value = str(icon or "").strip()
    return value or None


def _vc_to_iso_epoch(epoch: Any) -> str | None:
    try:
        return _to_iso(datetime.fromtimestamp(int(epoch), tz=timezone.utc))
    except Exception:
        return None


async def get_weatherapi_current(lat: float, lon: float, api_key: str) -> dict[str, Any]:
    if not api_key:
        raise ValueError("WeatherAPI key not configured")

    key = f"weatherapi-current:{lat},{lon}"

    async def _producer() -> dict[str, Any]:
        raw = await _json_get_with_retry(
            f"{WEATHERAPI_BASE}/current.json",
            {
                "key": api_key,
                "q": f"{lat},{lon}",
                "aqi": "no",
            },
            upstream_name="weatherapi",
        )
        return _normalize_weatherapi_current(raw)

    return await _get_or_refresh_shared(key, cache_type="current_weatherapi", ttl=300, producer=_producer)


async def get_weatherapi_hourly(lat: float, lon: float, api_key: str) -> list[dict[str, Any]]:
    if not api_key:
        raise ValueError("WeatherAPI key not configured")

    key = f"weatherapi-hourly:{lat},{lon}"

    async def _producer() -> list[dict[str, Any]]:
        raw = await _json_get_with_retry(
            f"{WEATHERAPI_BASE}/forecast.json",
            {
                "key": api_key,
                "q": f"{lat},{lon}",
                "days": 3,
                "aqi": "no",
                "alerts": "no",
            },
            upstream_name="weatherapi",
        )
        forecast = raw.get("forecast", {}) if isinstance(raw.get("forecast", {}), dict) else {}
        days = forecast.get("forecastday", []) if isinstance(forecast.get("forecastday", []), list) else []
        points: list[dict[str, Any]] = []
        now_utc = datetime.now(timezone.utc)

        for day in days:
            hours = day.get("hour", []) if isinstance(day.get("hour", []), list) else []
            for hour in hours:
                ts_raw = str(hour.get("time") or "")
                try:
                    ts = datetime.fromisoformat(ts_raw.replace(" ", "T")).replace(tzinfo=timezone.utc)
                except Exception:
                    ts = None
                if ts is not None and ts < now_utc - timedelta(hours=1):
                    continue

                condition = hour.get("condition", {}) if isinstance(hour.get("condition", {}), dict) else {}
                points.append(
                    {
                        "start_time": _to_iso(ts) if ts is not None else ts_raw,
                        "temp_f": hour.get("temp_f"),
                        "wind_speed": f"{hour.get('wind_mph', 0)} mph" if hour.get("wind_mph") is not None else None,
                        "wind_direction": hour.get("wind_dir") or hour.get("wind_degree"),
                        "short_forecast": condition.get("text"),
                        "icon": _weatherapi_icon(str(condition.get("icon") or "")),
                        "precip_percent": hour.get("chance_of_rain"),
                    }
                )

        points.sort(key=lambda p: str(p.get("start_time") or ""))
        return points[:48]

    return await _get_or_refresh_shared(key, cache_type="hourly_weatherapi", ttl=900, producer=_producer)


async def get_weatherapi_forecast(lat: float, lon: float, api_key: str) -> list[dict[str, Any]]:
    if not api_key:
        raise ValueError("WeatherAPI key not configured")

    key = f"weatherapi-forecast:{lat},{lon}"

    async def _producer() -> list[dict[str, Any]]:
        raw = await _json_get_with_retry(
            f"{WEATHERAPI_BASE}/forecast.json",
            {
                "key": api_key,
                "q": f"{lat},{lon}",
                "days": 7,
                "aqi": "no",
                "alerts": "no",
            },
            upstream_name="weatherapi",
        )
        forecast = raw.get("forecast", {}) if isinstance(raw.get("forecast", {}), dict) else {}
        days = forecast.get("forecastday", []) if isinstance(forecast.get("forecastday", []), list) else []
        periods: list[dict[str, Any]] = []
        number = 1

        for day in days:
            date_raw = str(day.get("date") or "")
            try:
                date_obj = datetime.fromisoformat(date_raw)
            except Exception:
                continue

            day_meta = day.get("day", {}) if isinstance(day.get("day", {}), dict) else {}
            day_condition = day_meta.get("condition", {}) if isinstance(day_meta.get("condition", {}), dict) else {}

            day_start = date_obj.replace(hour=7, minute=0, second=0)
            day_end = date_obj.replace(hour=19, minute=0, second=0)
            periods.append(
                {
                    "number": number,
                    "name": date_obj.strftime("%A"),
                    "start_time": _to_iso(day_start),
                    "end_time": _to_iso(day_end),
                    "is_daytime": True,
                    "temp_f": day_meta.get("maxtemp_f"),
                    "temp_trend": None,
                    "wind_speed": f"{day_meta.get('maxwind_mph', 0)} mph" if day_meta.get("maxwind_mph") is not None else None,
                    "wind_direction": None,
                    "icon": _weatherapi_icon(str(day_condition.get("icon") or "")),
                    "short_forecast": day_condition.get("text"),
                    "detailed_forecast": day_condition.get("text"),
                    "precip_percent": day_meta.get("daily_chance_of_rain"),
                }
            )
            number += 1

            night_start = date_obj.replace(hour=19, minute=0, second=0)
            night_end = (date_obj + timedelta(days=1)).replace(hour=7, minute=0, second=0)
            periods.append(
                {
                    "number": number,
                    "name": f"{date_obj.strftime('%A')} Night",
                    "start_time": _to_iso(night_start),
                    "end_time": _to_iso(night_end),
                    "is_daytime": False,
                    "temp_f": day_meta.get("mintemp_f"),
                    "temp_trend": None,
                    "wind_speed": f"{day_meta.get('maxwind_mph', 0)} mph" if day_meta.get("maxwind_mph") is not None else None,
                    "wind_direction": None,
                    "icon": _weatherapi_icon(str(day_condition.get("icon") or "")),
                    "short_forecast": day_condition.get("text"),
                    "detailed_forecast": day_condition.get("text"),
                    "precip_percent": day_meta.get("daily_chance_of_rain"),
                }
            )
            number += 1

        return periods

    return await _get_or_refresh_shared(key, cache_type="forecast_weatherapi", ttl=900, producer=_producer)


async def get_tomorrow_current(lat: float, lon: float, api_key: str) -> dict[str, Any]:
    if not api_key:
        raise ValueError("Tomorrow.io key not configured")

    key = f"tomorrow-current:{lat},{lon}"

    async def _producer() -> dict[str, Any]:
        raw = await _json_get_with_retry(
            f"{TOMORROW_BASE}/weather/realtime",
            {
                "apikey": api_key,
                "location": f"{lat},{lon}",
                "units": "imperial",
            },
            upstream_name="tomorrow",
        )
        return _normalize_tomorrow_current(raw)

    return await _get_or_refresh_shared(key, cache_type="current_tomorrow", ttl=300, producer=_producer)


async def get_tomorrow_hourly(lat: float, lon: float, api_key: str) -> list[dict[str, Any]]:
    if not api_key:
        raise ValueError("Tomorrow.io key not configured")

    key = f"tomorrow-hourly:{lat},{lon}"

    async def _producer() -> list[dict[str, Any]]:
        raw = await _json_get_with_retry(
            f"{TOMORROW_BASE}/timelines",
            {
                "apikey": api_key,
                "location": f"{lat},{lon}",
                "timesteps": "1h",
                "units": "imperial",
                "fields": "temperature,windSpeed,windDirection,precipitationProbability,weatherCode",
            },
            upstream_name="tomorrow",
        )
        data = raw.get("data", {}) if isinstance(raw.get("data", {}), dict) else {}
        timelines = data.get("timelines", []) if isinstance(data.get("timelines", []), list) else []
        timeline = timelines[0] if timelines else {}
        intervals = timeline.get("intervals", []) if isinstance(timeline.get("intervals", []), list) else []
        points: list[dict[str, Any]] = []

        for item in intervals[:48]:
            values = item.get("values", {}) if isinstance(item.get("values", {}), dict) else {}
            points.append(
                {
                    "start_time": item.get("startTime"),
                    "temp_f": values.get("temperature"),
                    "wind_speed": f"{values.get('windSpeed', 0)} mph" if values.get("windSpeed") is not None else None,
                    "wind_direction": values.get("windDirection"),
                    "short_forecast": _tomorrow_text(values.get("weatherCode")),
                    "icon": None,
                    "precip_percent": values.get("precipitationProbability"),
                }
            )

        return points

    return await _get_or_refresh_shared(key, cache_type="hourly_tomorrow", ttl=900, producer=_producer)


async def get_tomorrow_forecast(lat: float, lon: float, api_key: str) -> list[dict[str, Any]]:
    if not api_key:
        raise ValueError("Tomorrow.io key not configured")

    key = f"tomorrow-forecast:{lat},{lon}"

    async def _producer() -> list[dict[str, Any]]:
        raw = await _json_get_with_retry(
            f"{TOMORROW_BASE}/timelines",
            {
                "apikey": api_key,
                "location": f"{lat},{lon}",
                "timesteps": "1d",
                "units": "imperial",
                "fields": "temperatureMax,temperatureMin,windSpeedAvg,windDirectionAvg,precipitationProbabilityAvg,weatherCodeMax",
            },
            upstream_name="tomorrow",
        )
        data = raw.get("data", {}) if isinstance(raw.get("data", {}), dict) else {}
        timelines = data.get("timelines", []) if isinstance(data.get("timelines", []), list) else []
        timeline = timelines[0] if timelines else {}
        intervals = timeline.get("intervals", []) if isinstance(timeline.get("intervals", []), list) else []
        periods: list[dict[str, Any]] = []
        number = 1

        for item in intervals[:7]:
            start_raw = str(item.get("startTime") or "")
            try:
                day_start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
            except Exception:
                continue

            values = item.get("values", {}) if isinstance(item.get("values", {}), dict) else {}
            text = _tomorrow_text(values.get("weatherCodeMax"))

            periods.append(
                {
                    "number": number,
                    "name": day_start.strftime("%A"),
                    "start_time": _to_iso(day_start),
                    "end_time": _to_iso(day_start + timedelta(hours=12)),
                    "is_daytime": True,
                    "temp_f": values.get("temperatureMax"),
                    "temp_trend": None,
                    "wind_speed": f"{values.get('windSpeedAvg', 0)} mph" if values.get("windSpeedAvg") is not None else None,
                    "wind_direction": values.get("windDirectionAvg"),
                    "icon": None,
                    "short_forecast": text,
                    "detailed_forecast": text,
                    "precip_percent": values.get("precipitationProbabilityAvg"),
                }
            )
            number += 1

            periods.append(
                {
                    "number": number,
                    "name": f"{day_start.strftime('%A')} Night",
                    "start_time": _to_iso(day_start + timedelta(hours=12)),
                    "end_time": _to_iso(day_start + timedelta(days=1)),
                    "is_daytime": False,
                    "temp_f": values.get("temperatureMin"),
                    "temp_trend": None,
                    "wind_speed": f"{values.get('windSpeedAvg', 0)} mph" if values.get("windSpeedAvg") is not None else None,
                    "wind_direction": values.get("windDirectionAvg"),
                    "icon": None,
                    "short_forecast": text,
                    "detailed_forecast": text,
                    "precip_percent": values.get("precipitationProbabilityAvg"),
                }
            )
            number += 1

        return periods

    return await _get_or_refresh_shared(key, cache_type="forecast_tomorrow", ttl=900, producer=_producer)


async def get_visualcrossing_current(lat: float, lon: float, api_key: str) -> dict[str, Any]:
    if not api_key:
        raise ValueError("Visual Crossing key not configured")

    key = f"visualcrossing-current:{lat},{lon}"

    async def _producer() -> dict[str, Any]:
        raw = await _json_get_with_retry(
            f"{VISUALCROSSING_BASE}/{lat},{lon}",
            {
                "key": api_key,
                "unitGroup": "us",
                "contentType": "json",
                "include": "current",
            },
            upstream_name="visualcrossing",
        )
        current = raw.get("currentConditions", {}) if isinstance(raw.get("currentConditions", {}), dict) else {}
        timestamp = _vc_to_iso_epoch(current.get("datetimeEpoch")) or current.get("datetime")
        return {
            "station": "visualcrossing",
            "timestamp": timestamp,
            "description": current.get("conditions"),
            "icon": _vc_icon(current.get("icon")),
            "temp_f": current.get("temp"),
            "feels_like_f": current.get("feelslike"),
            "dewpoint_f": current.get("dew"),
            "humidity": current.get("humidity"),
            "wind_speed_mph": current.get("windspeed"),
            "wind_direction": current.get("winddir"),
            "wind_gust_mph": current.get("windgust"),
            "pressure_inhg": current.get("pressure"),
            "visibility_miles": current.get("visibility"),
            "cloud_layers": [],
        }

    return await _get_or_refresh_shared(key, cache_type="current_visualcrossing", ttl=300, producer=_producer)


async def get_visualcrossing_hourly(lat: float, lon: float, api_key: str) -> list[dict[str, Any]]:
    if not api_key:
        raise ValueError("Visual Crossing key not configured")

    key = f"visualcrossing-hourly:{lat},{lon}"

    async def _producer() -> list[dict[str, Any]]:
        raw = await _json_get_with_retry(
            f"{VISUALCROSSING_BASE}/{lat},{lon}",
            {
                "key": api_key,
                "unitGroup": "us",
                "contentType": "json",
                "include": "hours,days",
            },
            upstream_name="visualcrossing",
        )
        days = raw.get("days", []) if isinstance(raw.get("days", []), list) else []
        rows: list[dict[str, Any]] = []

        for day in days:
            hours = day.get("hours", []) if isinstance(day.get("hours", []), list) else []
            for hour in hours:
                rows.append(
                    {
                        "start_time": _vc_to_iso_epoch(hour.get("datetimeEpoch")) or hour.get("datetime"),
                        "temp_f": hour.get("temp"),
                        "wind_speed": f"{hour.get('windspeed', 0)} mph" if hour.get("windspeed") is not None else None,
                        "wind_direction": hour.get("winddir"),
                        "short_forecast": hour.get("conditions"),
                        "icon": _vc_icon(hour.get("icon")),
                        "precip_percent": hour.get("precipprob"),
                    }
                )

        rows.sort(key=lambda r: str(r.get("start_time") or ""))
        return rows[:48]

    return await _get_or_refresh_shared(key, cache_type="hourly_visualcrossing", ttl=900, producer=_producer)


async def get_visualcrossing_forecast(lat: float, lon: float, api_key: str) -> list[dict[str, Any]]:
    if not api_key:
        raise ValueError("Visual Crossing key not configured")

    key = f"visualcrossing-forecast:{lat},{lon}"

    async def _producer() -> list[dict[str, Any]]:
        raw = await _json_get_with_retry(
            f"{VISUALCROSSING_BASE}/{lat},{lon}",
            {
                "key": api_key,
                "unitGroup": "us",
                "contentType": "json",
                "include": "days",
            },
            upstream_name="visualcrossing",
        )
        days = raw.get("days", []) if isinstance(raw.get("days", []), list) else []
        periods: list[dict[str, Any]] = []
        number = 1

        for day in days[:7]:
            day_start_iso = _vc_to_iso_epoch(day.get("datetimeEpoch"))
            day_start: datetime | None = None
            if day_start_iso:
                day_start = datetime.fromisoformat(day_start_iso.replace("Z", "+00:00"))
            if day_start is None:
                continue

            text = day.get("conditions")
            wind_speed = f"{day.get('windspeed', 0)} mph" if day.get("windspeed") is not None else None

            periods.append(
                {
                    "number": number,
                    "name": day_start.strftime("%A"),
                    "start_time": _to_iso(day_start),
                    "end_time": _to_iso(day_start + timedelta(hours=12)),
                    "is_daytime": True,
                    "temp_f": day.get("tempmax"),
                    "temp_trend": None,
                    "wind_speed": wind_speed,
                    "wind_direction": day.get("winddir"),
                    "icon": _vc_icon(day.get("icon")),
                    "short_forecast": text,
                    "detailed_forecast": text,
                    "precip_percent": day.get("precipprob"),
                }
            )
            number += 1

            periods.append(
                {
                    "number": number,
                    "name": f"{day_start.strftime('%A')} Night",
                    "start_time": _to_iso(day_start + timedelta(hours=12)),
                    "end_time": _to_iso(day_start + timedelta(days=1)),
                    "is_daytime": False,
                    "temp_f": day.get("tempmin"),
                    "temp_trend": None,
                    "wind_speed": wind_speed,
                    "wind_direction": day.get("winddir"),
                    "icon": _vc_icon(day.get("icon")),
                    "short_forecast": text,
                    "detailed_forecast": text,
                    "precip_percent": day.get("precipprob"),
                }
            )
            number += 1

        return periods

    return await _get_or_refresh_shared(key, cache_type="forecast_visualcrossing", ttl=900, producer=_producer)


# ---------------------------------------------------------------------------
# AviationWeather keyless adapter (ADDS / aviationweather.gov)
# Surfaces METAR observations for the nearest airport station.
# Keyless — no registration required.
# ---------------------------------------------------------------------------

AVIATIONWEATHER_METAR_URL = "https://aviationweather.gov/api/data/metar"


def _nearest_icao_station(lat: float, lon: float) -> str:
    """
    Return a bounding-box query string for aviationweather.gov.
    We use a ±1.5° box; the API returns the nearest station inside it.
    """
    return f"{lat - 1.5},{lon - 1.5},{lat + 1.5},{lon + 1.5}"


def _normalize_metar(obs: dict) -> dict[str, Any]:
    """Normalize a single METAR GeoJSON feature to the shared current schema."""
    props = obs.get("properties", {}) if isinstance(obs.get("properties", {}), dict) else {}

    raw_temp_c = props.get("temperature", {}).get("value") if isinstance(props.get("temperature", {}), dict) else None
    raw_dew_c = props.get("dewpoint", {}).get("value") if isinstance(props.get("dewpoint", {}), dict) else None
    raw_vis_m = props.get("visibility", {}).get("value") if isinstance(props.get("visibility", {}), dict) else None
    raw_pressure_pa = props.get("seaLevelPressure", {}).get("value") if isinstance(props.get("seaLevelPressure", {}), dict) else None
    raw_wind_mps = props.get("windSpeed", {}).get("value") if isinstance(props.get("windSpeed", {}), dict) else None
    raw_gust_mps = props.get("windGust", {}).get("value") if isinstance(props.get("windGust", {}), dict) else None

    def _c_to_f(c: Any) -> float | None:
        try:
            return round(float(c) * 9 / 5 + 32, 1)
        except Exception:
            return None

    def _mps_to_mph(mps: Any) -> float | None:
        try:
            return round(float(mps) * 2.237, 1)
        except Exception:
            return None

    def _m_to_miles(m: Any) -> float | None:
        try:
            return round(float(m) / 1609.34, 1)
        except Exception:
            return None

    def _pa_to_inhg(pa: Any) -> float | None:
        try:
            return round(float(pa) / 3386.39, 2)
        except Exception:
            return None

    station = props.get("stationIdentifier") or props.get("station") or "aviationweather"
    sky_conditions = props.get("skyCondition", [])
    cloud_layers = []
    if isinstance(sky_conditions, list):
        for layer in sky_conditions:
            if isinstance(layer, dict):
                cov = layer.get("skyCover") or ""
                base = layer.get("cloudBase", {})
                base_ft = base.get("value") if isinstance(base, dict) else None
                cloud_layers.append({"coverage": cov, "base_ft": base_ft})

    return {
        "station": station,
        "timestamp": props.get("timestamp"),
        "description": props.get("presentWeather") or props.get("rawMessage"),
        "icon": None,
        "temp_f": _c_to_f(raw_temp_c),
        "feels_like_f": None,
        "dewpoint_f": _c_to_f(raw_dew_c),
        "humidity": None,
        "wind_speed_mph": _mps_to_mph(raw_wind_mps),
        "wind_direction": props.get("windDirection", {}).get("value") if isinstance(props.get("windDirection", {}), dict) else None,
        "wind_gust_mph": _mps_to_mph(raw_gust_mps),
        "pressure_inhg": _pa_to_inhg(raw_pressure_pa),
        "visibility_miles": _m_to_miles(raw_vis_m),
        "cloud_layers": cloud_layers,
        "raw_metar": props.get("rawMessage"),
        "flight_category": props.get("flightCategory"),
    }


async def get_aviationweather_metar(lat: float, lon: float, user_agent: str = "weatherapp") -> dict[str, Any]:
    """
    Fetch the closest METAR observation from aviationweather.gov.
    Returns a normalized current-conditions dict.  Cached 10 minutes.
    """
    key = f"aviationweather-metar:{lat:.3f},{lon:.3f}"

    async def _producer() -> dict[str, Any]:
        bbox = _nearest_icao_station(lat, lon)
        async with httpx.AsyncClient(
            headers={"User-Agent": user_agent, "Accept": "application/geo+json"},
            timeout=15,
            follow_redirects=True,
        ) as client:
            _bump_upstream_call("aviationweather")
            resp = await client.get(
                AVIATIONWEATHER_METAR_URL,
                params={
                    "bbox": bbox,
                    "format": "geojson",
                    "taf": "false",
                    "hours": 1,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        features = data.get("features", []) if isinstance(data.get("features", []), list) else []
        if not features:
            raise RuntimeError("No METAR stations found in bounding box")
        return _normalize_metar(features[0])

    return await _get_or_refresh_shared(key, cache_type="current_aviationweather", ttl=600, producer=_producer)


# ---------------------------------------------------------------------------
# NOAA CO-OPS Tides keyless adapter
# Returns tide predictions for the nearest station.
# Keyless — no registration required.
# ---------------------------------------------------------------------------

NOAA_TIDES_BASE = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"


async def get_noaa_tides(lat: float, lon: float, days: int = 2) -> dict[str, Any]:
    """
    Fetch tide predictions from the nearest NOAA tide station.
    Returns predictions for the next `days` days.  Cached 30 minutes.
    """
    safe_days = max(1, min(int(days), 7))
    key = f"noaa-tides:{lat:.3f},{lon:.3f}:{safe_days}"

    async def _producer() -> dict[str, Any]:
        # Step 1: find nearest station using the NOAA metadata API.
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            _bump_upstream_call("noaa_tides")
            station_resp = await client.get(
                "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/tidepredstations.json",
                params={"expand": "detail", "type": "tidepredictions"},
            )
            station_resp.raise_for_status()
            station_data = station_resp.json()

        stations = station_data.get("stationList", []) if isinstance(station_data.get("stationList", []), list) else []
        if not stations:
            raise RuntimeError("NOAA tides: no stations returned")

        # Find the station with the minimum great-circle distance.
        import math

        def _dist(s: dict) -> float:
            try:
                dlat = float(s.get("lat", 0)) - lat
                dlon = float(s.get("lng", 0)) - lon
                return math.sqrt(dlat ** 2 + dlon ** 2)
            except Exception:
                return float("inf")

        nearest = min(stations, key=_dist)
        station_id = str(nearest.get("stationId") or "")
        station_name = str(nearest.get("etidesStnName") or nearest.get("stationId") or "")

        if not station_id:
            raise RuntimeError("NOAA tides: could not resolve nearest station ID")

        # Step 2: fetch tide predictions for that station.
        from datetime import date

        begin_date = date.today().strftime("%Y%m%d")
        from datetime import timedelta as _td

        end_date = (date.today() + _td(days=safe_days - 1)).strftime("%Y%m%d")

        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            _bump_upstream_call("noaa_tides")
            pred_resp = await client.get(
                NOAA_TIDES_BASE,
                params={
                    "begin_date": begin_date,
                    "end_date": end_date,
                    "station": station_id,
                    "product": "predictions",
                    "datum": "MLLW",
                    "time_zone": "GMT",
                    "interval": "hilo",
                    "units": "english",
                    "application": "weatherapp",
                    "format": "json",
                },
            )
            pred_resp.raise_for_status()
            pred_data = pred_resp.json()

        if "error" in pred_data:
            raise RuntimeError(f"NOAA tides error: {pred_data['error'].get('message', 'unknown')}")

        predictions = pred_data.get("predictions", []) if isinstance(pred_data.get("predictions", []), list) else []
        tides: list[dict[str, Any]] = []
        for p in predictions:
            tides.append(
                {
                    "time": p.get("t"),
                    "type": "high" if str(p.get("type", "")).upper() == "H" else "low",
                    "height_ft": float(p["v"]) if p.get("v") not in (None, "") else None,
                }
            )

        return {
            "station_id": station_id,
            "station_name": station_name,
            "datum": "MLLW",
            "unit": "ft",
            "predictions": tides,
            "updated_at": time.time(),
        }

    return await _get_or_refresh_shared(key, cache_type="tides_noaa", ttl=1800, producer=_producer)


# ---------------------------------------------------------------------------
# Meteomatics keyed adapter
# Basic current conditions via the Meteomatics weather API (REST).
# Requires username + password (colon-separated in METEOMATICS_API_KEY env var).
# ---------------------------------------------------------------------------

METEOMATICS_BASE = "https://api.meteomatics.com"

_METEOMATICS_PARAMS = (
    "t_2m:F,"
    "apparent_temperature:F,"
    "relative_humidity_2m:p,"
    "wind_speed_10m:mph,"
    "wind_dir_10m:d,"
    "wind_gusts_10m_1h:mph,"
    "msl_pressure:hPa,"
    "dew_point_2m:F,"
    "visibility:mi,"
    "weather_symbol_1h:idx"
)


def _now_iso_meteomatics() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z")


def _normalize_meteomatics(raw: dict, ts: str) -> dict[str, Any]:
    """Parse Meteomatics REST /json response into the shared current schema."""
    data = raw.get("data", []) if isinstance(raw.get("data", []), list) else []

    values: dict[str, Any] = {}
    for item in data:
        param = str(item.get("parameter", ""))
        coords = item.get("coordinates", [])
        if isinstance(coords, list) and coords:
            dates_list = coords[0].get("dates", [])
            if isinstance(dates_list, list) and dates_list:
                v = dates_list[0].get("value")
                values[param] = v

    def _get(key_prefix: str) -> Any:
        for k, v in values.items():
            if k.startswith(key_prefix):
                return v
        return None

    return {
        "station": "meteomatics",
        "timestamp": ts,
        "description": None,
        "icon": None,
        "temp_f": _get("t_2m"),
        "feels_like_f": _get("apparent_temperature"),
        "dewpoint_f": _get("dew_point_2m"),
        "humidity": _get("relative_humidity_2m"),
        "wind_speed_mph": _get("wind_speed_10m"),
        "wind_direction": _get("wind_dir_10m"),
        "wind_gust_mph": _get("wind_gusts_10m_1h"),
        "pressure_inhg": (
            round(float(_get("msl_pressure")) / 33.8639, 2) if _get("msl_pressure") is not None else None
        ),
        "visibility_miles": _get("visibility"),
        "cloud_layers": [],
    }


async def get_meteomatics_current(lat: float, lon: float, api_key: str) -> dict[str, Any]:
    """
    Fetch current conditions from Meteomatics.
    `api_key` must be ``username:password`` (colon-separated).
    Cached 5 minutes.
    """
    if not api_key or ":" not in api_key:
        raise ValueError("Meteomatics key must be 'username:password'")

    username, password = api_key.split(":", 1)
    if not username or not password:
        raise ValueError("Meteomatics username or password is empty")

    key = f"meteomatics-current:{lat},{lon}"

    async def _producer() -> dict[str, Any]:
        ts = _now_iso_meteomatics()
        url = f"{METEOMATICS_BASE}/{ts}/{_METEOMATICS_PARAMS}/{lat},{lon}/json"

        async with httpx.AsyncClient(
            auth=(username, password),
            timeout=20,
            follow_redirects=True,
        ) as client:
            _bump_upstream_call("meteomatics")
            resp = await client.get(url)
            resp.raise_for_status()
            raw = resp.json()

        return _normalize_meteomatics(raw, ts)

    return await _get_or_refresh_shared(key, cache_type="current_meteomatics", ttl=300, producer=_producer)


async def _owm_get(url: str, params: dict) -> dict:
    """Fetch JSON from OWM with retry. API key is in params, never logged."""
    retryable_status = {429, 500, 502, 503, 504}
    last_exc: Exception | None = None

    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                _bump_upstream_call("owm")
                resp = await client.get(url, params=params)
                if resp.status_code in retryable_status:
                    raise httpx.HTTPStatusError(
                        f"OWM upstream status: {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                resp.raise_for_status()
                return resp.json()
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            is_retryable_http = (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response is not None
                and exc.response.status_code in retryable_status
            )
            if attempt < 3 and (
                isinstance(exc, (httpx.TimeoutException, httpx.TransportError))
                or is_retryable_http
            ):
                await asyncio.sleep(0.5 * attempt)
                continue
            raise

    if last_exc:
        raise last_exc
    raise RuntimeError("OWM request failed unexpectedly")


async def get_owm_onecall(lat: float, lon: float, api_key: str) -> dict:
    """
    OpenWeather One Call 3.0 — current + hourly (48 h) + daily (8 d) + alerts.
    Cached 10 minutes. API key is never included in the returned payload.
    Units: imperial (degF / mph).
    """
    if not api_key:
        raise ValueError("OWM API key not configured")

    key = f"owm:{lat},{lon}"

    async def _producer() -> dict:
        data = await _owm_get(
            f"{OWM_BASE}/onecall",
            {
                "lat":     lat,
                "lon":     lon,
                "appid":   api_key,
                "units":   "imperial",
                "exclude": "minutely",
            },
        )
        return {
            "timezone":        data.get("timezone"),
            "timezone_offset": data.get("timezone_offset"),
            "current":         data.get("current"),
            "hourly":          data.get("hourly", [])[:48],
            "daily":           data.get("daily", [])[:8],
            "alerts":          data.get("alerts", []),
        }

    return await _get_or_refresh_shared(key, cache_type="owm_onecall", ttl=600, producer=_producer)


async def get_owm_aqi(lat: float, lon: float, api_key: str) -> dict:
    """
    OpenWeather Air Quality endpoint — AQI index, pollutants, source.
    Cached 30 minutes. API key is never included in the returned payload.
    """
    if not api_key:
        raise ValueError("OWM API key not configured")

    key = f"aqi_owm:{lat},{lon}"

    async def _producer() -> dict:
        data = await _owm_get(
            f"{OWM_AQI_BASE}/air_pollution",
            {
                "lat": lat,
                "lon": lon,
                "appid": api_key,
            },
        )
        # List structure; return latest (most recent) air quality reading
        list_data = data.get("list", [])
        if not list_data:
            return {
                "aqi": None,
                "main": None,
                "components": {},
                "timestamp": None,
                "available": False,
            }
        latest = list_data[0]
        main = latest.get("main", {}) or {}
        return {
            "aqi": main.get("aqi"),  # 1-5
            "main": main.get("aqi"),
            "components": latest.get("components", {}),
            "timestamp": latest.get("dt"),
            "available": True,
        }

    return await _get_or_refresh_shared(key, cache_type="aqi_owm", ttl=1800, producer=_producer)


# ---------------------------------------------------------------------------
# Personal Weather Station (Weather.com / WUnderground style)
# ---------------------------------------------------------------------------

async def _pws_get_one(station_id: str, api_key: str) -> dict:
    params = {
        "stationId": station_id,
        "format": "json",
        "units": "e",
        "apiKey": api_key,
        "numericPrecision": "decimal",
    }
    retryable_status = {429, 500, 502, 503, 504}
    last_exc: Exception | None = None

    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
                _bump_upstream_call("pws_current")
                resp = await client.get(PWS_BASE, params=params)
                if resp.status_code in retryable_status:
                    raise httpx.HTTPStatusError(
                        f"PWS upstream status: {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                resp.raise_for_status()
                return resp.json()
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            is_retryable_http = (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response is not None
                and exc.response.status_code in retryable_status
            )
            if attempt < 3 and (
                isinstance(exc, (httpx.TimeoutException, httpx.TransportError))
                or is_retryable_http
            ):
                await asyncio.sleep(0.35 * attempt)
                continue
            raise

    if last_exc:
        raise last_exc
    raise RuntimeError("PWS request failed unexpectedly")


def _pws_icon(icon_code: Any) -> str | None:
    """
    Map Weather.com PWS icon code to icon URL.
    Icon codes: https://twcapi.co/TWCICON
    """
    if not icon_code:
        return None
    try:
        code = int(icon_code)
        # Weather.com icon format: numeric code to icon URL
        # Using da (day) at night fallback from their standard icon set
        return f"https://m.tbcdn.cn/weather/icons/46/{code:02d}.svg"
    except (ValueError, TypeError):
        return None


def _norm_pws_observation(station_id: str, raw: dict) -> dict:
    """Normalize Weather.com PWS response for frontend consumption."""
    observations = raw.get("observations", [])
    obs = observations[0] if observations else {}
    imperial = obs.get("imperial", {})

    return {
        "station_id": station_id,
        "neighborhood": obs.get("neighborhood"),
        "software_type": obs.get("softwareType"),
        "obs_time_utc": obs.get("obsTimeUtc"),
        "lat": obs.get("lat"),
        "lon": obs.get("lon"),
        "temp_f": imperial.get("temp"),
        "dewpt_f": imperial.get("dewpt"),
        "heat_index_f": imperial.get("heatIndex"),
        "wind_chill_f": imperial.get("windChill"),
        "wind_mph": imperial.get("windSpeed"),
        "wind_gust_mph": imperial.get("windGust"),
        "pressure_inhg": imperial.get("pressure"),
        "precip_rate_in": imperial.get("precipRate"),
        "precip_total_in": imperial.get("precipTotal"),
        "humidity": obs.get("humidity"),
        "uv": obs.get("uv"),
        "solar_radiation": obs.get("solarRadiation"),
        "weather_desc": obs.get("wxPhraseShort") or obs.get("wxPhrase"),
        "icon": _pws_icon(obs.get("iconCode")),
    }


async def get_pws_observations(provider: str, station_ids: list[str], api_key: str) -> dict:
    """
    Fetch latest observations for configured PWS (Personal Weather Station) station IDs
    from The Weather Company API (https://twcapi.co/v2PWSO).
    Returns partial results if one station fails.
    Cached 2 minutes.
    """
    provider_name = (provider or "weather.com").lower()
    if provider_name not in {"weather.com", "wunderground", "wu"}:
        raise ValueError(f"Unsupported PWS provider: {provider}")
    if not api_key:
        raise ValueError("PWS API key not configured")
    if not station_ids:
        return {"provider": provider_name, "stations": [], "errors": []}

    key = f"pws:{provider_name}:{','.join(sorted(station_ids))}"

    async def _producer() -> dict:
        stations: list[dict] = []
        errors: list[dict] = []

        for station_id in station_ids:
            try:
                raw = await _pws_get_one(station_id, api_key)
                stations.append(_norm_pws_observation(station_id, raw))
            except Exception as exc:
                errors.append({"station_id": station_id, "error": str(exc)})

        return {
            "provider": provider_name,
            "stations": stations,
            "errors": errors,
            "updated_at": time.time(),
        }

    return await _get_or_refresh_shared(key, cache_type="pws_current", ttl=120, producer=_producer)


async def _pws_get_history_one(station_id: str, api_key: str) -> dict:
    params = {
        "stationId": station_id,
        "format": "json",
        "units": "e",
        "apiKey": api_key,
        "numericPrecision": "decimal",
    }
    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        _bump_upstream_call("pws_history")
        resp = await client.get(PWS_HISTORY_BASE, params=params)
        resp.raise_for_status()
        return resp.json()


def _norm_pws_history(station_id: str, raw: dict, hours: int) -> dict:
    observations = raw.get("observations", [])
    if not observations:
        return {"station_id": station_id, "points": []}

    now_ts = time.time()
    min_ts = now_ts - (hours * 3600)
    points: list[dict] = []

    for obs in observations:
        obs_time = obs.get("obsTimeUtc")
        if not obs_time:
            continue
        try:
            obs_epoch = time.mktime(time.strptime(obs_time.replace("Z", ""), "%Y-%m-%dT%H:%M:%S"))
        except Exception:
            obs_epoch = None

        # Keep points in requested window; if parsing fails, keep point anyway.
        if obs_epoch is not None and obs_epoch < min_ts:
            continue

        imp = obs.get("imperial", {})
        p_min = imp.get("pressureMin")
        p_max = imp.get("pressureMax")
        p_mid = None
        if p_min is not None and p_max is not None:
            p_mid = round((p_min + p_max) / 2, 2)
        elif p_min is not None:
            p_mid = p_min
        elif p_max is not None:
            p_mid = p_max

        points.append(
            {
                "obs_time_utc": obs_time,
                "temp_f": imp.get("tempAvg"),
                "pressure_inhg": p_mid,
                "wind_gust_mph": imp.get("windgustAvg"),
                "humidity": obs.get("humidityAvg"),
                "precip_total_in": imp.get("precipTotal"),
            }
        )

    return {"station_id": station_id, "points": points}


async def get_pws_trend(provider: str, station_ids: list[str], api_key: str, hours: int = 3) -> dict:
    """
    Fetch historical trend data for configured PWS stations from The Weather Company API
    (https://twcapi.co/v2PWSRHHH - hourly history).
    Returns partial results if one station fails.
    Cached 5 minutes.
    """
    provider_name = (provider or "weather.com").lower()
    if provider_name not in {"weather.com", "wunderground", "wu"}:
        raise ValueError(f"Unsupported PWS provider: {provider}")
    if not api_key:
        raise ValueError("PWS API key not configured")
    if not station_ids:
        return {"provider": provider_name, "hours": hours, "stations": [], "errors": []}

    safe_hours = max(1, min(int(hours), 24))
    key = f"pws-trend:{provider_name}:{safe_hours}:{','.join(sorted(station_ids))}"

    async def _producer() -> dict:
        stations: list[dict] = []
        errors: list[dict] = []

        for station_id in station_ids:
            try:
                raw = await _pws_get_history_one(station_id, api_key)
                stations.append(_norm_pws_history(station_id, raw, safe_hours))
            except Exception as exc:
                errors.append({"station_id": station_id, "error": str(exc)})

        return {
            "provider": provider_name,
            "hours": safe_hours,
            "stations": stations,
            "errors": errors,
            "updated_at": time.time(),
        }

    return await _get_or_refresh_shared(key, cache_type="pws_trend", ttl=300, producer=_producer)


async def test_provider(
    provider_id: str,
    lat: float,
    lon: float,
    api_key: str | None = None,
    user_agent: str = "(weatherapp, local@example.com)",
) -> dict[str, Any]:
    """Test a provider's API connectivity. Returns {ok, message, data, error}."""
    try:
        if provider_id == "nws":
            result = await get_current(lat, lon, user_agent)
            return {
                "ok": True,
                "provider": "nws",
                "message": "NWS API responding",
                "data": {
                    "temp": result.get("temp_f"),
                    "condition": result.get("condition"),
                    "timestamp": result.get("obs_time"),
                },
            }

        elif provider_id == "openweather":
            if not api_key:
                return {"ok": False, "provider": "openweather", "error": "API key required"}
            result = await get_owm_onecall(lat, lon, api_key)
            return {
                "ok": True,
                "provider": "openweather",
                "message": "OpenWeather API responding",
                "data": {
                    "temp": result.get("current", {}).get("temp"),
                    "condition": result.get("current", {}).get("weather", [{}])[0].get("main"),
                    "timestamp": "current",
                },
            }

        elif provider_id == "weatherapi":
            if not api_key:
                return {"ok": False, "provider": "weatherapi", "error": "API key required"}
            result = await get_weatherapi_current(lat, lon, api_key)
            return {
                "ok": True,
                "provider": "weatherapi",
                "message": "WeatherAPI responding",
                "data": {
                    "temp": result.get("temp_c"),
                    "condition": result.get("condition"),
                    "timestamp": result.get("last_updated"),
                },
            }

        elif provider_id == "tomorrow":
            if not api_key:
                return {"ok": False, "provider": "tomorrow", "error": "API key required"}
            result = await get_tomorrow_current(lat, lon, api_key)
            return {
                "ok": True,
                "provider": "tomorrow",
                "message": "Tomorrow.io API responding",
                "data": {
                    "temp": result.get("temp"),
                    "condition": result.get("condition"),
                    "timestamp": result.get("updated_at"),
                },
            }

        elif provider_id == "meteomatics":
            if not api_key:
                return {"ok": False, "provider": "meteomatics", "error": "API key required"}
            result = await get_meteomatics_current(lat, lon, api_key)
            return {
                "ok": True,
                "provider": "meteomatics",
                "message": "Meteomatics API responding",
                "data": {
                    "temp": result.get("temp_c"),
                    "condition": result.get("condition"),
                    "timestamp": result.get("timestamp"),
                },
            }

        elif provider_id == "visualcrossing":
            if not api_key:
                return {"ok": False, "provider": "visualcrossing", "error": "API key required"}
            result = await get_visualcrossing_current(lat, lon, api_key)
            return {
                "ok": True,
                "provider": "visualcrossing",
                "message": "Visual Crossing API responding",
                "data": {
                    "temp": result.get("temp_c"),
                    "condition": result.get("condition"),
                    "timestamp": result.get("datetime"),
                },
            }

        elif provider_id == "aviationweather":
            result = await get_aviationweather_metar(lat, lon, user_agent)
            if result.get("station"):
                return {
                    "ok": True,
                    "provider": "aviationweather",
                    "message": "AviationWeather API responding",
                    "data": {
                        "station": result.get("station"),
                        "temp": result.get("temp_c"),
                        "condition": result.get("condition"),
                        "timestamp": result.get("timestamp"),
                    },
                }
            else:
                return {
                    "ok": False,
                    "provider": "aviationweather",
                    "error": "No METAR station found nearby",
                }

        elif provider_id == "noaa_tides":
            result = await get_noaa_tides(lat, lon, days=1)
            if result.get("station"):
                return {
                    "ok": True,
                    "provider": "noaa_tides",
                    "message": "NOAA Tides API responding",
                    "data": {
                        "station": result.get("station"),
                        "timestamp": "current",
                    },
                }
            else:
                return {
                    "ok": False,
                    "provider": "noaa_tides",
                    "error": "No tide station found nearby",
                }

        else:
            return {"ok": False, "provider": provider_id, "error": f"Unknown provider: {provider_id}"}

    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else 502
        provider_name = {
            "openweather": "OpenWeather",
            "weatherapi": "WeatherAPI",
            "visualcrossing": "Visual Crossing",
            "aviationweather": "AviationWeather",
            "noaa_tides": "NOAA Tides",
        }.get(provider_id, provider_id)
        if provider_id == "openweather" and status_code == 401:
            message = "OpenWeather rejected the API key (401 Unauthorized). Verify the key and that it has One Call access enabled."
        elif provider_id == "openweather" and status_code == 404:
            message = "OpenWeather endpoint not available for this request. Verify the configured API plan and endpoint support."
        elif status_code in {400, 401, 403, 404}:
            message = f"{provider_name} request failed with HTTP {status_code}. Verify provider credentials and configuration."
        else:
            message = f"{provider_name} upstream error (HTTP {status_code})."
        return {
            "ok": False,
            "provider": provider_id,
            "error": message,
            "status_code": 400 if status_code in {400, 401, 403, 404} else 502,
        }
    except Exception as exc:
        return {
            "ok": False,
            "provider": provider_id,
            "error": str(exc),
        }

