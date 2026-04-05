import tempfile
import time
import unittest
from pathlib import Path

from app.cache_db import WeatherCache


class CacheDbTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_path = Path(self._tmpdir.name) / "cache.db"
        self.cache = WeatherCache(str(self._db_path))

    def tearDown(self):
        self.cache.close()
        self._tmpdir.cleanup()

    def test_expired_get_does_not_delete_row(self):
        key = "expired-key"
        self.cache.set(key, {"ok": True}, cache_type="current_nws")

        old_ts = int(time.time()) - 1000
        with self.cache._lock:
            self.cache._conn.execute("UPDATE cache SET timestamp = ? WHERE key = ?", (old_ts, key))
            self.cache._conn.commit()

        result = self.cache.get(key, cache_type="current_nws")
        self.assertIsNone(result)

        with self.cache._lock:
            row = self.cache._conn.execute("SELECT COUNT(*) FROM cache WHERE key = ?", (key,)).fetchone()
        self.assertEqual(int(row[0]), 1)

    def test_connection_uses_wal_mode(self):
        with self.cache._lock:
            mode_row = self.cache._conn.execute("PRAGMA journal_mode").fetchone()
        self.assertEqual(str(mode_row[0]).lower(), "wal")

    def test_current_cache_writes_are_recorded_in_history(self):
        self.cache.set("current:1,2", {"temp_f": 70}, cache_type="current_nws")

        points = self.cache.get_history(["current:1,2"], hours=1)

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["cache_type"], "current_nws")
        self.assertEqual(points[0]["data"]["temp_f"], 70)

    def test_history_results_are_sorted_and_bounded(self):
        self.cache.set("current:1,2", {"temp_f": 68}, cache_type="current_nws")
        self.cache.set("current:1,2", {"temp_f": 69}, cache_type="current_nws")
        self.cache.set("current:1,2", {"temp_f": 70}, cache_type="current_nws")

        with self.cache._lock:
            rows = self.cache._conn.execute(
                "SELECT id FROM history WHERE key = ? ORDER BY id ASC",
                ("current:1,2",),
            ).fetchall()
            base = int(time.time()) - 120
            for offset, row in enumerate(rows):
                self.cache._conn.execute(
                    "UPDATE history SET timestamp = ? WHERE id = ?",
                    (base + offset, int(row[0])),
                )
            self.cache._conn.commit()

        points = self.cache.get_history(["current:1,2"], hours=1, limit=2)

        self.assertEqual(len(points), 2)
        self.assertLessEqual(points[0]["timestamp"], points[1]["timestamp"])
        self.assertEqual(points[0]["data"]["temp_f"], 68)
        self.assertEqual(points[1]["data"]["temp_f"], 69)


if __name__ == "__main__":
    unittest.main()
