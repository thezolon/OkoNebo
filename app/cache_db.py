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
    "alerts": 900,        # 15 min baseline
    "current": 900,       # 15 min
    "forecast": 1800,     # 30 min
    "hourly": 1800,       # 30 min
    "pws": 600,           # 10 min
    "owm": 900,           # 15 min
}

# Shortened TTLs when storms are approaching or active
STORM_APPROACHING_TTL = {
    "alerts": 300,        # 5 min
    "current": 300,       # 5 min
    "forecast": 600,      # 10 min
    "hourly": 300,        # 5 min
    "pws": 180,           # 3 min
    "owm": 300,           # 5 min
}

# Aggressive TTLs during active storms or storm mode
ACTIVE_STORM_TTL = {
    "alerts": 120,        # 2 min (30s if in storm mode, but cache granularity is 2min)
    "current": 300,       # 5 min
    "forecast": 300,      # 5 min
    "hourly": 300,        # 5 min
    "pws": 120,           # 2 min
    "owm": 300,           # 5 min
}


class WeatherCache:
    """SQLite cache with adaptive TTLs based on weather threat level."""

    def __init__(self, db_path: str = "cache.db"):
        self.db_path = Path(db_path)
        self._init_db()

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
        ttl = self._get_ttl(cache_type, threat_level)
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
