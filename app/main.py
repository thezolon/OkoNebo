"""
main.py — FastAPI application entry point.

Serves:
  - /api/*        JSON endpoints for weather data
  - /             Static frontend (app/static/)
  - /docs         Swagger UI
  - /openapi.json OpenAPI spec (for AI agent tool registration)
"""

from pathlib import Path
from collections import defaultdict, deque
import asyncio
import base64
import contextvars
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from typing import Any
from zoneinfo import available_timezones

import yaml
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app import weather_client as wc
from app.secure_settings import SecureSettingsStore

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency in older installs
    load_dotenv = None

# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

if load_dotenv is not None:
    load_dotenv(_CONFIG_PATH.parent / ".env")


def _load_config_file() -> dict[str, Any]:
    try:
        with open(_CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError:
        # Corrupted YAML should not crash the app at import time.
        return {}
    except FileNotFoundError:
        # Fresh clones / CI may not have config.yaml yet; runtime defaults still allow
        # tests and bootstrap endpoints to initialize safely.
        return {}


_cfg = _load_config_file()
_cfg_lock = None

PROVIDER_IDS = [
    "nws",
    "openweather",
    "pws",
    "tomorrow",
    "meteomatics",
    "weatherapi",
    "visualcrossing",
    "aviationweather",
    "noaa_tides",
]

PROVIDER_META: dict[str, dict[str, Any]] = {
    "nws": {"requires_api_key": False, "default_enabled": True},
    "openweather": {"requires_api_key": True, "default_enabled": False},
    "pws": {"requires_api_key": True, "default_enabled": False},
    "tomorrow": {"requires_api_key": True, "default_enabled": False},
    "meteomatics": {"requires_api_key": True, "default_enabled": False},
    "weatherapi": {"requires_api_key": True, "default_enabled": False},
    "visualcrossing": {"requires_api_key": True, "default_enabled": False},
    "aviationweather": {"requires_api_key": False, "default_enabled": True},
    "noaa_tides": {"requires_api_key": False, "default_enabled": True},
}

PROVIDER_CAPABILITIES: dict[str, list[str]] = {
    "nws": ["current", "forecast", "hourly", "alerts"],
    "openweather": ["owm_onecall", "tiles"],
    "pws": ["pws_current", "pws_trend"],
    "tomorrow": ["current", "forecast", "hourly"],
    "meteomatics": ["current"],
    "weatherapi": ["current", "forecast", "hourly"],
    "visualcrossing": ["current", "forecast", "hourly"],
    "aviationweather": ["metar"],
    "noaa_tides": ["tides"],
}

MAP_PROVIDER_IDS = ["esri_street", "osm", "carto_light", "carto_dark"]
PROVIDER_KEY_ENV = {
    "openweather": "OWM_API_KEY",
    "pws": "PWS_API_KEY",
    "tomorrow": "TOMORROW_API_KEY",
    "weatherapi": "WEATHERAPI_API_KEY",
    "visualcrossing": "VISUALCROSSING_API_KEY",
    "meteomatics": "METEOMATICS_API_KEY",
}

AGENT_SCOPE_DEFINITIONS: dict[str, str] = {
    "weather.read": "Read weather observations, forecasts, alerts, METAR, tides, and PWS feeds",
    "config.read": "Read bootstrap/config metadata",
    "stats.read": "Read upstream provider call counters",
    "debug.read": "Read debug telemetry payload",
}

AGENT_SCOPE_BY_PATH: dict[str, str] = {
    "/api/config": "config.read",
    "/api/bootstrap": "config.read",
    "/api/current": "weather.read",
    "/api/forecast": "weather.read",
    "/api/hourly": "weather.read",
    "/api/alerts": "weather.read",
    "/api/metar": "weather.read",
    "/api/tides": "weather.read",
    "/api/owm": "weather.read",
    "/api/pws": "weather.read",
    "/api/pws/trend": "weather.read",
    "/api/stats": "stats.read",
    "/api/debug": "debug.read",
    "/api/capabilities": "config.read",
}

AGENT_PROFILE_VERSION = "1.0"
_VALID_TIMEZONES = available_timezones()
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
_LABEL_RE = re.compile(r"^[\w\s\-.,()&'/:]{1,100}$")
_LOG_LEVEL = str(os.getenv("LOG_LEVEL") or "INFO").upper()
logging.basicConfig(level=getattr(logging, _LOG_LEVEL, logging.INFO), format="%(message)s")
LOGGER = logging.getLogger("okonebo")
_REQUEST_ID_CTX: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="n/a")


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _valid_timezone(value: str) -> bool:
    return bool(value) and value in _VALID_TIMEZONES


def _sanitize_label(label: Any, fallback: str, field_name: str) -> str:
    text = str(label or fallback).strip()
    if not text:
        text = fallback
    if len(text) > 100:
        raise HTTPException(status_code=400, detail=f"{field_name} must be 1-100 characters")
    if any(ord(ch) < 32 and ch not in {"\t", "\n", "\r"} for ch in text):
        raise HTTPException(status_code=400, detail=f"{field_name} contains invalid control characters")
    if not _LABEL_RE.match(text):
        raise HTTPException(status_code=400, detail=f"{field_name} contains unsupported characters")
    return text


def _sanitize_user_agent(value: Any, fallback: str) -> str:
    text = str(value if value is not None else fallback).strip()
    if not text:
        return str(fallback).strip() or "(weatherapp, local@example.com)"
    if len(text) > 256:
        raise HTTPException(status_code=400, detail="user_agent must be 1-256 characters")
    if any(ord(ch) < 32 and ch not in {"\t", "\n", "\r"} for ch in text):
        raise HTTPException(status_code=400, detail="user_agent contains invalid control characters")
    return text


def _sanitize_pws_stations(stations: Any) -> list[str]:
    raw_list = stations if isinstance(stations, list) else []
    cleaned = [str(item).strip() for item in raw_list if str(item).strip()]
    if len(cleaned) > 10:
        raise HTTPException(status_code=400, detail="pws.stations supports up to 10 station IDs")
    for station in cleaned:
        if len(station) > 64:
            raise HTTPException(status_code=400, detail="pws station IDs must be <= 64 characters")
    return cleaned


def _sanitize_username(value: Any, role: str) -> str:
    username = str(value or "").strip()
    if not username:
        return ""
    if not _USERNAME_RE.match(username):
        raise HTTPException(
            status_code=400,
            detail=f"{role} username must be 3-64 chars using letters, numbers, dot, underscore, or dash",
        )
    return username


def _validate_password_strength(password: str, role: str) -> None:
    if len(password) < 8:
        raise HTTPException(status_code=400, detail=f"{role} password must be at least 8 characters")
    has_alpha = any(ch.isalpha() for ch in password)
    has_digit = any(ch.isdigit() for ch in password)
    has_symbol = any(not ch.isalnum() for ch in password)
    if (has_alpha + has_digit + has_symbol) < 2:
        raise HTTPException(
            status_code=400,
            detail=f"{role} password must include at least two character classes (letters, digits, symbols)",
        )


def _validate_runtime_config(cfg: dict[str, Any]) -> None:
    location = cfg.get("location", {}) if isinstance(cfg.get("location", {}), dict) else {}
    tz = str(location.get("timezone") or "UTC").strip()
    if not _valid_timezone(tz):
        location["timezone"] = "UTC"
        cfg["location"] = location


def _request_id(request: Request | None) -> str:
    if request is None:
        return _REQUEST_ID_CTX.get()
    existing = getattr(request.state, "request_id", None)
    if existing:
        _REQUEST_ID_CTX.set(str(existing))
        return str(existing)
    incoming = str(request.headers.get("X-Request-ID") or "").strip()
    rid = incoming or secrets.token_hex(8)
    request.state.request_id = rid
    _REQUEST_ID_CTX.set(rid)
    return rid


def _log_event(event: str, request: Request | None = None, level: str = "info", **fields: Any) -> None:
    payload: dict[str, Any] = {
        "ts": int(time.time()),
        "event": event,
        "request_id": _request_id(request),
    }
    payload.update(fields)
    logger_fn = getattr(LOGGER, level, LOGGER.info)
    try:
        logger_fn(json.dumps(payload, sort_keys=True, default=str))
    except Exception:
        logger_fn(str(payload))


def _default_provider_config() -> dict[str, dict[str, Any]]:
    return {
        pid: {"enabled": bool(PROVIDER_META.get(pid, {}).get("default_enabled", False))}
        for pid in PROVIDER_IDS
    }


def _provider_api_key(pid: str) -> str:
    env_name = PROVIDER_KEY_ENV.get(pid)
    env_value = os.getenv(env_name, "") if env_name else ""
    if env_value:
        return str(env_value)
    return str(SECURE_STORE.get_json(f"providers.{pid}.api_key", "") or "")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


_settings_seed = (
    os.getenv("SETTINGS_ENCRYPTION_KEY")
    or str((_cfg.get("auth", {}) or {}).get("token_secret") or "")
    or str(_cfg.get("user_agent") or "okonebo-local")
)
SECURE_STORE = SecureSettingsStore(_CONFIG_PATH.parent / "secure_settings.db", key_seed=_settings_seed)


def _apply_config(cfg: dict[str, Any]) -> None:
    global LAT, LON, LABEL, TIMEZONE, USER_AGENT
    global OWM_KEY, PWS_PROVIDER, PWS_KEY, PWS_STATIONS, ALERT_LOCATIONS
    global AUTH_ENABLED, AUTH_REQUIRE_VIEWER_LOGIN, AUTH_USERS, AUTH_TOKEN_SECRET
    global PROVIDERS, FIRST_RUN_COMPLETE, MAP_PROVIDER
    global AGENT_TOKENS, REVOKED_AGENT_TOKEN_IDS, PROVIDER_PULL_CYCLES

    _validate_runtime_config(cfg)
    runtime_cfg = SECURE_STORE.get_json("settings.runtime", default={}) or {}

    location = runtime_cfg.get("location", {}) or cfg.get("location", {})
    LAT = _safe_float(location.get("lat", 0.0), 0.0)
    LON = _safe_float(location.get("lon", 0.0), 0.0)
    LABEL = str(location.get("label", "Configured Location"))
    configured_tz = str(location.get("timezone", "UTC"))
    TIMEZONE = configured_tz if _valid_timezone(configured_tz) else "UTC"
    USER_AGENT = str(runtime_cfg.get("user_agent") or cfg.get("user_agent", "(weatherapp, local@example.com)"))

    runtime_pws = runtime_cfg.get("pws", {}) if isinstance(runtime_cfg.get("pws", {}), dict) else {}
    runtime_providers = runtime_cfg.get("providers", {}) if isinstance(runtime_cfg.get("providers", {}), dict) else {}
    runtime_map = runtime_cfg.get("map", {}) if isinstance(runtime_cfg.get("map", {}), dict) else {}

    # .env overrides keep deploy secrets out of config.yaml for open-source use.
    OWM_KEY = _provider_api_key("openweather") or str(cfg.get("openweather", {}).get("api_key", ""))
    PWS_PROVIDER = str(runtime_pws.get("provider") or cfg.get("pws", {}).get("provider", "weather.com"))
    PWS_KEY = _provider_api_key("pws") or str(cfg.get("pws", {}).get("api_key", ""))
    PWS_STATIONS = list(runtime_pws.get("stations") or cfg.get("pws", {}).get("stations", []) or [])
    ALERT_LOCATIONS = list(
        runtime_cfg.get(
            "alert_locations",
            cfg.get(
            "alert_locations",
            [{"lat": LAT, "lon": LON, "label": LABEL}],
            ),
        )
        or [{"lat": LAT, "lon": LON, "label": LABEL}]
    )

    auth_cfg = runtime_cfg.get("auth", {}) if isinstance(runtime_cfg.get("auth", {}), dict) else {}
    if not auth_cfg:
        auth_cfg = cfg.get("auth", {}) if isinstance(cfg.get("auth", {}), dict) else {}
    AUTH_ENABLED = _env_bool("AUTH_ENABLED", bool(auth_cfg.get("enabled", False)))
    AUTH_REQUIRE_VIEWER_LOGIN = _env_bool(
        "AUTH_REQUIRE_VIEWER_LOGIN",
        bool(auth_cfg.get("require_viewer_login", False)),
    )
    AUTH_USERS = list(SECURE_STORE.get_json("auth.users", auth_cfg.get("users", [])) or [])

    env_admin_username = str(os.getenv("ADMIN_USERNAME") or "").strip()
    env_admin_password = str(os.getenv("ADMIN_PASSWORD") or "").strip()
    env_viewer_username = str(os.getenv("VIEWER_USERNAME") or "").strip()
    env_viewer_password = str(os.getenv("VIEWER_PASSWORD") or "").strip()

    def _upsert_env_user(role: str, username: str, password: str) -> None:
        if not username or not password:
            return
        match = None
        for user in AUTH_USERS:
            if str(user.get("username", "")).strip().lower() == username.lower():
                match = user
                break
        if match is None:
            match = {}
            AUTH_USERS.append(match)
        match["username"] = username
        match["role"] = role
        # Runtime env bootstrap supports plaintext fallback for first login.
        match["password"] = password
        match.pop("password_hash", None)

    _upsert_env_user("admin", env_admin_username, env_admin_password)
    _upsert_env_user("viewer", env_viewer_username, env_viewer_password)

    AUTH_TOKEN_SECRET = str(
        os.getenv("AUTH_TOKEN_SECRET")
        or auth_cfg.get("token_secret")
        or "dev-okonebo-secret"
    )
    AGENT_TOKENS = list(SECURE_STORE.get_json("auth.agent_tokens", []) or [])
    REVOKED_AGENT_TOKEN_IDS = set(
        str(token_id)
        for token_id in (SECURE_STORE.get_json("auth.revoked_agent_token_ids", []) or [])
        if str(token_id).strip()
    )

    provider_cfg = _default_provider_config()
    from_file = cfg.get("providers", {}) if isinstance(cfg.get("providers", {}), dict) else {}
    for pid in PROVIDER_IDS:
        if isinstance(from_file.get(pid), dict):
            provider_cfg[pid].update({"enabled": bool(from_file[pid].get("enabled", False))})
        if isinstance(runtime_providers.get(pid), dict):
            provider_cfg[pid].update({"enabled": bool(runtime_providers[pid].get("enabled", provider_cfg[pid]["enabled"]))})
    PROVIDERS = provider_cfg
    map_provider = str(runtime_map.get("provider") or cfg.get("map", {}).get("provider") or "esri_street")
    MAP_PROVIDER = map_provider if map_provider in MAP_PROVIDER_IDS else "esri_street"

    runtime_cache = runtime_cfg.get("cache", {}) if isinstance(runtime_cfg.get("cache", {}), dict) else {}
    provider_cycles_raw = runtime_cache.get("provider_ttl_seconds", {}) if isinstance(runtime_cache.get("provider_ttl_seconds", {}), dict) else {}
    PROVIDER_PULL_CYCLES = wc.set_provider_pull_cycles(provider_cycles_raw)

    FIRST_RUN_COMPLETE = bool(SECURE_STORE.get_json("bootstrap.first_run_complete", False))


_apply_config(_cfg)
SERVER_STARTED_AT = int(time.time())
DEBUG_STATE: dict[str, Any] = {
    "last_client_snapshot": None,
    "last_client_update": None,
}
AGENT_TOKENS: list[dict[str, Any]] = []
REVOKED_AGENT_TOKEN_IDS: set[str] = set()
RATE_LIMIT_WINDOW_SEC = 60
RATE_LIMIT_MAX_PER_WINDOW = 800
_RATE_LIMIT_BUCKETS: dict[str, deque[float]] = defaultdict(deque)
_RATE_LIMIT_BLOCKED_TOTAL = 0
_PROVIDER_OUTCOMES: dict[str, int] = defaultdict(int)
_OBSERVABILITY_RUNTIME: dict[str, Any] = {
    "last_overall": None,
    "last_change_ts": None,
    "transitions_total": 0,
    "history": [],
}

# Login brute-force protection — max attempts per IP per window.
_LOGIN_ATTEMPT_WINDOW_SEC = 300  # 5 minutes
_LOGIN_ATTEMPT_MAX = 10
_LOGIN_ATTEMPT_BUCKETS: dict[str, deque[float]] = defaultdict(deque)

# Token denylist — revoked tokens (by jti = payload_b64 prefix) with expiry.
# Uses a compact set; expired entries are pruned on each revocation write.
_TOKEN_DENYLIST: dict[str, float] = {}  # token_key -> exp epoch

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Weather API",
    description=(
        "Live weather data for a configured location, sourced from the "
        "National Weather Service (weather.gov). Provides current conditions, "
        "7-day and hourly forecasts, and active alerts. "
        "Designed for both human browser use and AI agent tool-calling."
    ),
    version="1.0.0",
    contact={"name": "zaipc", "email": "zolon@hackthemind.org"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_cfg_lock = asyncio.Lock()


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def _hash_password(password: str, salt: str | None = None) -> str:
    safe_salt = salt or secrets.token_hex(16)
    rounds = 120_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), safe_salt.encode(), rounds)
    return f"pbkdf2_sha256${rounds}${safe_salt}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, rounds_s, salt, expected_hex = stored.split("$", 3)
            rounds = int(rounds_s)
            digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), rounds).hex()
            return hmac.compare_digest(digest, expected_hex)
        except Exception:
            return False
    return hmac.compare_digest(password, stored)


def _find_user(username: str) -> dict[str, Any] | None:
    wanted = (username or "").strip().lower()
    for user in AUTH_USERS:
        name = str(user.get("username", "")).strip().lower()
        if name and name == wanted:
            return user
    return None


def _make_token(
    username: str,
    role: str,
    ttl_hours: int = 24,
    token_id: str | None = None,
    scopes: list[str] | None = None,
    token_type: str = "user",
) -> str:
    now = int(time.time())
    payload = {
        "sub": username,
        "role": role,
        "iat": now,
        "exp": now + (ttl_hours * 3600),
        "type": token_type,
    }
    if token_id:
        payload["jti"] = token_id
    if scopes:
        payload["scopes"] = [str(scope).strip() for scope in scopes if str(scope).strip()]
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(AUTH_TOKEN_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def _decode_token(token: str) -> dict[str, Any] | None:
    try:
        payload_b64, sig = token.split(".", 1)
        expected_sig = hmac.new(AUTH_TOKEN_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(_b64url_decode(payload_b64).decode())
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        if payload.get("type") == "agent":
            token_id = str(payload.get("jti") or "").strip()
            if token_id and token_id in REVOKED_AGENT_TOKEN_IDS:
                return None
        # Reject revoked tokens.
        if payload_b64 in _TOKEN_DENYLIST:
            return None
        return payload
    except Exception:
        return None


def _revoke_token(token: str) -> None:
    """Add a token's key to the denylist. Prune expired entries."""
    try:
        payload_b64, _ = token.split(".", 1)
        payload = json.loads(_b64url_decode(payload_b64).decode())
        exp = int(payload.get("exp", 0))
        now = int(time.time())
        # Prune already-expired entries.
        expired_keys = [k for k, v in _TOKEN_DENYLIST.items() if v < now]
        for k in expired_keys:
            del _TOKEN_DENYLIST[k]
        if exp > now:
            _TOKEN_DENYLIST[payload_b64] = exp
        if payload.get("type") == "agent":
            token_id = str(payload.get("jti") or "").strip()
            if token_id:
                REVOKED_AGENT_TOKEN_IDS.add(token_id)
                SECURE_STORE.set_json("auth.revoked_agent_token_ids", sorted(REVOKED_AGENT_TOKEN_IDS))
    except Exception:
        pass  # If token is malformed, nothing to revoke.


def _extract_bearer_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return None
    return auth_header.split(" ", 1)[1].strip() or None


def _request_identity(request: Request) -> dict[str, Any] | None:
    token = _extract_bearer_token(request)
    if not token:
        return None
    return _decode_token(token)


def _track_provider_outcome(endpoint: str, provider_id: str, outcome: str) -> None:
    key = f"{endpoint}:{provider_id}:{outcome}"
    _PROVIDER_OUTCOMES[key] += 1


def _observability_health(upstream_stats: dict[str, Any], active_rate_limit_clients: int) -> dict[str, Any]:
    retries = upstream_stats.get("retries", {}) if isinstance(upstream_stats.get("retries", {}), dict) else {}
    cache_runtime = (
        upstream_stats.get("cache_runtime", {})
        if isinstance(upstream_stats.get("cache_runtime", {}), dict)
        else {}
    )

    retry_attempted = 0
    retry_exhausted = 0
    for values in retries.values():
        if isinstance(values, dict):
            retry_attempted += int(values.get("attempted") or 0)
            retry_exhausted += int(values.get("exhausted") or 0)

    memory_hit = int(cache_runtime.get("memory_hit") or 0)
    sqlite_hit = int(cache_runtime.get("sqlite_hit") or 0)
    miss = int(cache_runtime.get("miss") or 0)
    hit_total = memory_hit + sqlite_hit
    cache_lookups = hit_total + miss
    cache_hit_ratio = (hit_total / cache_lookups) if cache_lookups > 0 else 1.0

    retry_pressure = "high" if retry_exhausted >= 3 else "elevated" if retry_attempted >= 8 else "normal"
    rate_limit_pressure = "high" if active_rate_limit_clients >= 50 else "elevated" if active_rate_limit_clients >= 10 else "normal"
    cache_pressure = "high" if cache_hit_ratio < 0.40 else "elevated" if cache_hit_ratio < 0.65 else "normal"

    overall = "healthy"
    if "high" in {retry_pressure, rate_limit_pressure, cache_pressure}:
        overall = "degraded"
    elif "elevated" in {retry_pressure, rate_limit_pressure, cache_pressure}:
        overall = "warning"

    return {
        "overall": overall,
        "retry_pressure": retry_pressure,
        "rate_limit_pressure": rate_limit_pressure,
        "cache_pressure": cache_pressure,
        "retry_attempted_total": retry_attempted,
        "retry_exhausted_total": retry_exhausted,
        "cache_hit_ratio": round(cache_hit_ratio, 3),
        "cache_lookups": cache_lookups,
    }


def _reset_observability_runtime() -> None:
    _OBSERVABILITY_RUNTIME["last_overall"] = None
    _OBSERVABILITY_RUNTIME["last_change_ts"] = None
    _OBSERVABILITY_RUNTIME["transitions_total"] = 0
    _OBSERVABILITY_RUNTIME["history"] = []


def _record_observability_state(obs: dict[str, Any]) -> None:
    now = time.time()
    overall = str(obs.get("overall") or "healthy")

    last = _OBSERVABILITY_RUNTIME.get("last_overall")
    if last is None:
        _OBSERVABILITY_RUNTIME["last_change_ts"] = now
    elif last != overall:
        _OBSERVABILITY_RUNTIME["transitions_total"] = int(_OBSERVABILITY_RUNTIME.get("transitions_total") or 0) + 1
        _OBSERVABILITY_RUNTIME["last_change_ts"] = now

    _OBSERVABILITY_RUNTIME["last_overall"] = overall

    history = list(_OBSERVABILITY_RUNTIME.get("history") or [])
    history.append({"ts": now, "overall": overall})
    cutoff = now - 3600  # Keep one hour in memory.
    history = [entry for entry in history if float(entry.get("ts") or 0) >= cutoff]
    if len(history) > 240:
        history = history[-240:]
    _OBSERVABILITY_RUNTIME["history"] = history

    win_cutoff = now - 600
    recent = [entry for entry in history if float(entry.get("ts") or 0) >= win_cutoff]
    flaps = 0
    prev_overall = None
    for entry in recent:
        cur = str(entry.get("overall") or "")
        if prev_overall is not None and cur and cur != prev_overall:
            flaps += 1
        if cur:
            prev_overall = cur

    last_change_ts = float(_OBSERVABILITY_RUNTIME.get("last_change_ts") or now)
    obs["transitions_total"] = int(_OBSERVABILITY_RUNTIME.get("transitions_total") or 0)
    obs["flaps_10m"] = flaps
    obs["seconds_since_last_change"] = int(max(now - last_change_ts, 0))
    obs["stability"] = "flapping" if flaps >= 4 else "watch" if flaps >= 2 else "stable"


def _observability_recommendations(obs: dict[str, Any]) -> list[str]:
    recs: list[str] = []

    retry_pressure = str(obs.get("retry_pressure") or "normal")
    cache_pressure = str(obs.get("cache_pressure") or "normal")
    rate_limit_pressure = str(obs.get("rate_limit_pressure") or "normal")
    stability = str(obs.get("stability") or "stable")
    flaps = int(obs.get("flaps_10m") or 0)

    if retry_pressure == "high":
        recs.append("High retry pressure: verify upstream provider status and credentials, then consider increasing pull cycles.")
    elif retry_pressure == "elevated":
        recs.append("Elevated retries: monitor provider errors and watch for rate-limit trends.")

    if cache_pressure == "high":
        recs.append("Low cache hit ratio: increase provider pull-cycle TTLs or investigate cache invalidation churn.")
    elif cache_pressure == "elevated":
        recs.append("Cache pressure elevated: confirm cache lookups are not dominated by one-off keys.")

    if rate_limit_pressure == "high":
        recs.append("Rate-limit pressure is high: reduce API request bursts and review client polling behavior.")
    elif rate_limit_pressure == "elevated":
        recs.append("Rate-limit pressure elevated: watch active client count and adjust limits if needed.")

    if stability == "flapping":
        recs.insert(0, f"Observability is flapping ({flaps} transitions in 10m): investigate bursty traffic or unstable upstreams.")
    elif stability == "watch":
        recs.insert(0, "Observability recently shifted states: continue monitoring for another refresh cycle.")

    if not recs:
        recs.append("System telemetry looks healthy. Continue normal monitoring.")

    return recs


@app.middleware("http")
async def api_rate_limiter(request: Request, call_next):
    global _RATE_LIMIT_BLOCKED_TOTAL

    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)

    req_id = _request_id(request)

    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW_SEC

    bucket = _RATE_LIMIT_BUCKETS[client_ip]
    while bucket and bucket[0] < cutoff:
        bucket.popleft()

    if len(bucket) >= RATE_LIMIT_MAX_PER_WINDOW:
        _RATE_LIMIT_BLOCKED_TOTAL += 1
        _log_event(
            "rate_limit.blocked",
            request,
            level="warning",
            path=path,
            method=request.method.upper(),
            client_ip=client_ip,
        )
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": "15", "X-Request-ID": req_id},
            content={
                "detail": "Rate limit exceeded",
                "window_seconds": RATE_LIMIT_WINDOW_SEC,
                "max_requests": RATE_LIMIT_MAX_PER_WINDOW,
            },
        )

    bucket.append(now)
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response


@app.middleware("http")
async def api_auth_guard(request: Request, call_next):
    path = request.url.path
    method = request.method.upper()
    req_id = _request_id(request)

    if not path.startswith("/api/"):
        return await call_next(request)

    if not AUTH_ENABLED:
        return await call_next(request)

    if path.startswith("/api/auth/"):
        return await call_next(request)

    if path == "/api/capabilities":
        return await call_next(request)

    identity = _request_identity(request)
    admin_only = (path == "/api/settings" and method == "POST") or path.startswith("/api/agent-tokens")

    if AUTH_REQUIRE_VIEWER_LOGIN and identity is None:
        _log_event("auth.denied", request, level="warning", path=path, reason="viewer_login_required")
        return JSONResponse(
            status_code=401,
            headers={"X-Request-ID": req_id},
            content={"detail": "Authentication required"},
        )

    if identity is not None and identity.get("role") == "agent":
        required_scope = AGENT_SCOPE_BY_PATH.get(path)
        if not required_scope:
            _log_event("auth.denied", request, level="warning", path=path, reason="agent_endpoint_disallowed")
            return JSONResponse(
                status_code=403,
                headers={"X-Request-ID": req_id},
                content={"detail": "Agent token cannot access this endpoint"},
            )
        granted = {str(scope).strip() for scope in (identity.get("scopes") or []) if str(scope).strip()}
        if required_scope not in granted:
            _log_event(
                "auth.denied",
                request,
                level="warning",
                path=path,
                reason="agent_scope_missing",
                required_scope=required_scope,
            )
            return JSONResponse(
                status_code=403,
                headers={"X-Request-ID": req_id},
                content={
                    "detail": "Agent token missing required scope",
                    "required_scope": required_scope,
                },
            )

    if admin_only:
        if identity is None:
            _log_event("auth.denied", request, level="warning", path=path, reason="admin_login_required")
            return JSONResponse(
                status_code=401,
                headers={"X-Request-ID": req_id},
                content={"detail": "Admin login required"},
            )
        if identity.get("role") != "admin":
            _log_event("auth.denied", request, level="warning", path=path, reason="admin_role_required")
            return JSONResponse(
                status_code=403,
                headers={"X-Request-ID": req_id},
                content={"detail": "Admin role required"},
            )

    return await call_next(request)

# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@app.get(
    "/api/auth/config",
    summary="Auth mode configuration",
    description="Returns whether auth is enabled and whether viewer login is required.",
    tags=["Auth"],
)
async def api_auth_config():
    return {
        "enabled": AUTH_ENABLED,
        "require_viewer_login": AUTH_REQUIRE_VIEWER_LOGIN,
    }


@app.post(
    "/api/auth/login",
    summary="Login",
    description="Login with username/password and receive bearer token.",
    tags=["Auth"],
)
async def api_auth_login(payload: dict[str, Any] = Body(...), request: Request = None):
    if not AUTH_ENABLED:
        raise HTTPException(status_code=400, detail="Authentication is disabled")

    # Brute-force protection: max LOGIN_ATTEMPT_MAX attempts per IP per window.
    client_ip = (request.client.host if request and request.client else "unknown")
    now = time.time()
    cutoff = now - _LOGIN_ATTEMPT_WINDOW_SEC
    bucket = _LOGIN_ATTEMPT_BUCKETS[client_ip]
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= _LOGIN_ATTEMPT_MAX:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": "300"},
        )
    bucket.append(now)

    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    user = _find_user(username)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    stored = str(user.get("password_hash") or user.get("password") or "")
    if not stored or not _verify_password(password, stored):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    role = str(user.get("role") or "viewer")
    token = _make_token(username=str(user.get("username") or username), role=role)
    return {
        "token": token,
        "user": {
            "username": str(user.get("username") or username),
            "role": role,
        },
    }


@app.post(
    "/api/auth/logout",
    summary="Logout",
    description=(
        "Revoke the current bearer token server-side. "
        "The token is added to an in-memory denylist until it expires naturally."
    ),
    tags=["Auth"],
)
async def api_auth_logout(request: Request):
    token = _extract_bearer_token(request)
    if token:
        _revoke_token(token)
    return {"ok": True}


@app.get(
    "/api/auth/me",
    summary="Current auth identity",
    description="Returns the current authenticated user from bearer token.",
    tags=["Auth"],
)
async def api_auth_me(request: Request):
    identity = _request_identity(request)
    if not identity:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {
        "username": identity.get("sub"),
        "role": identity.get("role"),
        "exp": identity.get("exp"),
    }


def _require_admin_identity(request: Request) -> dict[str, Any]:
    if not AUTH_ENABLED:
        raise HTTPException(status_code=400, detail="Enable auth before managing agent tokens")
    identity = _request_identity(request)
    if not identity:
        raise HTTPException(status_code=401, detail="Admin login required")
    if identity.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return identity


@app.get(
    "/api/capabilities",
    summary="Agent capability metadata",
    description="Lists available API tool surfaces and scope requirements for agent clients.",
    tags=["Config"],
)
async def api_capabilities():
    return {
        "service": "okonebo",
        "version": "1.0.0",
        "auth": {
            "enabled": AUTH_ENABLED,
            "require_viewer_login": AUTH_REQUIRE_VIEWER_LOGIN,
            "agent_scopes": AGENT_SCOPE_DEFINITIONS,
        },
        "tools": [
            {"name": "get_config", "endpoint": "/api/config", "scope": "config.read"},
            {"name": "get_bootstrap", "endpoint": "/api/bootstrap", "scope": "config.read"},
            {"name": "get_current", "endpoint": "/api/current", "scope": "weather.read"},
            {"name": "get_forecast", "endpoint": "/api/forecast", "scope": "weather.read"},
            {"name": "get_hourly", "endpoint": "/api/hourly", "scope": "weather.read"},
            {"name": "get_alerts", "endpoint": "/api/alerts", "scope": "weather.read"},
            {"name": "get_metar", "endpoint": "/api/metar", "scope": "weather.read"},
            {"name": "get_tides", "endpoint": "/api/tides", "scope": "weather.read"},
            {"name": "get_pws", "endpoint": "/api/pws", "scope": "weather.read"},
            {"name": "get_pws_trend", "endpoint": "/api/pws/trend", "scope": "weather.read"},
            {"name": "get_stats", "endpoint": "/api/stats", "scope": "stats.read"},
            {"name": "get_debug", "endpoint": "/api/debug", "scope": "debug.read"},
        ],
    }


@app.get(
    "/.well-known/okonebo-agent.json",
    summary="Agent auto-configuration profile",
    description="Machine-readable profile that agents can load to self-configure against OkoNebo.",
    tags=["Config"],
)
async def api_agent_profile():
    base_url = "http://localhost:8888"
    return {
        "service": "okonebo",
        "profile_version": AGENT_PROFILE_VERSION,
        "base_url": base_url,
        "auth": {
            "type": "bearer",
            "token_kind": "agent",
            "token_creation_endpoint": "/api/agent-tokens",
            "token_revoke_endpoint": "/api/agent-tokens/{token_id}",
            "required_header": "Authorization: Bearer <agent_token>",
            "scopes": AGENT_SCOPE_DEFINITIONS,
        },
        "discovery": {
            "capabilities_endpoint": "/api/capabilities",
            "openapi": "/openapi.json",
            "swagger": "/docs",
        },
        "manual": {
            "human_page": "/agent-manual.html",
            "integration_guide": "/agent-integrations.html",
        },
        "tools": [
            {"name": "get_current", "method": "GET", "path": "/api/current", "scope": "weather.read"},
            {"name": "get_forecast", "method": "GET", "path": "/api/forecast", "scope": "weather.read"},
            {"name": "get_hourly", "method": "GET", "path": "/api/hourly", "scope": "weather.read"},
            {"name": "get_alerts", "method": "GET", "path": "/api/alerts", "scope": "weather.read"},
            {"name": "get_metar", "method": "GET", "path": "/api/metar", "scope": "weather.read"},
            {"name": "get_tides", "method": "GET", "path": "/api/tides", "scope": "weather.read"},
            {"name": "get_pws", "method": "GET", "path": "/api/pws", "scope": "weather.read"},
            {"name": "get_pws_trend", "method": "GET", "path": "/api/pws/trend", "scope": "weather.read"},
            {"name": "get_config", "method": "GET", "path": "/api/config", "scope": "config.read"},
            {"name": "get_bootstrap", "method": "GET", "path": "/api/bootstrap", "scope": "config.read"},
            {"name": "get_stats", "method": "GET", "path": "/api/stats", "scope": "stats.read"},
            {"name": "get_debug", "method": "GET", "path": "/api/debug", "scope": "debug.read"},
        ],
        "agent_behavior": {
            "rules": [
                "Prefer read-only endpoints unless explicitly instructed otherwise.",
                "Do not call admin endpoints using agent tokens.",
                "Handle 502 responses as provider-fallback failures and report attempted providers.",
                "Use /api/capabilities to validate scope coverage before tool calls.",
            ]
        },
    }


@app.get(
    "/.well-known/okonebo-agent-instructions.txt",
    summary="Plain-text agent instructions",
    description="Human-readable and model-ingestible instruction block for OkoNebo-compatible agents.",
    tags=["Config"],
)
async def api_agent_instructions_txt():
    lines = [
        "OkoNebo Agent Instructions",
        "",
        "Identity:",
        "- You are an agent consuming OkoNebo weather APIs.",
        "- Base URL: http://localhost:8888",
        "",
        "Authentication:",
        "- Send Authorization: Bearer <agent_token>.",
        "- Use only granted scopes: weather.read, config.read, stats.read, debug.read.",
        "",
        "Discovery:",
        "- Load /.well-known/okonebo-agent.json first.",
        "- Validate tools/scopes via GET /api/capabilities.",
        "",
        "Tool Mapping:",
        "- get_current -> GET /api/current",
        "- get_forecast -> GET /api/forecast",
        "- get_hourly -> GET /api/hourly",
        "- get_alerts -> GET /api/alerts",
        "- get_metar -> GET /api/metar",
        "- get_tides -> GET /api/tides?days=2",
        "- get_stats -> GET /api/stats",
        "- get_config -> GET /api/config",
        "- get_bootstrap -> GET /api/bootstrap",
        "",
        "Runtime Rules:",
        "- Treat HTTP 401/403 as auth/scope errors and stop retry loops.",
        "- Treat HTTP 502 on weather routes as upstream provider failure; report fallback status.",
        "- Keep calls read-only unless operator explicitly authorizes admin mutation.",
        "",
        "Operator Docs:",
        "- Human manual: /agent-manual.html",
        "- Integration guide: /agent-integrations.html",
    ]
    return Response(content="\n".join(lines), media_type="text/plain; charset=utf-8")


@app.get(
    "/api/agent-tokens",
    summary="List managed agent tokens",
    description="Returns managed AI agent tokens metadata (token values are never returned).",
    tags=["Auth"],
)
async def api_agent_tokens_get(request: Request):
    _require_admin_identity(request)
    return {
        "tokens": AGENT_TOKENS,
        "revoked_ids": sorted(REVOKED_AGENT_TOKEN_IDS),
        "allowed_scopes": AGENT_SCOPE_DEFINITIONS,
    }


@app.post(
    "/api/agent-tokens",
    summary="Create managed agent token",
    description="Creates a scoped AI agent bearer token. Token value is returned only once.",
    tags=["Auth"],
)
async def api_agent_tokens_post(request: Request, payload: dict[str, Any] = Body(...)):
    identity = _require_admin_identity(request)

    name = str(payload.get("name") or "").strip() or "Agent Token"
    ttl_hours = int(payload.get("ttl_hours") or 24)
    ttl_hours = max(1, min(ttl_hours, 24 * 90))
    scopes = payload.get("scopes") or ["weather.read", "config.read", "stats.read"]
    if not isinstance(scopes, list):
        raise HTTPException(status_code=400, detail="scopes must be a list")
    clean_scopes = [str(scope).strip() for scope in scopes if str(scope).strip()]
    unknown_scopes = [scope for scope in clean_scopes if scope not in AGENT_SCOPE_DEFINITIONS]
    if unknown_scopes:
        raise HTTPException(status_code=400, detail=f"Unsupported scopes: {', '.join(unknown_scopes)}")

    token_id = secrets.token_hex(12)
    now = int(time.time())
    exp = now + (ttl_hours * 3600)
    token = _make_token(
        username=f"agent:{token_id}",
        role="agent",
        ttl_hours=ttl_hours,
        token_id=token_id,
        scopes=clean_scopes,
        token_type="agent",
    )

    record = {
        "id": token_id,
        "name": name,
        "scopes": clean_scopes,
        "created_at": now,
        "expires_at": exp,
        "created_by": str(identity.get("sub") or "admin"),
        "revoked": False,
    }
    AGENT_TOKENS.append(record)
    SECURE_STORE.set_json("auth.agent_tokens", AGENT_TOKENS)
    _log_event(
        "token.created",
        request,
        token_id=token_id,
        created_by=str(identity.get("sub") or "admin"),
        scope_count=len(clean_scopes),
        ttl_hours=ttl_hours,
    )

    return {
        "id": token_id,
        "token": token,
        "name": name,
        "scopes": clean_scopes,
        "expires_at": exp,
    }


@app.delete(
    "/api/agent-tokens/{token_id}",
    summary="Revoke managed agent token",
    description="Revokes an AI agent token by token id.",
    tags=["Auth"],
)
async def api_agent_tokens_delete(token_id: str, request: Request):
    _require_admin_identity(request)
    wanted = str(token_id or "").strip()
    if not wanted:
        raise HTTPException(status_code=400, detail="token_id is required")

    updated = False
    for item in AGENT_TOKENS:
        if str(item.get("id") or "") == wanted:
            item["revoked"] = True
            updated = True
            break

    REVOKED_AGENT_TOKEN_IDS.add(wanted)
    SECURE_STORE.set_json("auth.agent_tokens", AGENT_TOKENS)
    SECURE_STORE.set_json("auth.revoked_agent_token_ids", sorted(REVOKED_AGENT_TOKEN_IDS))
    _log_event("token.revoked", request, token_id=wanted, updated=updated)

    return {"ok": True, "token_id": wanted, "updated": updated}

@app.get(
    "/api/bootstrap",
    summary="Bootstrap state",
    description="Returns whether first-run setup is required and auth mode information.",
    tags=["Config"],
)
async def api_bootstrap():
    return {
        "first_run_required": not FIRST_RUN_COMPLETE,
        "auth": {
            "enabled": AUTH_ENABLED,
            "require_viewer_login": AUTH_REQUIRE_VIEWER_LOGIN,
        },
        "providers": {
            pid: {
                "enabled": bool(PROVIDERS.get(pid, {}).get("enabled", False)),
                "requires_api_key": bool(PROVIDER_META.get(pid, {}).get("requires_api_key", False)),
                "configured": (
                    not bool(PROVIDER_META.get(pid, {}).get("requires_api_key", False))
                    or bool(_provider_api_key(pid))
                ),
                "capabilities": PROVIDER_CAPABILITIES.get(pid, []),
            }
            for pid in PROVIDER_IDS
        },
        "map": {
            "provider": MAP_PROVIDER,
            "options": MAP_PROVIDER_IDS,
        },
    }


@app.get(
    "/api/config",
    summary="Location configuration",
    description="Returns the configured location coordinates, label, and timezone.",
    tags=["Weather"],
)
async def api_config():
    return {
        "lat": LAT,
        "lon": LON,
        "label": LABEL,
        "timezone": TIMEZONE,
        "alert_locations": ALERT_LOCATIONS,
        "owm_available": bool(PROVIDERS.get("openweather", {}).get("enabled") and OWM_KEY),
        "pws_available": bool(PROVIDERS.get("pws", {}).get("enabled") and PWS_KEY and PWS_STATIONS),
        "pws_provider": PWS_PROVIDER,
        "pws_station_count": len(PWS_STATIONS),
        "map_provider": MAP_PROVIDER,
        "providers": {pid: {"enabled": bool(PROVIDERS.get(pid, {}).get("enabled", False))} for pid in PROVIDER_IDS},
    }


@app.get(
    "/api/current",
    summary="Current surface observations",
    description=(
        "Latest surface observation from the nearest NWS automated station. "
        "Includes temperature (°F), feels-like, dewpoint, humidity, wind, "
        "barometric pressure, visibility, and cloud layers. Cached 5 minutes."
    ),
    tags=["Weather"],
)
async def api_current():
    attempted: list[str] = []
    provider_errors: dict[str, str] = {}

    async def _attempt(provider_id: str, fetcher):
        attempted.append(provider_id)
        started = time.time()
        try:
            payload = await fetcher()
            _track_provider_outcome("current", provider_id, "success")
            _log_event(
                "provider.attempt",
                None,
                endpoint="current",
                provider=provider_id,
                success=True,
                duration_ms=int((time.time() - started) * 1000),
            )
            if isinstance(payload, dict):
                payload["source"] = provider_id
            return payload
        except Exception as exc:
            provider_errors[provider_id] = str(exc)
            _track_provider_outcome("current", provider_id, "error")
            _log_event(
                "provider.attempt",
                None,
                level="warning",
                endpoint="current",
                provider=provider_id,
                success=False,
                duration_ms=int((time.time() - started) * 1000),
                error=str(exc),
            )
            return None

    if PROVIDERS.get("nws", {}).get("enabled"):
        payload = await _attempt("nws", lambda: wc.get_current(LAT, LON, USER_AGENT))
        if payload is not None:
            return payload

    if PROVIDERS.get("weatherapi", {}).get("enabled"):
        weatherapi_key = _provider_api_key("weatherapi")
        if weatherapi_key:
            payload = await _attempt("weatherapi", lambda: wc.get_weatherapi_current(LAT, LON, weatherapi_key))
            if payload is not None:
                return payload

    if PROVIDERS.get("tomorrow", {}).get("enabled"):
        tomorrow_key = _provider_api_key("tomorrow")
        if tomorrow_key:
            payload = await _attempt("tomorrow", lambda: wc.get_tomorrow_current(LAT, LON, tomorrow_key))
            if payload is not None:
                return payload

    if PROVIDERS.get("visualcrossing", {}).get("enabled"):
        visualcrossing_key = _provider_api_key("visualcrossing")
        if visualcrossing_key:
            payload = await _attempt("visualcrossing", lambda: wc.get_visualcrossing_current(LAT, LON, visualcrossing_key))
            if payload is not None:
                return payload

    if PROVIDERS.get("meteomatics", {}).get("enabled"):
        meteomatics_key = _provider_api_key("meteomatics")
        if meteomatics_key and ":" in meteomatics_key:
            payload = await _attempt("meteomatics", lambda: wc.get_meteomatics_current(LAT, LON, meteomatics_key))
            if payload is not None:
                return payload

    details = {
        "detail": "No enabled/working current-conditions provider",
        "attempted": attempted,
        "errors": provider_errors,
    }
    raise HTTPException(status_code=502, detail=details)


@app.get(
    "/api/forecast",
    summary="7-day forecast",
    description=(
        "NWS 7-day forecast broken into day/night periods. Each period includes "
        "temperature, wind, precipitation probability, short and detailed text "
        "forecasts, and an icon URL. Cached 15 minutes."
    ),
    tags=["Weather"],
)
async def api_forecast():
    attempted: list[str] = []
    provider_errors: dict[str, str] = {}

    async def _attempt(provider_id: str, fetcher):
        attempted.append(provider_id)
        started = time.time()
        try:
            payload = await fetcher()
            _track_provider_outcome("forecast", provider_id, "success")
            _log_event(
                "provider.attempt",
                None,
                endpoint="forecast",
                provider=provider_id,
                success=True,
                duration_ms=int((time.time() - started) * 1000),
            )
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        item.setdefault("source", provider_id)
            return payload
        except Exception as exc:
            provider_errors[provider_id] = str(exc)
            _track_provider_outcome("forecast", provider_id, "error")
            _log_event(
                "provider.attempt",
                None,
                level="warning",
                endpoint="forecast",
                provider=provider_id,
                success=False,
                duration_ms=int((time.time() - started) * 1000),
                error=str(exc),
            )
            return None

    if PROVIDERS.get("nws", {}).get("enabled"):
        payload = await _attempt("nws", lambda: wc.get_forecast(LAT, LON, USER_AGENT))
        if payload is not None:
            return payload

    if PROVIDERS.get("weatherapi", {}).get("enabled"):
        weatherapi_key = _provider_api_key("weatherapi")
        if weatherapi_key:
            payload = await _attempt("weatherapi", lambda: wc.get_weatherapi_forecast(LAT, LON, weatherapi_key))
            if payload is not None:
                return payload

    if PROVIDERS.get("tomorrow", {}).get("enabled"):
        tomorrow_key = _provider_api_key("tomorrow")
        if tomorrow_key:
            payload = await _attempt("tomorrow", lambda: wc.get_tomorrow_forecast(LAT, LON, tomorrow_key))
            if payload is not None:
                return payload

    if PROVIDERS.get("visualcrossing", {}).get("enabled"):
        visualcrossing_key = _provider_api_key("visualcrossing")
        if visualcrossing_key:
            payload = await _attempt("visualcrossing", lambda: wc.get_visualcrossing_forecast(LAT, LON, visualcrossing_key))
            if payload is not None:
                return payload

    details = {
        "detail": "No enabled/working forecast provider",
        "attempted": attempted,
        "errors": provider_errors,
    }
    raise HTTPException(status_code=502, detail=details)


@app.get(
    "/api/hourly",
    summary="48-hour hourly forecast",
    description=(
        "Hourly forecast for the next 48 hours. Each entry includes start time, "
        "temperature (°F), wind speed/direction, precipitation probability, and "
        "short forecast text. Cached 15 minutes."
    ),
    tags=["Weather"],
)
async def api_hourly():
    attempted: list[str] = []
    provider_errors: dict[str, str] = {}

    async def _attempt(provider_id: str, fetcher):
        attempted.append(provider_id)
        started = time.time()
        try:
            payload = await fetcher()
            _track_provider_outcome("hourly", provider_id, "success")
            _log_event(
                "provider.attempt",
                None,
                endpoint="hourly",
                provider=provider_id,
                success=True,
                duration_ms=int((time.time() - started) * 1000),
            )
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        item.setdefault("source", provider_id)
            return payload
        except Exception as exc:
            provider_errors[provider_id] = str(exc)
            _track_provider_outcome("hourly", provider_id, "error")
            _log_event(
                "provider.attempt",
                None,
                level="warning",
                endpoint="hourly",
                provider=provider_id,
                success=False,
                duration_ms=int((time.time() - started) * 1000),
                error=str(exc),
            )
            return None

    if PROVIDERS.get("nws", {}).get("enabled"):
        payload = await _attempt("nws", lambda: wc.get_hourly(LAT, LON, USER_AGENT))
        if payload is not None:
            return payload

    if PROVIDERS.get("weatherapi", {}).get("enabled"):
        weatherapi_key = _provider_api_key("weatherapi")
        if weatherapi_key:
            payload = await _attempt("weatherapi", lambda: wc.get_weatherapi_hourly(LAT, LON, weatherapi_key))
            if payload is not None:
                return payload

    if PROVIDERS.get("tomorrow", {}).get("enabled"):
        tomorrow_key = _provider_api_key("tomorrow")
        if tomorrow_key:
            payload = await _attempt("tomorrow", lambda: wc.get_tomorrow_hourly(LAT, LON, tomorrow_key))
            if payload is not None:
                return payload

    if PROVIDERS.get("visualcrossing", {}).get("enabled"):
        visualcrossing_key = _provider_api_key("visualcrossing")
        if visualcrossing_key:
            payload = await _attempt("visualcrossing", lambda: wc.get_visualcrossing_hourly(LAT, LON, visualcrossing_key))
            if payload is not None:
                return payload

    details = {
        "detail": "No enabled/working hourly provider",
        "attempted": attempted,
        "errors": provider_errors,
    }
    raise HTTPException(status_code=502, detail=details)


@app.get(
    "/api/metar",
    summary="Aviation METAR observation",
    description=(
        "Nearest METAR surface observation from aviationweather.gov. "
        "Includes temperature, dewpoint, wind, pressure, visibility, ceiling, "
        "raw METAR string, and IFR/VFR flight category.  Keyless — no API key needed. "
        "Cached 10 minutes."
    ),
    tags=["Weather"],
)
async def api_metar():
    if not PROVIDERS.get("aviationweather", {}).get("enabled"):
        return JSONResponse(
            status_code=200,
            content={"available": False, "error": "AviationWeather provider disabled"},
        )
    try:
        result = await wc.get_aviationweather_metar(LAT, LON, USER_AGENT)
        result["source"] = "aviationweather"
        return result
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/api/tides",
    summary="NOAA tide predictions",
    description=(
        "Tide predictions (high/low) for the nearest NOAA CO-OPS tide station. "
        "Returns up to 7 days of predictions.  Keyless — no API key needed. "
        "Cached 30 minutes."
    ),
    tags=["Weather"],
)
async def api_tides(days: int = Query(default=2, ge=1, le=7)):
    if not PROVIDERS.get("noaa_tides", {}).get("enabled"):
        return JSONResponse(
            status_code=200,
            content={"available": False, "error": "NOAA Tides provider disabled"},
        )
    try:
        return await wc.get_noaa_tides(LAT, LON, days=days)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/api/alerts",
    summary="Active weather alerts",
    description=(
        "All currently active NWS weather alerts for the configured home/work monitoring points. "
        "Each alert includes event type, severity, urgency, certainty, "
        "headline, description, instructions, expiry time, and GeoJSON geometry "
        "when polygon data is available. Duplicate alerts are de-duplicated and tagged "
        "with the monitored locations they affect. "
        "Returns an empty list when no alerts are active. Cached 5 minutes."
    ),
    tags=["Weather"],
)
async def api_alerts():
    try:
        return await wc.get_alerts_multi(ALERT_LOCATIONS, USER_AGENT)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/api/owm",
    summary="OpenWeather One Call 3.0",
    description=(
        "Current conditions, 48-hour hourly, 8-day daily, and alerts from "
        "OpenWeather One Call 3.0. Supplements NWS data with UV index, "
        "sunrise/sunset, and extended forecast. Cached 10 minutes."
    ),
    tags=["Weather"],
)
async def api_owm():
    if not PROVIDERS.get("openweather", {}).get("enabled"):
        return JSONResponse(
            status_code=200,
            content={
                "available": False,
                "error": "OpenWeather provider disabled",
                "timezone": TIMEZONE,
                "current": None,
                "hourly": [],
                "daily": [],
                "alerts": [],
            },
        )
    try:
        return await wc.get_owm_onecall(LAT, LON, OWM_KEY)
    except Exception as exc:
        # Graceful degradation: keep UI functional while OWM key/plan propagates.
        return JSONResponse(
            status_code=200,
            content={
                "available": False,
                "error": str(exc),
                "timezone": TIMEZONE,
                "current": None,
                "hourly": [],
                "daily": [],
                "alerts": [],
            },
        )


@app.get(
    "/api/pws",
    summary="Personal Weather Station observations",
    description=(
        "Latest observations from configured personal weather stations. "
        "Designed for direct hyperlocal station data. Cached 2 minutes."
    ),
    tags=["Weather"],
)
async def api_pws():
    if not PROVIDERS.get("pws", {}).get("enabled") or not PWS_KEY or not PWS_STATIONS:
        return {
            "provider": PWS_PROVIDER,
            "stations": [],
            "errors": [],
            "updated_at": time.time(),
            "available": False,
        }
    try:
        return await wc.get_pws_observations(PWS_PROVIDER, PWS_STATIONS, PWS_KEY)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/api/pws/trend",
    summary="PWS station trends",
    description=(
        "Returns recent PWS observation points for each configured station to "
        "drive sparkline and trend indicators (1-24 hour window)."
    ),
    tags=["Weather"],
)
async def api_pws_trend(hours: int = Query(default=3, ge=1, le=24)):
    if not PROVIDERS.get("pws", {}).get("enabled") or not PWS_KEY or not PWS_STATIONS:
        return {
            "provider": PWS_PROVIDER,
            "hours": max(1, min(int(hours), 24)),
            "stations": [],
            "errors": [],
            "updated_at": time.time(),
            "available": False,
        }
    try:
        return await wc.get_pws_trend(PWS_PROVIDER, PWS_STATIONS, PWS_KEY, hours=hours)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/api/stats",
    summary="Upstream provider call stats",
    description="Returns per-provider upstream call counts since server start.",
    tags=["Debug"],
)
async def api_stats():
    return wc.get_upstream_call_stats()


@app.get(
    "/api/debug",
    summary="Debug and metrics snapshot",
    description=(
        "Returns server runtime details plus the most recent client-side metrics "
        "snapshot posted by the browser. Useful for remote diagnostics without "
        "opening browser dev tools."
    ),
    tags=["Debug"],
)
async def api_debug():
    active_rate_limit_clients = 0
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW_SEC
    for client_ip, bucket in list(_RATE_LIMIT_BUCKETS.items()):
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if bucket:
            active_rate_limit_clients += 1

    upstream_stats = wc.get_upstream_call_stats()
    observability = _observability_health(upstream_stats, active_rate_limit_clients)
    _record_observability_state(observability)
    observability["recommendations"] = _observability_recommendations(observability)

    return {
        "server_time": int(time.time()),
        "server_started_at": SERVER_STARTED_AT,
        "uptime_seconds": int(time.time()) - SERVER_STARTED_AT,
        "location": {
            "lat": LAT,
            "lon": LON,
            "label": LABEL,
            "timezone": TIMEZONE,
        },
        "integrations": {
            "owm_available": bool(PROVIDERS.get("openweather", {}).get("enabled") and OWM_KEY),
            "pws_available": bool(PROVIDERS.get("pws", {}).get("enabled") and PWS_KEY and PWS_STATIONS),
            "pws_provider": PWS_PROVIDER,
            "pws_station_count": len(PWS_STATIONS),
        },
        "upstream_calls": upstream_stats,
        "rate_limit": {
            "window_seconds": RATE_LIMIT_WINDOW_SEC,
            "max_requests_per_window": RATE_LIMIT_MAX_PER_WINDOW,
            "active_clients": active_rate_limit_clients,
            "blocked_total": _RATE_LIMIT_BLOCKED_TOTAL,
        },
        "observability": observability,
        "provider_outcomes": dict(_PROVIDER_OUTCOMES),
        "client": DEBUG_STATE["last_client_snapshot"],
        "client_updated_at": DEBUG_STATE["last_client_update"],
    }


@app.get(
    "/api/settings",
    summary="Runtime configuration settings",
    description="Returns editable dashboard settings for post-install setup.",
    tags=["Config"],
)
async def api_settings_get():
    home = {"lat": LAT, "lon": LON, "label": LABEL}
    work = None
    if len(ALERT_LOCATIONS) > 1:
        work_loc = ALERT_LOCATIONS[1]
        work = {
            "lat": work_loc.get("lat"),
            "lon": work_loc.get("lon"),
            "label": work_loc.get("label") or "Work",
        }

    return {
        "location": {
            "home": home,
            "work": work,
            "timezone": TIMEZONE,
        },
        "user_agent": USER_AGENT,
        "pws": {
            "provider": PWS_PROVIDER,
            "stations": PWS_STATIONS,
            "configured": bool(PWS_KEY and PWS_STATIONS),
        },
        "map": {
            "provider": MAP_PROVIDER,
            "options": MAP_PROVIDER_IDS,
        },
        "providers": {
            pid: {
                "enabled": bool(PROVIDERS.get(pid, {}).get("enabled", False)),
                "requires_api_key": bool(PROVIDER_META.get(pid, {}).get("requires_api_key", False)),
                "configured": (
                    not bool(PROVIDER_META.get(pid, {}).get("requires_api_key", False))
                    or bool(_provider_api_key(pid))
                ),
                "capabilities": PROVIDER_CAPABILITIES.get(pid, []),
            }
            for pid in PROVIDER_IDS
        },
        "openweather": {
            "configured": bool(OWM_KEY),
        },
        "auth": {
            "enabled": AUTH_ENABLED,
            "require_viewer_login": AUTH_REQUIRE_VIEWER_LOGIN,
            "admin_user": next((u.get("username") for u in AUTH_USERS if u.get("role") == "admin"), "admin"),
            "viewer_user": next((u.get("username") for u in AUTH_USERS if u.get("role") == "viewer"), "viewer"),
        },
        "cache": {
            "provider_ttl_seconds": PROVIDER_PULL_CYCLES,
            "provider_ttl_defaults": wc.get_provider_pull_cycle_defaults(),
            "provider_ttl_bounds": wc.get_provider_pull_cycle_bounds(),
        },
        "secrets_source": {
            "owm": "env" if os.getenv("OWM_API_KEY") else "config",
            "pws": "env" if os.getenv("PWS_API_KEY") else "config",
            "weatherapi": "env" if os.getenv("WEATHERAPI_API_KEY") else "secure_store",
            "tomorrow": "env" if os.getenv("TOMORROW_API_KEY") else "secure_store",
            "visualcrossing": "env" if os.getenv("VISUALCROSSING_API_KEY") else "secure_store",
        },
    }


@app.post(
    "/api/settings",
    summary="Update runtime configuration",
    description="Updates location/user-agent/PWS settings and persists to config.yaml.",
    tags=["Config"],
)
async def api_settings_post(payload: dict[str, Any] = Body(...)):
    start_ts = time.time()
    async with _cfg_lock:
        cfg = _load_config_file()

        location = payload.get("location", {})
        home = location.get("home", {})
        work = location.get("work")
        timezone = str(location.get("timezone", cfg.get("location", {}).get("timezone", "UTC")) or "UTC").strip()
        if not _valid_timezone(timezone):
            raise HTTPException(status_code=400, detail="Invalid timezone")

        try:
            home_lat = float(home.get("lat"))
            home_lon = float(home.get("lon"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Home location lat/lon must be numeric") from exc
        if not (-90.0 <= home_lat <= 90.0 and -180.0 <= home_lon <= 180.0):
            raise HTTPException(status_code=400, detail="Home location lat must be -90..90 and lon -180..180")

        home_label = _sanitize_label(home.get("label"), "Home", "Home label")
        cfg["location"] = {
            "lat": home_lat,
            "lon": home_lon,
            "label": home_label,
            "timezone": timezone,
        }

        alert_locations = [{"lat": home_lat, "lon": home_lon, "label": home_label}]
        if isinstance(work, dict) and work.get("lat") not in (None, "") and work.get("lon") not in (None, ""):
            try:
                work_lat = float(work.get("lat"))
                work_lon = float(work.get("lon"))
            except Exception as exc:
                raise HTTPException(status_code=400, detail="Work location lat/lon must be numeric") from exc
            if not (-90.0 <= work_lat <= 90.0 and -180.0 <= work_lon <= 180.0):
                raise HTTPException(status_code=400, detail="Work location lat must be -90..90 and lon -180..180")
            alert_locations.append(
                {
                    "lat": work_lat,
                    "lon": work_lon,
                    "label": _sanitize_label(work.get("label"), "Work", "Work label"),
                }
            )
        cfg["alert_locations"] = alert_locations

        if "user_agent" in payload:
            cfg["user_agent"] = _sanitize_user_agent(payload.get("user_agent"), cfg.get("user_agent") or USER_AGENT)

        pws_payload = payload.get("pws", {}) if isinstance(payload.get("pws", {}), dict) else {}
        pws_cfg = cfg.get("pws", {}) if isinstance(cfg.get("pws", {}), dict) else {}
        if "provider" in pws_payload:
            pws_cfg["provider"] = str(pws_payload.get("provider") or pws_cfg.get("provider") or "weather.com")
        if "stations" in pws_payload:
            pws_cfg["stations"] = _sanitize_pws_stations(pws_payload.get("stations") or [])
        cfg["pws"] = pws_cfg

        auth_payload = payload.get("auth", {}) if isinstance(payload.get("auth", {}), dict) else {}
        auth_cfg = cfg.get("auth", {}) if isinstance(cfg.get("auth", {}), dict) else {}
        users = list(auth_cfg.get("users", []) or [])

        def upsert_user(role: str, username: str | None, password: str | None) -> None:
            if not username:
                return
            uname = _sanitize_username(username, role)
            if not uname:
                return
            existing = None
            for user in users:
                if str(user.get("username", "")).strip().lower() == uname.lower():
                    existing = user
                    break
            if existing is None:
                existing = {"username": uname, "role": role}
                users.append(existing)
            existing["username"] = uname
            existing["role"] = role
            if password:
                _validate_password_strength(str(password), role)
                existing["password_hash"] = _hash_password(password)
                existing.pop("password", None)

        if "enabled" in auth_payload:
            auth_cfg["enabled"] = bool(auth_payload.get("enabled"))
        else:
            auth_cfg["enabled"] = bool(auth_cfg.get("enabled", False))

        if "require_viewer_login" in auth_payload:
            auth_cfg["require_viewer_login"] = bool(auth_payload.get("require_viewer_login"))
        else:
            auth_cfg["require_viewer_login"] = bool(auth_cfg.get("require_viewer_login", False))

        admin_username = str(auth_payload.get("admin_username") or "").strip() or None
        admin_password = str(auth_payload.get("admin_password") or "").strip() or None
        viewer_username = str(auth_payload.get("viewer_username") or "").strip() or None
        viewer_password = str(auth_payload.get("viewer_password") or "").strip() or None

        upsert_user("admin", admin_username, admin_password)
        upsert_user("viewer", viewer_username, viewer_password)

        if auth_cfg.get("enabled"):
            has_admin = any(str(user.get("role")) == "admin" for user in users)
            if not has_admin:
                raise HTTPException(status_code=400, detail="At least one admin user is required when auth is enabled")
            for user in users:
                if str(user.get("role")) == "admin":
                    has_password = bool(user.get("password_hash") or user.get("password"))
                    if not has_password:
                        raise HTTPException(status_code=400, detail="Admin password is required when auth is enabled")

        auth_cfg["users"] = users
        auth_cfg["token_secret"] = str(auth_cfg.get("token_secret") or secrets.token_hex(24))
        cfg["auth"] = auth_cfg

        providers_payload = payload.get("providers", {}) if isinstance(payload.get("providers", {}), dict) else {}
        providers_cfg = cfg.get("providers", {}) if isinstance(cfg.get("providers", {}), dict) else {}
        runtime_providers: dict[str, dict[str, Any]] = {}
        for pid in PROVIDER_IDS:
            p_payload = providers_payload.get(pid, {}) if isinstance(providers_payload.get(pid, {}), dict) else {}
            p_cfg = providers_cfg.get(pid, {}) if isinstance(providers_cfg.get(pid, {}), dict) else {}
            enabled = bool(p_payload.get("enabled", p_cfg.get("enabled", False)))
            providers_cfg[pid] = {"enabled": enabled}
            runtime_providers[pid] = {"enabled": enabled}

            if "api_key" in p_payload:
                raw = str(p_payload.get("api_key") or "").strip()
                if raw and len(raw) > 512:
                    raise HTTPException(status_code=400, detail=f"{pid} api_key must be <= 512 characters")
                if pid == "meteomatics" and raw and ":" not in raw:
                    raise HTTPException(status_code=400, detail="meteomatics api_key must be username:password")
                if raw:
                    SECURE_STORE.set_json(f"providers.{pid}.api_key", raw)
                else:
                    SECURE_STORE.delete(f"providers.{pid}.api_key")

        cfg["providers"] = providers_cfg

        map_payload = payload.get("map", {}) if isinstance(payload.get("map", {}), dict) else {}
        map_cfg = cfg.get("map", {}) if isinstance(cfg.get("map", {}), dict) else {}
        chosen_map_provider = str(map_payload.get("provider") or map_cfg.get("provider") or "esri_street")
        if chosen_map_provider not in MAP_PROVIDER_IDS:
            raise HTTPException(status_code=400, detail="Unsupported map provider")
        map_cfg["provider"] = chosen_map_provider
        cfg["map"] = map_cfg

        cache_payload = payload.get("cache", {}) if isinstance(payload.get("cache", {}), dict) else {}
        provider_ttl_payload = (
            cache_payload.get("provider_ttl_seconds", {})
            if isinstance(cache_payload.get("provider_ttl_seconds", {}), dict)
            else {}
        )
        provider_ttl_seconds = wc.set_provider_pull_cycles(provider_ttl_payload)

        SECURE_STORE.set_json("auth.users", users)

        runtime_settings = {
            "location": cfg.get("location", {}),
            "alert_locations": cfg.get("alert_locations", []),
            "user_agent": cfg.get("user_agent"),
            "pws": cfg.get("pws", {}),
            "providers": runtime_providers,
            "map": {"provider": chosen_map_provider},
            "auth": {
                "enabled": bool(auth_cfg.get("enabled", False)),
                "require_viewer_login": bool(auth_cfg.get("require_viewer_login", False)),
                "admin_user": next((u.get("username") for u in users if u.get("role") == "admin"), "admin"),
                "viewer_user": next((u.get("username") for u in users if u.get("role") == "viewer"), "viewer"),
            },
            "cache": {
                "provider_ttl_seconds": provider_ttl_seconds,
            },
        }
        SECURE_STORE.set_json("settings.runtime", runtime_settings)
        if payload.get("mark_first_run_complete"):
            SECURE_STORE.set_json("bootstrap.first_run_complete", True)

        with open(_CONFIG_PATH, "w") as f:
            yaml.safe_dump(cfg, f, sort_keys=False)

        _apply_config(cfg)

    _log_event(
        "settings.saved",
        None,
        changed_top_level=sorted(str(key) for key in payload.keys()),
        duration_ms=int((time.time() - start_ts) * 1000),
    )

    return {"ok": True, "message": "Settings saved", "restart_required": False}


@app.get(
    "/api/test-provider",
    summary="Test provider connectivity",
    description="Tests whether a provider API is working with the configured API key and location.",
    tags=["Weather"],
)
async def api_test_provider(provider: str = Query("nws"), api_key: str | None = Query(None), request: Request = None):
    if not AUTH_ENABLED:
        pass  # Allow in local mode
    elif request:
        identity = _request_identity(request)
        if identity is None:
            raise HTTPException(status_code=401, detail="Authentication required to test providers")
        if identity.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin role required to test providers")

    provider = str(provider or "nws").strip().lower()
    if provider not in PROVIDER_IDS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    if not PROVIDERS.get(provider, {}).get("enabled"):
        raise HTTPException(status_code=400, detail=f"Provider {provider} is not enabled")

    # Get API key: from parameter (unsaved form), then from persistent storage
    test_api_key = api_key
    if not test_api_key:
        test_api_key = _provider_api_key(provider) if PROVIDER_META.get(provider, {}).get("requires_api_key") else None

    if PROVIDER_META.get(provider, {}).get("requires_api_key") and not test_api_key:
        raise HTTPException(status_code=400, detail=f"Provider {provider} requires an API key but none is configured")

    try:
        result = await wc.test_provider(
            provider_id=provider,
            lat=LAT,
            lon=LON,
            api_key=test_api_key,
            user_agent=USER_AGENT,
        )
        if result.get("ok"):
            return {"ok": True, "provider": provider, "message": result.get("message"), "data": result.get("data")}
        else:
            raise HTTPException(status_code=502, detail=result.get("error", "Provider test failed"))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Provider test error: {str(exc)}") from exc


@app.post("/api/debug/client", include_in_schema=False)
async def api_debug_client(payload: dict[str, Any] = Body(...)):
    DEBUG_STATE["last_client_snapshot"] = payload
    DEBUG_STATE["last_client_update"] = int(time.time())
    return {"ok": True}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    # Silence browser favicon requests when no icon asset is provided.
    return Response(status_code=204)


@app.get("/api/owm-tile/{layer}/{z}/{x}/{y}", include_in_schema=False)
async def owm_tile_proxy(layer: str, z: int, x: int, y: int):
    """Reverse-proxy OWM map tiles so the API key stays server-side."""
    allowed = {"precipitation_new", "temp_new", "wind_new", "clouds_new", "pressure_new"}
    if layer not in allowed:
        raise HTTPException(status_code=400, detail="Unknown layer")
    if not PROVIDERS.get("openweather", {}).get("enabled"):
        raise HTTPException(status_code=503, detail="OWM provider disabled")
    if not OWM_KEY:
        raise HTTPException(status_code=503, detail="OWM not configured")
    url = f"https://tile.openweathermap.org/map/{layer}/{z}/{x}/{y}.png"
    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            wc.record_upstream_call("owm_tiles")
            resp = await client.get(url, params={"appid": OWM_KEY})
        if not resp.is_success:
            raise HTTPException(status_code=resp.status_code, detail="OWM tile error")
        return Response(
            content=resp.content,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=600"},
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Static frontend — mount LAST so API routes take priority
# ---------------------------------------------------------------------------

_STATIC = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(_STATIC), html=True), name="static")
