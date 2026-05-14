"""Value summarization, truncation, and sensitive data redaction for audit records."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

_SUMMARY_MAX_STRING = 300
_SUMMARY_MAX_ITEMS = 20
_SUMMARY_MAX_DEPTH = 3
_REDACTION_MAX_DEPTH = 10

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "authorization",
    "cookie",
    "private_key",
    "access_token",
    "auth_token",
    "session_id",
    "credentials",
    "credential",
    "refresh_token",
    "client_secret",
    "aws_access_key",
    "aws_secret_key",
}
_CONTENT_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("api_key_assignment", re.compile(r"(?i)\bapi[_-]?key\s*[:=]\s*['\"][^'\"]+['\"]")),
    ("secret_assignment", re.compile(r"(?i)\bsecret\s*[:=]\s*['\"][^'\"]+['\"]")),
    ("token_assignment", re.compile(r"(?i)\btoken\s*[:=]\s*['\"][^'\"]+['\"]")),
    ("password_assignment", re.compile(r"(?i)\bpassword\s*[:=]\s*['\"][^'\"]+['\"]")),
    ("api_key_unquoted", re.compile(r"(?i)\bapi[_-]?key\s*[:=]\s*\S+")),
    ("secret_unquoted", re.compile(r"(?i)\bsecret\s*[:=]\s*\S+")),
    ("token_unquoted", re.compile(r"(?i)\btoken\s*[:=]\s*\S+")),
    ("password_unquoted", re.compile(r"(?i)\bpassword\s*[:=]\s*\S+")),
    ("bearer_token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9_\-.]+")),
    ("jwt_token", re.compile(r"(?i)\b(eyJ[A-Za-z0-9_\-]+)\.(eyJ[A-Za-z0-9_\-]+)\.[A-Za-z0-9_\-]+")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_secret_key", re.compile(r"(?i)\baws[_-]?secret[_-]?key\s*[:=]\s*['\"][^'\"]+['\"]")),
    ("private_key_header", re.compile(r"-----BEGIN\s+(RSA|EC|DSA|OPENSSH)?\s*PRIVATE\s+KEY-----")),
    (
        "uuid_token",
        re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),
    ),
    ("gh_token", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}\b")),
    ("gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[0-9]{10,12}-[0-9]{10,12}-[A-Za-z0-9]{24,}\b")),
]


def _estimate_tokens(value: str) -> int:
    return max(1, (len(value) + 3) // 4) if value else 0


def _truncate_string(value: str) -> dict[str, Any] | str:
    if len(value) <= _SUMMARY_MAX_STRING:
        return value
    return {
        "preview": value[:_SUMMARY_MAX_STRING],
        "truncated": True,
        "original_length": len(value),
        "sha256": sha256(value.encode("utf-8")).hexdigest(),
    }


def _summarize_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= _SUMMARY_MAX_DEPTH:
        return {"type": type(value).__name__}
    if isinstance(value, str):
        return _truncate_string(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        items = [_summarize_value(item, depth=depth + 1) for item in value[:_SUMMARY_MAX_ITEMS]]
        if len(value) > _SUMMARY_MAX_ITEMS:
            items.append({"truncated_items": len(value) - _SUMMARY_MAX_ITEMS})
        return items
    if isinstance(value, dict):
        summarized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _SUMMARY_MAX_ITEMS:
                summarized["_truncated_keys"] = len(value) - _SUMMARY_MAX_ITEMS
                break
            summarized[str(key)] = _summarize_value(item, depth=depth + 1)
        return summarized
    return repr(value)


def _hash_utf8(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _result_summary(result: str) -> tuple[dict[str, Any], str]:
    try:
        payload = json.loads(result)
    except json.JSONDecodeError:
        return {"raw_result": _truncate_string(result)}, _hash_utf8(result)

    details = payload.get("details", {})
    summary = {
        "ok": bool(payload.get("ok", False)),
        "message": str(payload.get("message", ""))[:500],
        "code": payload.get("code"),
        "details": _summarize_value(details),
    }
    return summary, _hash_utf8(result)


def _has_truncation_marker(value: Any, *, depth: int = 0) -> bool:
    if depth >= _SUMMARY_MAX_DEPTH:
        return False
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "truncated" and item is True:
                return True
            if key.endswith("_truncated") and item is True:
                return True
            if _has_truncation_marker(item, depth=depth + 1):
                return True
        return False
    if isinstance(value, list):
        return any(_has_truncation_marker(item, depth=depth + 1) for item in value)
    return False


def _plain_string(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        preview = value.get("preview")
        if isinstance(preview, str) and preview:
            return preview
    return None


def _mask_secret_value(raw: str) -> dict[str, Any]:
    """Produce an opaque redacted representation for a secret string."""
    return {
        "redacted": True,
        "reason": "sensitive value",
    }


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(sensitive in normalized for sensitive in _SENSITIVE_KEYS)


def _redact_sensitive_values(value: Any, *, depth: int = 0) -> Any:
    """Recursively redact sensitive key values in nested dict / list structures.

    Keys are matched case-insensitively against ``_SENSITIVE_KEYS``.  When a
    string value is found under a sensitive key it is replaced by a
    deterministic redaction object.  Paths, commands and other non-sensitive
    data are preserved as-is.
    """
    if depth >= _REDACTION_MAX_DEPTH:
        return value
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(str(key)):
                if isinstance(item, str) and item:
                    redacted[key] = _mask_secret_value(item)
                elif isinstance(item, (int, float, bool)) or item is None:
                    redacted[key] = item
                else:
                    redacted[key] = _redact_sensitive_values(item, depth=depth + 1)
            else:
                redacted[key] = _redact_sensitive_values(item, depth=depth + 1)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive_values(item, depth=depth + 1) for item in value]
    if isinstance(value, str) and value:
        for _name, pattern in _CONTENT_SECRET_PATTERNS:
            if pattern.search(value):
                return _mask_secret_value(value)
    return value


def _strip_redacted(record: dict[str, Any]) -> dict[str, Any]:
    """Remove redacted value markers from a single audit record."""
    cleaned: dict[str, Any] = {}
    for key, value in record.items():
        cleaned[key] = _strip_redacted_value(value)
    return cleaned


def _strip_redacted_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 20:
        return value
    if isinstance(value, dict):
        if value.get("redacted") is True:
            return "[REDACTED]"
        return {k: _strip_redacted_value(v, depth=depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_redacted_value(item, depth=depth + 1) for item in value]
    return value


def _telemetry_summary(params: dict[str, Any], result: str) -> dict[str, Any]:
    params_summary = _summarize_value(params)
    params_json = json.dumps(params_summary, ensure_ascii=False, sort_keys=True)
    result_chars = len(result)
    params_chars = len(params_json)
    try:
        payload = json.loads(result)
    except json.JSONDecodeError:
        payload = None
    return {
        "input_chars": params_chars,
        "output_chars": result_chars,
        "estimated_input_tokens": _estimate_tokens(params_json),
        "estimated_output_tokens": _estimate_tokens(result),
        "estimated_total_tokens": _estimate_tokens(params_json) + _estimate_tokens(result),
        "result_truncated": _has_truncation_marker(payload) if isinstance(payload, dict) else False,
    }
