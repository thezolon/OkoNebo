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


if __name__ == "__main__":
    unittest.main()
