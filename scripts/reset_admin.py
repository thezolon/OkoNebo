#!/usr/bin/env python3
"""Reset or create admin/viewer credentials in secure_settings.db.

Designed for Docker recovery flows, for example:
  docker exec weather-app python /app/scripts/reset_admin.py --username admin --password 'new-strong-pass'
"""

from __future__ import annotations

import argparse
import hashlib
import secrets
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.secure_settings import SecureSettingsStore


def _hash_password(password: str, salt: str | None = None) -> str:
    safe_salt = salt or secrets.token_hex(16)
    rounds = 120_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), safe_salt.encode(), rounds)
    return f"pbkdf2_sha256${rounds}${safe_salt}${digest.hex()}"


def _load_config(config_path: Path) -> dict[str, Any]:
    try:
        with config_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _settings_seed(cfg: dict[str, Any]) -> str:
    auth_cfg = cfg.get("auth", {}) if isinstance(cfg.get("auth", {}), dict) else {}
    return str(auth_cfg.get("token_secret") or cfg.get("user_agent") or "okonebo-local")


def _upsert_user(users: list[dict[str, Any]], role: str, username: str, password: str) -> None:
    target = None
    for user in users:
        if str(user.get("role") or "").strip() == role:
            target = user
            break
        if str(user.get("username") or "").strip().lower() == username.strip().lower():
            target = user
            break

    if target is None:
        target = {}
        users.append(target)

    target["role"] = role
    target["username"] = username.strip()
    target["password_hash"] = _hash_password(password)
    target.pop("password", None)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset OkoNebo admin/viewer credentials")
    parser.add_argument("--username", default="admin", help="Admin username (default: admin)")
    parser.add_argument("--password", required=True, help="New admin password")
    parser.add_argument("--viewer-username", default="", help="Optional viewer username")
    parser.add_argument("--viewer-password", default="", help="Optional viewer password")
    parser.add_argument("--db", default="/app/secure_settings.db", help="Path to secure_settings.db")
    parser.add_argument("--config", default="/app/config.yaml", help="Path to config.yaml")
    args = parser.parse_args()

    admin_username = str(args.username or "").strip()
    admin_password = str(args.password or "")
    viewer_username = str(args.viewer_username or "").strip()
    viewer_password = str(args.viewer_password or "")

    if len(admin_username) < 3:
        raise SystemExit("admin username must be at least 3 characters")
    if len(admin_password) < 8:
        raise SystemExit("admin password must be at least 8 characters")
    if bool(viewer_username) ^ bool(viewer_password):
        raise SystemExit("viewer username and password must be provided together")

    config_path = Path(args.config)
    db_path = Path(args.db)
    cfg = _load_config(config_path)
    store = SecureSettingsStore(db_path=db_path, key_seed=_settings_seed(cfg))

    users = list(store.get_json("auth.users", []) or [])
    _upsert_user(users, role="admin", username=admin_username, password=admin_password)

    if viewer_username and viewer_password:
        _upsert_user(users, role="viewer", username=viewer_username, password=viewer_password)

    store.set_json("auth.users", users)

    runtime = store.get_json("settings.runtime", {})
    if not isinstance(runtime, dict):
        runtime = {}
    auth_runtime = runtime.get("auth", {}) if isinstance(runtime.get("auth", {}), dict) else {}
    auth_runtime["admin_user"] = admin_username
    if viewer_username:
        auth_runtime["viewer_user"] = viewer_username
    runtime["auth"] = auth_runtime
    store.set_json("settings.runtime", runtime)

    print("OK: credentials updated in secure_settings.db")
    print(f"admin username: {admin_username}")
    if viewer_username:
        print(f"viewer username: {viewer_username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
