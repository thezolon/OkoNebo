"""
Lightweight SQLite cache for weather data with adaptive TTLs.
Reduces API calls by caching responses with different retention policies based on threat level.
"""

import sqlite3
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any

# Cache TTLs (seconds) - will be updated dynamically based on alert severity
DEFAULT_TTL = {
    "alerts": 900,        # legacy bucket
    "current": 900,       # legacy bucket
    "forecast": 1800,     # legacy bucket
    "hourly": 1800,       # legacy bucket
    "pws": 600,           # legacy bucket
    "owm": 900,           # legacy bucket

    # Provider-specific buckets (used by weather_client cache_type values)
    "point_nws": 86400,
    "alerts_nws": 300,
    "current_nws": 300,
    "forecast_nws": 900,
    "hourly_nws": 900,

    "current_weatherapi": 300,
    "forecast_weatherapi": 900,
    "hourly_weatherapi": 900,

    "current_tomorrow": 300,
    "forecast_tomorrow": 900,
    "hourly_tomorrow": 900,

    "current_visualcrossing": 300,
    "forecast_visualcrossing": 900,
    "hourly_visualcrossing": 900,

    "current_meteomatics": 300,
    "current_aviationweather": 600,
    "tides_noaa": 1800,
    "owm_onecall": 600,
    "pws_current": 120,
    "pws_trend": 300,
}

# Shortened TTLs when storms are approaching or active
STORM_APPROACHING_TTL = {
    "alerts": 300,
    "current": 300,
    "forecast": 600,
    "hourly": 300,
    "pws": 180,
    "owm": 300,

    "point_nws": 86400,
    "alerts_nws": 180,
    "current_nws": 180,
    "forecast_nws": 600,
    "hourly_nws": 300,

    "current_weatherapi": 240,
    "forecast_weatherapi": 600,
    "hourly_weatherapi": 600,

    "current_tomorrow": 240,
    "forecast_tomorrow": 600,
    "hourly_tomorrow": 600,

    "current_visualcrossing": 240,
    "forecast_visualcrossing": 600,
    "hourly_visualcrossing": 600,

    "current_meteomatics": 240,
    "current_aviationweather": 600,
    "tides_noaa": 1800,
    "owm_onecall": 300,
    "pws_current": 120,
    "pws_trend": 240,
}

# Aggressive TTLs during active storms or storm mode
ACTIVE_STORM_TTL = {
    "alerts": 120,
    "current": 300,
    "forecast": 300,
    "hourly": 300,
    "pws": 120,
    "owm": 300,

    "point_nws": 86400,
    "alerts_nws": 120,
    "current_nws": 120,
    "forecast_nws": 300,
    "hourly_nws": 300,

    "current_weatherapi": 180,
    "forecast_weatherapi": 300,
    "hourly_weatherapi": 300,

    "current_tomorrow": 180,
    "forecast_tomorrow": 300,
    "hourly_tomorrow": 300,

    "current_visualcrossing": 180,
    "forecast_visualcrossing": 300,
    "hourly_visualcrossing": 300,

    "current_meteomatics": 180,
    "current_aviationweather": 600,
    "tides_noaa": 1800,
    "owm_onecall": 300,
    "pws_current": 90,
    "pws_trend": 180,
}


class WeatherCache:
    """SQLite cache with adaptive TTLs based on weather threat level."""

    def __init__(self, db_path: str = "cache.db"):
        self.db_path = Path(db_path)
        self._ttl_overrides: Dict[str, int] = {}
        self._init_db()

    def set_ttl_overrides(self, overrides: Dict[str, Any] | None):
        """Set runtime cache-type TTL overrides (seconds)."""
        cleaned: Dict[str, int] = {}
        for key, raw in (overrides or {}).items():
            try:
                ttl = int(raw)
            except Exception:
                continue
            if ttl <= 0:
                continue
            cleaned[str(key)] = ttl
        self._ttl_overrides = cleaned

    def resolve_ttl(self, cache_type: str, threat_level: str = "default", fallback: int = 900) -> int:
        """Resolve effective TTL including runtime overrides."""
        if cache_type in self._ttl_overrides:
            return int(self._ttl_overrides[cache_type])

        base = self._get_ttl(cache_type, threat_level)
        if base is None:
            return int(fallback)
        return int(base)

    def _init_db(self):
        """Create cache table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    timestamp INTEGER NOT NULL
                )
            """)
            conn.commit()

    def _get_ttl(self, cache_type: str, threat_level: str = "default") -> int:
        """Get TTL in seconds based on threat level."""
        if threat_level == "active":
            return ACTIVE_STORM_TTL.get(cache_type, DEFAULT_TTL.get(cache_type, 900))
        elif threat_level == "approaching":
            return STORM_APPROACHING_TTL.get(cache_type, DEFAULT_TTL.get(cache_type, 900))
        return DEFAULT_TTL.get(cache_type, 900)

    def set(self, key: str, data: Dict[str, Any], cache_type: str = "default", threat_level: str = "default"):
        """Store data in cache with adaptive TTL."""
        json_data = json.dumps(data)
        timestamp = int(time.time())

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache (key, data, timestamp) VALUES (?, ?, ?)",
                (key, json_data, timestamp),
            )
            conn.commit()

    def get(self, key: str, cache_type: str = "default", threat_level: str = "default") -> Optional[Dict[str, Any]]:
        """
        Retrieve data from cache if not expired.
        
        Args:
            key: Cache key
            cache_type: Type of cache (alerts, current, forecast, etc.)
            threat_level: "default", "approaching", or "active"
        
        Returns:
            Cached data if valid, None if expired or not found
        """
        ttl = self.resolve_ttl(cache_type, threat_level)
        now = int(time.time())

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT data, timestamp FROM cache WHERE key = ?", (key,)).fetchone()

        if not row:
            return None

        data_str, stored_time = row
        age = now - stored_time

        if age > ttl:
            # Expired; remove it
            self.delete(key)
            return None

        try:
            return json.loads(data_str)
        except json.JSONDecodeError:
            return None

    def delete(self, key: str):
        """Remove entry from cache."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            conn.commit()

    def clear(self):
        """Clear all cache entries."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM cache")
            conn.commit()

    def get_threat_level(self, alerts: list) -> str:
        """
        Determine threat level based on current alerts.
        
        Args:
            alerts: List of alert dictionaries from NWS API
        
        Returns:
            "default", "approaching", or "active"
        """
        if not alerts:
            return "default"

        # Check for severe/urgent alerts (Tornado Warning, Severe Thunderstorm Warning, etc.)
        severe_keywords = {
            "tornado warning",
            "severe thunderstorm warning",
            "flash flood warning",
            "extreme wind warning",
        }

        watch_keywords = {
            "tornado watch",
            "severe thunderstorm watch",
            "winter weather watch",
            "flood watch",
        }

        for alert in alerts:
            event = alert.get("event", "").lower()
            if any(kw in event for kw in severe_keywords):
                return "active"

        # If we have watches or lower-severity alerts, assume approaching
        for alert in alerts:
            event = alert.get("event", "").lower()
            if any(kw in event for kw in watch_keywords):
                return "approaching"

        # Check forecast if available (basic check for "chance of" or "likely" in description)
        return "default"

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            size_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0

        return {
            "entries": count,
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / (1024 * 1024), 3),
        }
