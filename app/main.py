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
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

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

    runtime_cfg = SECURE_STORE.get_json("settings.runtime", default={}) or {}

    location = runtime_cfg.get("location", {}) or cfg.get("location", {})
    LAT = float(location.get("lat", 0.0))
    LON = float(location.get("lon", 0.0))
    LABEL = str(location.get("label", "Configured Location"))
    TIMEZONE = str(location.get("timezone", "UTC"))
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
    AUTH_ENABLED = bool(auth_cfg.get("enabled", False))
    AUTH_REQUIRE_VIEWER_LOGIN = bool(auth_cfg.get("require_viewer_login", False))
    AUTH_USERS = list(SECURE_STORE.get_json("auth.users", auth_cfg.get("users", [])) or [])
    AUTH_TOKEN_SECRET = str(
        os.getenv("AUTH_TOKEN_SECRET")
        or auth_cfg.get("token_secret")
        or "dev-okonebo-secret"
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

    FIRST_RUN_COMPLETE = bool(SECURE_STORE.get_json("bootstrap.first_run_complete", False))


_apply_config(_cfg)
SERVER_STARTED_AT = int(time.time())
DEBUG_STATE: dict[str, Any] = {
    "last_client_snapshot": None,
    "last_client_update": None,
}
RATE_LIMIT_WINDOW_SEC = 60
RATE_LIMIT_MAX_PER_WINDOW = 800
_RATE_LIMIT_BUCKETS: dict[str, deque[float]] = defaultdict(deque)
_RATE_LIMIT_BLOCKED_TOTAL = 0

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


def _make_token(username: str, role: str, ttl_hours: int = 24) -> str:
    now = int(time.time())
    payload = {
        "sub": username,
        "role": role,
        "iat": now,
        "exp": now + (ttl_hours * 3600),
    }
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


@app.middleware("http")
async def api_rate_limiter(request: Request, call_next):
    global _RATE_LIMIT_BLOCKED_TOTAL

    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW_SEC

    bucket = _RATE_LIMIT_BUCKETS[client_ip]
    while bucket and bucket[0] < cutoff:
        bucket.popleft()

    if len(bucket) >= RATE_LIMIT_MAX_PER_WINDOW:
        _RATE_LIMIT_BLOCKED_TOTAL += 1
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": "15"},
            content={
                "detail": "Rate limit exceeded",
                "window_seconds": RATE_LIMIT_WINDOW_SEC,
                "max_requests": RATE_LIMIT_MAX_PER_WINDOW,
            },
        )

    bucket.append(now)
    return await call_next(request)


@app.middleware("http")
async def api_auth_guard(request: Request, call_next):
    path = request.url.path
    method = request.method.upper()

    if not path.startswith("/api/"):
        return await call_next(request)

    if not AUTH_ENABLED:
        return await call_next(request)

    if path.startswith("/api/auth/"):
        return await call_next(request)

    identity = _request_identity(request)
    admin_only = (path == "/api/settings" and method == "POST")

    if AUTH_REQUIRE_VIEWER_LOGIN and identity is None:
        return JSONResponse(status_code=401, content={"detail": "Authentication required"})

    if admin_only:
        if identity is None:
            return JSONResponse(status_code=401, content={"detail": "Admin login required"})
        if identity.get("role") != "admin":
            return JSONResponse(status_code=403, content={"detail": "Admin role required"})

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
        try:
            payload = await fetcher()
            if isinstance(payload, dict):
                payload["source"] = provider_id
            return payload
        except Exception as exc:
            provider_errors[provider_id] = str(exc)
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
        try:
            payload = await fetcher()
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        item.setdefault("source", provider_id)
            return payload
        except Exception as exc:
            provider_errors[provider_id] = str(exc)
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
        try:
            payload = await fetcher()
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        item.setdefault("source", provider_id)
            return payload
        except Exception as exc:
            provider_errors[provider_id] = str(exc)
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
        "upstream_calls": wc.get_upstream_call_stats(),
        "rate_limit": {
            "window_seconds": RATE_LIMIT_WINDOW_SEC,
            "max_requests_per_window": RATE_LIMIT_MAX_PER_WINDOW,
            "active_clients": active_rate_limit_clients,
            "blocked_total": _RATE_LIMIT_BLOCKED_TOTAL,
        },
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
    async with _cfg_lock:
        cfg = _load_config_file()

        location = payload.get("location", {})
        home = location.get("home", {})
        work = location.get("work")
        timezone = location.get("timezone", cfg.get("location", {}).get("timezone", "UTC"))

        try:
            home_lat = float(home.get("lat"))
            home_lon = float(home.get("lon"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Home location lat/lon must be numeric") from exc
        if not (-90.0 <= home_lat <= 90.0 and -180.0 <= home_lon <= 180.0):
            raise HTTPException(status_code=400, detail="Home location lat must be -90..90 and lon -180..180")

        home_label = str(home.get("label") or "Home")
        cfg["location"] = {
            "lat": home_lat,
            "lon": home_lon,
            "label": home_label,
            "timezone": str(timezone or "UTC"),
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
                    "label": str(work.get("label") or "Work"),
                }
            )
        cfg["alert_locations"] = alert_locations

        if "user_agent" in payload:
            cfg["user_agent"] = str(payload.get("user_agent") or cfg.get("user_agent") or USER_AGENT)

        pws_payload = payload.get("pws", {}) if isinstance(payload.get("pws", {}), dict) else {}
        pws_cfg = cfg.get("pws", {}) if isinstance(cfg.get("pws", {}), dict) else {}
        if "provider" in pws_payload:
            pws_cfg["provider"] = str(pws_payload.get("provider") or pws_cfg.get("provider") or "weather.com")
        if "stations" in pws_payload:
            stations = pws_payload.get("stations") or []
            pws_cfg["stations"] = [str(s).strip() for s in stations if str(s).strip()]
        cfg["pws"] = pws_cfg

        auth_payload = payload.get("auth", {}) if isinstance(payload.get("auth", {}), dict) else {}
        auth_cfg = cfg.get("auth", {}) if isinstance(cfg.get("auth", {}), dict) else {}
        users = list(auth_cfg.get("users", []) or [])

        def upsert_user(role: str, username: str | None, password: str | None) -> None:
            if not username:
                return
            uname = str(username).strip()
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
        }
        SECURE_STORE.set_json("settings.runtime", runtime_settings)
        if payload.get("mark_first_run_complete"):
            SECURE_STORE.set_json("bootstrap.first_run_complete", True)

        with open(_CONFIG_PATH, "w") as f:
            yaml.safe_dump(cfg, f, sort_keys=False)

        _apply_config(cfg)

    return {"ok": True, "message": "Settings saved", "restart_required": False}


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
