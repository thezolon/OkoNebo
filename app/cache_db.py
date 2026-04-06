"""
Lightweight SQLite cache for weather data with adaptive TTLs.
Reduces API calls by caching responses with different retention policies based on threat level.
"""

import sqlite3
import json
import threading
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
    "aqi_owm": 1800,
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
    "aqi_owm": 900,
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
    "aqi_owm": 600,

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
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
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
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    timestamp INTEGER NOT NULL
                )
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL,
                    cache_type TEXT NOT NULL,
                    data TEXT NOT NULL,
                    timestamp INTEGER NOT NULL
                )
            """)
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_history_timestamp ON history(timestamp)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_history_key ON history(key)")
            self._conn.commit()

    def _should_record_history(self, cache_type: str) -> bool:
        return str(cache_type).startswith("current_")

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

        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache (key, data, timestamp) VALUES (?, ?, ?)",
                (key, json_data, timestamp),
            )
            if self._should_record_history(cache_type):
                self._conn.execute(
                    "INSERT INTO history (key, cache_type, data, timestamp) VALUES (?, ?, ?, ?)",
                    (key, cache_type, json_data, timestamp),
                )
                self._conn.execute(
                    "DELETE FROM history WHERE timestamp < ?",
                    (timestamp - 172800,),
                )
            self._conn.commit()

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

        with self._lock:
            row = self._conn.execute("SELECT data, timestamp FROM cache WHERE key = ?", (key,)).fetchone()

        if not row:
            return None

        data_str, stored_time = row
        age = now - stored_time

        if age > ttl:
            # Expired values are ignored at read-time; cleanup is handled elsewhere.
            return None

        try:
            return json.loads(data_str)
        except json.JSONDecodeError:
            return None

    def delete(self, key: str):
        """Remove entry from cache."""
        with self._lock:
            self._conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            self._conn.commit()

    def clear(self):
        """Clear all cache entries."""
        with self._lock:
            self._conn.execute("DELETE FROM cache")
            self._conn.execute("DELETE FROM history")
            self._conn.commit()

    def get_history(self, keys: list[str], hours: int = 6, limit: int = 500) -> list[Dict[str, Any]]:
        """Return bounded ascending time-series snapshots for the requested keys."""
        clean_keys = [str(key) for key in keys if str(key)]
        if not clean_keys:
            return []

        safe_hours = max(1, min(int(hours), 24))
        safe_limit = max(1, min(int(limit), 2000))
        cutoff = int(time.time()) - (safe_hours * 3600)
        placeholders = ", ".join("?" for _ in clean_keys)
        query = (
            f"SELECT key, cache_type, data, timestamp FROM history "  # nosec B608
            f"WHERE key IN ({placeholders}) AND timestamp >= ? "
            f"ORDER BY timestamp ASC LIMIT ?"
        )

        with self._lock:
            rows = self._conn.execute(query, (*clean_keys, cutoff, safe_limit)).fetchall()

        points: list[Dict[str, Any]] = []
        for key, cache_type, data_str, timestamp in rows:
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            points.append(
                {
                    "key": key,
                    "cache_type": cache_type,
                    "timestamp": timestamp,
                    "data": data,
                }
            )
        return points

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
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            history_count = self._conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
            size_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0

        return {
            "entries": count,
            "history_entries": history_count,
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / (1024 * 1024), 3),
        }

    def close(self):
        """Close the persistent SQLite connection."""
        with self._lock:
            self._conn.close()
