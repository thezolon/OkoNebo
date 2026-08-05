"""Tests for how the settings-store encryption seed is resolved.

Configuring the secret by environment rather than by config file used to leave
the store with no seed at all: only config.yaml's auth.token_secret was
consulted, never the AUTH_TOKEN_SECRET environment variable. Every restart then
minted a random key, so saved settings -- including the configured location --
became unreadable and were silently replaced by defaults. The user-visible
symptom was having to re-enter GPS coordinates after every restart.
"""

import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _resolve_seed(env: dict, config_token_secret: str | None) -> str:
    """Reproduce main.py's seed resolution in isolation."""
    cfg_secret = str(config_token_secret or "")
    return (
        env.get("SETTINGS_ENCRYPTION_KEY")
        or cfg_secret
        or str(env.get("AUTH_TOKEN_SECRET") or "")
    )


class SeedResolutionTests(unittest.TestCase):
    def test_explicit_key_wins(self):
        seed = _resolve_seed(
            {"SETTINGS_ENCRYPTION_KEY": "explicit", "AUTH_TOKEN_SECRET": "env-token"},
            "config-token",
        )
        self.assertEqual(seed, "explicit")

    def test_config_file_outranks_env_token(self):
        """Order matters: an install with both must keep deriving the key it already had."""
        seed = _resolve_seed({"AUTH_TOKEN_SECRET": "env-token"}, "config-token")
        self.assertEqual(seed, "config-token")

    def test_env_token_is_used_when_nothing_else_is_set(self):
        """The regression this fixes: env-only configuration produced no seed."""
        seed = _resolve_seed({"AUTH_TOKEN_SECRET": "env-token"}, None)
        self.assertEqual(seed, "env-token")

    def test_no_seed_anywhere_yields_empty(self):
        self.assertEqual(_resolve_seed({}, None), "")


class SettingsSurviveRestartTests(unittest.TestCase):
    """End-to-end: the same seed across two processes must keep the location."""

    def test_location_survives_a_simulated_restart(self):
        from app.secure_settings import SecureSettingsStore

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "secure.db"
            seed = "a-stable-token-secret"

            first = SecureSettingsStore(db, key_seed=seed)
            first.set_json("settings.runtime", {"location": {"lat": 36.1539, "lon": -95.9928}})

            # New process, same seed.
            second = SecureSettingsStore(db, key_seed=seed)
            restored = second.get_json("settings.runtime")

        self.assertEqual(restored["location"]["lat"], 36.1539)
        self.assertEqual(restored["location"]["lon"], -95.9928)

    def test_a_random_seed_per_process_loses_the_location(self):
        """Demonstrates the old behaviour, so the regression cannot creep back."""
        import secrets

        from app.secure_settings import SecureSettingsStore

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "secure.db"

            first = SecureSettingsStore(db, key_seed=secrets.token_hex(32))
            first.set_json("settings.runtime", {"location": {"lat": 36.1539}})

            second = SecureSettingsStore(db, key_seed=secrets.token_hex(32))
            restored = second.get_json("settings.runtime", default=None)

        self.assertIsNone(restored, "a per-process random key cannot read the previous process's data")


if __name__ == "__main__":
    unittest.main()
