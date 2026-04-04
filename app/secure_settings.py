"""Encrypted SQLite settings store for runtime configuration and secrets."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class SecureSettingsStore:
    def __init__(self, db_path: str | Path, key_seed: str):
        self.db_path = Path(db_path)
        self._fernet = Fernet(self._derive_key(key_seed))
        self._init_db()

    def _derive_key(self, seed: str) -> bytes:
        digest = hashlib.sha256((seed or "weatherapp-default-key").encode()).digest()
        return base64.urlsafe_b64encode(digest)

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
            return json.loads(raw.decode())
        except (InvalidToken, json.JSONDecodeError, UnicodeDecodeError):
            return default

    def delete(self, key: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM secure_settings WHERE skey = ?", (key,))
            conn.commit()

    def keys(self) -> list[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT skey FROM secure_settings ORDER BY skey").fetchall()
        return [row[0] for row in rows]
