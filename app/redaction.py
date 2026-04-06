import logging
import re
from typing import Any


REDACTED = "[REDACTED]"

_SECRET_FIELD_NAMES = {
    "api_key",
    "apikey",
    "appid",
    "authorization",
    "password",
    "passwd",
    "password_hash",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "client_secret",
    "secret",
    "private_key",
    "owm_key",
    "pws_key",
    "viewer_password",
    "admin_password",
}

_SECRET_QUERY_PARAM_RE = re.compile(
    r"(?i)([?&](?:api[_-]?key|apikey|appid|authorization|password|passwd|token|access[_-]?token|refresh[_-]?token|id[_-]?token|client[_-]?secret|secret)=)([^&#\s]+)"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(['\"]?(?:api[_-]?key|apikey|appid|authorization|password|passwd|token|access[_-]?token|refresh[_-]?token|id[_-]?token|client[_-]?secret|secret|private[_-]?key|password_hash)['\"]?\s*[:=]\s*['\"]?)([^'\",\s}]+)"
)
_BEARER_TOKEN_RE = re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._~+/=-]+)")
_BASIC_AUTH_URL_RE = re.compile(r"(?i)(https?://)([^\s/@:]+):([^\s/@]+)@")


def _normalize_key(key: Any) -> str:
    return str(key or "").strip().lower().replace("-", "_")


def _should_redact_key(key: Any, value: Any) -> bool:
    normalized = _normalize_key(key)
    if normalized in _SECRET_FIELD_NAMES:
        return True
    if normalized == "auth" and isinstance(value, str):
        return True
    if normalized.endswith("_token") or normalized.endswith("_password") or normalized.endswith("_secret"):
        return True
    if normalized.endswith("_password_hash"):
        return True
    return False


def redact_text(value: str) -> str:
    if not value:
        return value
    redacted = _BASIC_AUTH_URL_RE.sub(r"\1[REDACTED]:[REDACTED]@", value)
    redacted = _SECRET_QUERY_PARAM_RE.sub(r"\1[REDACTED]", redacted)
    redacted = _BEARER_TOKEN_RE.sub(r"\1[REDACTED]", redacted)
    redacted = _SECRET_ASSIGNMENT_RE.sub(r"\1[REDACTED]", redacted)
    return redacted


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            if _should_redact_key(key, item):
                result[key] = REDACTED
            else:
                result[key] = redact_value(item)
        return result
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, set):
        return {redact_value(item) for item in value}
    if isinstance(value, str):
        return redact_text(value)
    return value


class SecretRedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact_text(record.getMessage())
            record.args = ()
        except Exception:
            return True
        return True


def install_logging_redaction() -> None:
    redacting_filter = SecretRedactingFilter()
    logger_names = ["", "okonebo", "httpx", "httpcore", "uvicorn", "uvicorn.access", "uvicorn.error"]
    for logger_name in logger_names:
        logger = logging.getLogger(logger_name)
        if not any(isinstance(item, SecretRedactingFilter) for item in logger.filters):
            logger.addFilter(redacting_filter)
        for handler in logger.handlers:
            if not any(isinstance(item, SecretRedactingFilter) for item in handler.filters):
                handler.addFilter(redacting_filter)