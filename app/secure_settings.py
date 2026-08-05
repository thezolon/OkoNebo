"""Encrypted SQLite settings store for runtime configuration and secrets."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


# SETTINGS_ENCRYPTION_KEY is an environment variable a human sets by hand, so the
# realistic input is a passphrase rather than high-entropy random bytes. Deriving
# the Fernet key with a single unsalted SHA-256 -- as this store originally did --
# left it brute-forceable offline at GPU speed by anyone holding the database file
# (a backup, a support copy, an SD card pulled from a Pi). That file holds provider
# API keys, auth password hashes and the VAPID private key, so it is worth
# stretching properly. 600k iterations costs well under a second once per process.
PBKDF2_ITERATIONS = 600_000
_SALT_META_KEY = "kdf_salt"


class SecureSettingsStore:
    def __init__(self, db_path: str | Path, key_seed: str):
        self.db_path = Path(db_path)
        self._init_db()
        self._fernet = Fernet(self._derive_key(key_seed, self._get_or_create_salt()))
        # Retained solely to read rows written before the KDF change; see get_json,
        # which transparently re-encrypts anything it opens this way.
        self._legacy_fernet = Fernet(self._derive_legacy_key(key_seed))

    @staticmethod
    def _derive_key(seed: str, salt: bytes) -> bytes:
        digest = hashlib.pbkdf2_hmac("sha256", (seed or "").encode(), salt, PBKDF2_ITERATIONS)
        return base64.urlsafe_b64encode(digest)

    @staticmethod
    def _derive_legacy_key(seed: str) -> bytes:
        """The original unsalted single-round derivation. Decrypt-only."""
        digest = hashlib.sha256((seed or "weatherapp-default-key").encode()).digest()
        return base64.urlsafe_b64encode(digest)

    def _get_or_create_salt(self) -> bytes:
        """Per-store salt, held in the clear. Salts are not secret; they exist so
        two installations with the same passphrase do not share a key, and so a
        precomputed table cannot cover them."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT mvalue FROM secure_meta WHERE mkey = ?", (_SALT_META_KEY,)
            ).fetchone()
            if row and row[0]:
                return bytes(row[0])
            salt = secrets.token_bytes(16)
            conn.execute(
                "INSERT OR REPLACE INTO secure_meta (mkey, mvalue) VALUES (?, ?)",
                (_SALT_META_KEY, salt),
            )
            conn.commit()
            return salt

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS secure_settings (
                    skey TEXT PRIMARY KEY,
                    svalue BLOB NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS secure_meta (
                    mkey TEXT PRIMARY KEY,
                    mvalue BLOB NOT NULL
                )
                """
            )
            conn.commit()

    def set_json(self, key: str, value: Any) -> None:
        payload = json.dumps(value, separators=(",", ":")).encode()
        token = self._fernet.encrypt(payload)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO secure_settings (skey, svalue, updated_at) VALUES (?, ?, ?)",
                (key, token, int(time.time())),
            )
            conn.commit()

    def get_json(self, key: str, default: Any = None) -> Any:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT svalue FROM secure_settings WHERE skey = ?", (key,)
            ).fetchone()
        if not row:
            return default
        token = row[0]
        try:
            raw = self._fernet.decrypt(token)
        except InvalidToken:
            # Written before the KDF change. Open it with the old key and rewrite
            # it under the new one, so an existing install migrates in place
            # rather than losing its API keys, VAPID key and auth users.
            try:
                raw = self._legacy_fernet.decrypt(token)
            except InvalidToken:
                return default
            self._rewrite_with_current_key(key, raw)

        try:
            return json.loads(raw.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return default

    def _rewrite_with_current_key(self, key: str, raw: bytes) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE secure_settings SET svalue = ?, updated_at = ? WHERE skey = ?",
                    (self._fernet.encrypt(raw), int(time.time()), key),
                )
                conn.commit()
        except Exception:
            # A failed migration must never break a read; the legacy value is
            # still perfectly usable and the next read will try again.
            pass

    def delete(self, key: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM secure_settings WHERE skey = ?", (key,))
            conn.commit()

    def keys(self) -> list[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT skey FROM secure_settings ORDER BY skey").fetchall()
        return [row[0] for row in rows]
