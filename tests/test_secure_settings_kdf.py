"""Tests for the settings-store key derivation and its migration path.

The Fernet key was originally derived with a single unsalted SHA-256 of the
seed, which is brute-forceable offline at GPU speed by anyone holding the
database file. It is now PBKDF2-HMAC-SHA256 with a per-store salt.

The migration matters as much as the derivation: an existing install must keep
its provider API keys, VAPID private key and auth users. Losing them would be
far worse than the weak KDF.
"""

import base64
import hashlib
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from app.secure_settings import SecureSettingsStore


class SecureSettingsKdfTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "secure.db"

    def _legacy_write(self, seed: str, key: str, json_text: str) -> None:
        """Write a row exactly the way the old unsalted derivation did."""
        legacy_key = base64.urlsafe_b64encode(
            hashlib.sha256((seed or "weatherapp-default-key").encode()).digest()
        )
        token = Fernet(legacy_key).encrypt(json_text.encode())
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS secure_settings (
                       skey TEXT PRIMARY KEY, svalue BLOB NOT NULL, updated_at INTEGER NOT NULL)"""
            )
            conn.execute(
                "INSERT OR REPLACE INTO secure_settings (skey, svalue, updated_at) VALUES (?, ?, ?)",
                (key, token, int(time.time())),
            )
            conn.commit()

    def _stored_blob(self, key: str) -> bytes:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT svalue FROM secure_settings WHERE skey = ?", (key,)).fetchone()
        return bytes(row[0])

    def test_round_trip(self):
        store = SecureSettingsStore(self.db_path, key_seed="a-passphrase")
        store.set_json("providers", {"owm": {"api_key": "secret"}})
        self.assertEqual(store.get_json("providers"), {"owm": {"api_key": "secret"}})

    def test_salt_persists_across_instances(self):
        first = SecureSettingsStore(self.db_path, key_seed="a-passphrase")
        first.set_json("k", {"v": 1})
        second = SecureSettingsStore(self.db_path, key_seed="a-passphrase")
        self.assertEqual(second.get_json("k"), {"v": 1}, "a reopened store must still decrypt")

    def test_two_stores_with_the_same_passphrase_get_different_keys(self):
        """The point of the salt: identical passphrases must not share a key."""
        other_path = Path(self._tmp.name) / "other.db"
        a = SecureSettingsStore(self.db_path, key_seed="same")
        b = SecureSettingsStore(other_path, key_seed="same")
        self.assertNotEqual(a._fernet._signing_key, b._fernet._signing_key)

    def test_wrong_seed_cannot_read(self):
        SecureSettingsStore(self.db_path, key_seed="right").set_json("k", {"v": "secret"})
        wrong = SecureSettingsStore(self.db_path, key_seed="wrong")
        self.assertIsNone(wrong.get_json("k"), "a wrong passphrase must not decrypt")

    def test_legacy_row_is_still_readable(self):
        """An existing install must not lose its settings."""
        self._legacy_write("my-seed", "auth.users", '[{"username": "admin"}]')
        store = SecureSettingsStore(self.db_path, key_seed="my-seed")
        self.assertEqual(store.get_json("auth.users"), [{"username": "admin"}])

    def test_legacy_row_is_migrated_in_place(self):
        """After one read the row should be re-encrypted under the new key."""
        self._legacy_write("my-seed", "providers", '{"owm": "k"}')
        before = self._stored_blob("providers")

        store = SecureSettingsStore(self.db_path, key_seed="my-seed")
        self.assertEqual(store.get_json("providers"), {"owm": "k"})

        after = self._stored_blob("providers")
        self.assertNotEqual(before, after, "the row should have been rewritten")

        # The rewritten row must be readable by the new key alone.
        legacy_key = base64.urlsafe_b64encode(hashlib.sha256(b"my-seed").digest())
        with self.assertRaises(Exception):
            Fernet(legacy_key).decrypt(after)
        self.assertEqual(store.get_json("providers"), {"owm": "k"})

    def test_corrupt_row_returns_default(self):
        SecureSettingsStore(self.db_path, key_seed="s").set_json("k", {"v": 1})
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE secure_settings SET svalue = ? WHERE skey = ?", (b"garbage", "k"))
            conn.commit()
        store = SecureSettingsStore(self.db_path, key_seed="s")
        self.assertEqual(store.get_json("k", default="fallback"), "fallback")

    def test_missing_key_returns_default(self):
        store = SecureSettingsStore(self.db_path, key_seed="s")
        self.assertEqual(store.get_json("nope", default={"d": 1}), {"d": 1})

    def test_delete_and_keys(self):
        store = SecureSettingsStore(self.db_path, key_seed="s")
        store.set_json("a", 1)
        store.set_json("b", 2)
        self.assertEqual(store.keys(), ["a", "b"])
        store.delete("a")
        self.assertEqual(store.keys(), ["b"])


if __name__ == "__main__":
    unittest.main()
