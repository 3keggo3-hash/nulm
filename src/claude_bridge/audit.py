"""Structured audit logging for Claude Bridge tool calls."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    import msvcrt  # type: ignore[import-untyped]
else:
    import fcntl  # type: ignore[import-untyped]

from claude_bridge.anomaly import compute_anomaly_scores

_AUDIT_LOCK = threading.RLock()
_CURRENT_SESSION_ID = ""
_MAX_AUDIT_SESSION_SCAN_FILES = 256
_MAX_AUDIT_RECORD_SCAN_LINES = 10000
_SUMMARY_MAX_STRING = 300
_SUMMARY_MAX_ITEMS = 20
_SUMMARY_MAX_DEPTH = 3
_ACTIVITY_MAX_ITEMS = 20
_REDACTION_MAX_DEPTH = 10
_PATH_PARAM_KEYS = (
    "file",
    "path",
    "source",
    "destination",
    "target",
    "from_path",
    "to_path",
)
_COMMAND_TOOLS = {"run_shell", "start_process", "read_process_output", "stop_process"}
_WRITE_TOOLS = {
    "write_file",
    "move_file",
    "copy_file",
    "patch_file",
    "undo_last_patch",
}
_PATCH_TOOLS = {"preview_patch", "patch_file", "undo_last_patch"}
_VALIDATION_COMMAND_PREFIXES = (
    "pytest",
    "python -m pytest",
    "python3 -m pytest",
    "ruff check",
    "black --check",
    "mypy",
    "npm test",
    "npm run test",
    "pnpm test",
    "yarn test",
    "cargo test",
    "go test",
    "make test",
)
_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "authorization",
    "cookie",
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
]


def _estimate_tokens(value: str) -> int:
    return max(1, (len(value) + 3) // 4) if value else 0


def _audit_dir() -> Path:
    override = os.environ.get("CLAUDE_BRIDGE_AUDIT_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".claude-bridge" / "audit").resolve()


def _new_session_id() -> str:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return f"{stamp}-{uuid.uuid4().hex[:12]}"


def reset_audit_session() -> str:
    global _CURRENT_SESSION_ID
    with _AUDIT_LOCK:
        _CURRENT_SESSION_ID = _new_session_id()
        return _CURRENT_SESSION_ID


def current_session_id() -> str:
    with _AUDIT_LOCK:
        if not _CURRENT_SESSION_ID:
            return reset_audit_session()
        return _CURRENT_SESSION_ID


_VALID_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _session_file(session_id: str) -> Path:
    # FIX: Validate session_id to prevent path traversal
    if not _VALID_SESSION_ID_RE.match(session_id):
        raise ValueError(f"invalid session_id: {session_id!r}")
    return _audit_dir() / f"{session_id}.jsonl"


def _append_audit_record(path: Path, line: str) -> None:
    """Append a line to an audit file with process locking and restricted permissions."""
    try:
        with _AUDIT_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                # FIX: Process-level file locking via flock (msvcrt on Windows)
                if sys.platform == "win32":
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    except (ImportError, OSError):
                        pass
                else:
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX)
                    except (ImportError, OSError):
                        pass
                handle.write(line + "\n")
                # FIX: Restrict file permissions to owner-only
                os.chmod(path, 0o600)
    except OSError:
        return


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


def _result_summary(result: str) -> tuple[dict[str, Any], str]:
    try:
        payload = json.loads(result)
    except json.JSONDecodeError:
        return {"raw_result": _truncate_string(result)}, sha256(result.encode("utf-8")).hexdigest()

    details = payload.get("details", {})
    summary = {
        "ok": bool(payload.get("ok", False)),
        "message": str(payload.get("message", "")),
        "code": payload.get("code"),
        "details": _summarize_value(details),
    }
    return summary, sha256(result.encode("utf-8")).hexdigest()


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


def _record_result(record: dict[str, Any]) -> dict[str, Any]:
    result = record.get("result", {})
    return result if isinstance(result, dict) else {}


def _record_params(record: dict[str, Any]) -> dict[str, Any]:
    params = record.get("params", {})
    return params if isinstance(params, dict) else {}


def _append_unique(items: list[str], value: str | None) -> None:
    if value and value not in items and len(items) < _ACTIVITY_MAX_ITEMS:
        items.append(value)


def _collect_paths(record: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    params = _record_params(record)
    result = _record_result(record)
    details = result.get("details", {})
    detail_map = details if isinstance(details, dict) else {}
    for source in (params, detail_map):
        for key in _PATH_PARAM_KEYS:
            _append_unique(paths, _plain_string(source.get(key)))
    return paths


def _collect_command(record: dict[str, Any]) -> str | None:
    params = _record_params(record)
    command = _plain_string(params.get("command"))
    if command:
        return command
    result = _record_result(record)
    details = result.get("details", {})
    if isinstance(details, dict):
        return _plain_string(details.get("command"))
    return None


def _record_risk_level(record: dict[str, Any]) -> str | None:
    decision_risk = record.get("decision_risk_level")
    if isinstance(decision_risk, str) and decision_risk:
        return decision_risk
    result = _record_result(record)
    details = result.get("details", {})
    if isinstance(details, dict):
        return _plain_string(details.get("risk_level"))
    return None


def _activity_item(record: dict[str, Any]) -> dict[str, Any]:
    result = _record_result(record)
    ok = bool(result.get("ok", False))
    item: dict[str, Any] = {
        "timestamp": record.get("timestamp"),
        "tool_name": record.get("tool_name", "unknown"),
        "ok": ok,
        "message": result.get("message", ""),
        "duration_ms": record.get("duration_ms"),
    }
    paths = _collect_paths(record)
    if paths:
        item["paths"] = paths
    command = _collect_command(record)
    if command:
        item["command"] = command
    risk_level = _record_risk_level(record)
    if risk_level:
        item["risk_level"] = risk_level
    return item


def _is_successful_write(record: dict[str, Any]) -> bool:
    tool_name = str(record.get("tool_name", "unknown"))
    result = _record_result(record)
    return tool_name in _WRITE_TOOLS and bool(result.get("ok", False))


def _is_validation_command(command: str) -> bool:
    normalized = " ".join(command.strip().split())
    return any(
        normalized == prefix or normalized.startswith(prefix + " ")
        for prefix in _VALIDATION_COMMAND_PREFIXES
    )


def _build_validation_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    latest_write_position: int | None = None
    for index, record in enumerate(records):
        if _is_successful_write(record):
            latest_write_position = index
            break

    validation_commands: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        command = _collect_command(record)
        if not command or not _is_validation_command(command):
            continue
        item = _activity_item(record)
        item["after_last_write"] = (
            latest_write_position is not None and index < latest_write_position
        )
        if len(validation_commands) < _ACTIVITY_MAX_ITEMS:
            validation_commands.append(item)

    validation_after_changes = any(
        bool(item.get("ok", False)) and bool(item.get("after_last_write", False))
        for item in validation_commands
    )
    has_changes = latest_write_position is not None
    return {
        "has_changes": has_changes,
        "validation_after_changes": validation_after_changes,
        "validation_commands": validation_commands,
        "needs_validation": has_changes and not validation_after_changes,
        "recommended_next_step": (
            "Run the relevant validation command for the changed project "
            "(for example pytest, ruff check ., mypy src, or the package test script)."
            if has_changes and not validation_after_changes
            else None
        ),
    }


def build_activity_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    touched_paths: list[str] = []
    commands: list[dict[str, Any]] = []
    patch_previews: list[dict[str, Any]] = []
    risky_actions: list[dict[str, Any]] = []
    approval_rejections: list[dict[str, Any]] = []
    writes: list[dict[str, Any]] = []

    for record in records:
        tool_name = str(record.get("tool_name", "unknown"))
        result = _record_result(record)
        item = _activity_item(record)
        for path in _collect_paths(record):
            _append_unique(touched_paths, path)

        command = _collect_command(record)
        if command and len(commands) < _ACTIVITY_MAX_ITEMS:
            commands.append(item)
        if tool_name in _PATCH_TOOLS and len(patch_previews) < _ACTIVITY_MAX_ITEMS:
            patch_previews.append(item)
        if tool_name in _WRITE_TOOLS and len(writes) < _ACTIVITY_MAX_ITEMS:
            writes.append(item)
        if result.get("code") == "approval_rejected":
            if len(approval_rejections) < _ACTIVITY_MAX_ITEMS:
                approval_rejections.append(item)
        risk_level = _record_risk_level(record)
        if risk_level and risk_level != "low" and len(risky_actions) < _ACTIVITY_MAX_ITEMS:
            risky_actions.append(item)

    return {
        "touched_paths": touched_paths,
        "commands": commands,
        "writes": writes,
        "patch_previews": patch_previews,
        "approval_rejections": approval_rejections,
        "risky_actions": risky_actions,
        "policy_decisions": _compute_policy_decision_counts(records),
        "validation": _build_validation_summary(records),
        "timeline": [_activity_item(record) for record in records[:_ACTIVITY_MAX_ITEMS]],
    }


def _extract_policy_decision(result: str) -> dict[str, Any] | None:
    """Extract policy decision fields from a tool result payload.

    Checks ``details.decision`` first, then top-level ``decision``.
    Returns ``None`` when no decision object is present.
    """
    try:
        payload = json.loads(result)
    except json.JSONDecodeError:
        return None
    decision: dict[str, Any] | None = None
    details = payload.get("details", {})
    if isinstance(details, dict):
        candidate = details.get("decision")
        if isinstance(candidate, dict):
            decision = candidate
    if decision is None:
        candidate = payload.get("decision")
        if isinstance(candidate, dict):
            decision = candidate
    if decision is None:
        return None
    return {
        "decision_action": decision.get("action"),
        "decision_source": decision.get("source"),
        "decision_risk_level": decision.get("risk_level"),
        "decision_reason": decision.get("reason"),
        "decision_risk_reasons": decision.get("risk_reasons", []),
        "decision_metadata": _redact_sensitive_values(decision.get("metadata", {})),
    }


def _extract_decision_from_record(record: dict[str, Any]) -> dict[str, Any] | None:
    """Extract policy decision fields from an audit record.

    Since ``log_tool_call`` merges top-level decision fields into each record,
    this helper reads them directly.  Falls back to ``result.details.decision``
    for records written before the merge behaviour was introduced.
    """
    action = record.get("decision_action")
    if action is not None:
        return {
            "action": action,
            "source": record.get("decision_source"),
            "risk_level": record.get("decision_risk_level"),
            "reason": record.get("decision_reason"),
            "risk_reasons": record.get("decision_risk_reasons", []),
            "metadata": record.get("decision_metadata", {}),
        }
    result = _record_result(record)
    details = result.get("details", {})
    if isinstance(details, dict):
        candidate = details.get("decision")
        if isinstance(candidate, dict):
            return {
                "action": candidate.get("action"),
                "source": candidate.get("source"),
                "risk_level": candidate.get("risk_level"),
                "reason": candidate.get("reason"),
                "risk_reasons": candidate.get("risk_reasons", []),
                "metadata": candidate.get("metadata", {}),
            }
    return None


def _timestamp_compare(record_ts: str | None, since_ts: str) -> bool:
    """Return True when *record_ts* is on or after *since_ts*.

    Both are expected to be ISO-8601 strings (lexicographically comparable).
    """
    if not record_ts:
        return False
    return record_ts >= since_ts


# Public filter helpers -------------------------------------------------------

_VALID_DECISION_ACTIONS = {"allow", "deny", "ask"}
_VALID_DECISION_SOURCES = {"default", "builtin_guard", "rule", "approval", "ai"}
_VALID_RISK_LEVELS = {"low", "medium", "high", "critical"}


def filter_audit_records(
    records: list[dict[str, Any]],
    *,
    tool_name: str | None = None,
    ok: bool | None = None,
    decision_action: str | None = None,
    decision_source: str | None = None,
    decision_risk_level: str | None = None,
    since: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Filter a list of audit records with the supplied criteria.

    All filters are optional.  When multiple filters are provided they are
    combined with AND semantics.  The returned list is kept in the original
    insertion order (oldest first) by default; reverse before calling when
    most-recent-first ordering is desired.

    Args:
        records: Raw audit records loaded from a session file.
        tool_name: Keep only records whose ``tool_name`` equals this value.
        ok: Keep only records where the result ``ok`` field matches.
        decision_action: One of ``"allow"``, ``"deny"``, ``"ask"``.
        decision_source: One of ``"default"``, ``"builtin_guard"``,
            ``"rule"``, ``"approval"``, ``"ai"``.
        decision_risk_level: One of ``"low"``, ``"medium"``, ``"high"``,
            ``"critical"``.
        since: ISO-8601 timestamp string; keep records on or after this time.
        limit: Maximum number of records to return (oldest first).

    Returns:
        The filtered list of audit records.
    """
    if decision_action is not None:
        decision_action = decision_action.lower()
        if decision_action not in _VALID_DECISION_ACTIONS:
            return []
    if decision_source is not None:
        decision_source = decision_source.lower()
        if decision_source not in _VALID_DECISION_SOURCES:
            return []
    if decision_risk_level is not None:
        decision_risk_level = decision_risk_level.lower()
        if decision_risk_level not in _VALID_RISK_LEVELS:
            return []

    filtered: list[dict[str, Any]] = []
    for record in records:
        if tool_name is not None:
            if record.get("tool_name") != tool_name:
                continue
        if ok is not None:
            result = _record_result(record)
            if bool(result.get("ok", False)) != ok:
                continue
        if since is not None:
            if not _timestamp_compare(record.get("timestamp"), since):
                continue
        if (
            decision_action is not None
            or decision_source is not None
            or decision_risk_level is not None
        ):
            decision = _extract_decision_from_record(record)
            if decision is None:
                continue
            if decision_action is not None:
                if decision.get("action") != decision_action:
                    continue
            if decision_source is not None:
                if decision.get("source") != decision_source:
                    continue
            if decision_risk_level is not None:
                if decision.get("risk_level") != decision_risk_level:
                    continue
        filtered.append(record)
        if limit is not None and len(filtered) >= limit:
            break
    return filtered


def _compute_policy_decision_counts(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute policy decision statistics for a set of audit records."""
    allow_count = 0
    deny_count = 0
    ask_count = 0
    high_critical_risk_count = 0
    rule_decision_count = 0
    total_with_decision = 0

    for record in records:
        decision = _extract_decision_from_record(record)
        if decision is None:
            continue
        total_with_decision += 1
        action = decision.get("action", "")
        if action == "allow":
            allow_count += 1
        elif action == "deny":
            deny_count += 1
        elif action == "ask":
            ask_count += 1
        risk = decision.get("risk_level", "")
        if risk in ("high", "critical"):
            high_critical_risk_count += 1
        source = decision.get("source", "")
        if source == "rule":
            rule_decision_count += 1

    return {
        "total_with_decision": total_with_decision,
        "allow_count": allow_count,
        "deny_count": deny_count,
        "ask_count": ask_count,
        "high_critical_risk_count": high_critical_risk_count,
        "rule_decision_count": rule_decision_count,
        "decision_counts": {
            "allow": allow_count,
            "deny": deny_count,
            "ask": ask_count,
        },
        "risk_counts": {
            "high_or_critical": high_critical_risk_count,
        },
    }


def _mask_secret_value(raw: str) -> dict[str, Any]:
    """Produce a deterministic redacted representation for a secret string."""
    return {
        "redacted": True,
        "reason": "sensitive value",
        "sha256": sha256(raw.encode("utf-8")).hexdigest(),
        "length": len(raw),
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


def log_tool_call(
    tool_name: str,
    params: dict[str, Any],
    result: str,
    *,
    duration_ms: float,
) -> None:
    session_id = current_session_id()
    summary, result_hash = _result_summary(result)
    summary = _redact_sensitive_values(summary)
    params_summary = _summarize_value(params)
    params_redacted = _redact_sensitive_values(params_summary)
    record: dict[str, Any] = {
        "record_id": uuid.uuid4().hex,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session_id": session_id,
        "tool_name": tool_name,
        "params": params_redacted,
        "params_hash": sha256(
            json.dumps(params_redacted, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "duration_ms": round(duration_ms, 3),
        "result": summary,
        "result_hash": result_hash,
        "telemetry": _telemetry_summary(params, result),
        "replay_context": {
            "tool_name": tool_name,
            "params": params_redacted,
        },
    }
    decision_fields = _extract_policy_decision(result)
    if decision_fields:
        record.update(decision_fields)

    path = _session_file(session_id)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    _append_audit_record(path, line)


def _load_records(session_id: str, *, max_lines: int | None = None) -> list[dict[str, Any]]:
    path = _session_file(session_id)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                if max_lines is not None and index >= max_lines:
                    break
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(raw, dict):
                    records.append(raw)
    except OSError:
        return []
    return records


def latest_session_id() -> str | None:
    candidates = _session_files_newest_first(limit=_MAX_AUDIT_SESSION_SCAN_FILES)
    if not candidates:
        return None
    return candidates[0].stem


def _session_files_newest_first(*, limit: int | None = None) -> list[Path]:
    audit_dir = _audit_dir()
    if not audit_dir.exists():
        return []
    candidates: list[tuple[float, Path]] = []
    try:
        paths = list(audit_dir.glob("*.jsonl"))
    except OSError:
        return []
    for path in paths:
        try:
            if path.is_file():
                candidates.append((path.stat().st_mtime, path))
        except OSError:
            continue
    candidates.sort(key=lambda item: item[0], reverse=True)
    selected = candidates[:limit] if limit is not None else candidates
    return [path for _, path in selected]


def _iter_session_ids_newest_first() -> list[str]:
    return [path.stem for path in _session_files_newest_first(limit=_MAX_AUDIT_SESSION_SCAN_FILES)]


def find_audit_record(record_id: str) -> dict[str, Any] | None:
    for session_id in _iter_session_ids_newest_first():
        for record in _load_records(session_id, max_lines=_MAX_AUDIT_RECORD_SCAN_LINES):
            if record.get("record_id") == record_id:
                return record
    return None


def get_recent_tool_calls(
    *,
    limit: int = 20,
    tool_name: str | None = None,
    session_id: str | None = None,
    ok: bool | None = None,
    decision_action: str | None = None,
    decision_source: str | None = None,
    decision_risk_level: str | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    """Return recent tool calls with optional filters.

    All filter parameters are optional and backwards-compatible.  When
    provided they are delegated to :func:`filter_audit_records`.
    """
    selected_session_id = session_id or latest_session_id() or current_session_id()
    records = _load_records(selected_session_id)
    has_advanced_filter = any(
        param is not None
        for param in (ok, decision_action, decision_source, decision_risk_level, since)
    )
    if has_advanced_filter:
        records = filter_audit_records(
            records,
            tool_name=tool_name,
            ok=ok,
            decision_action=decision_action,
            decision_source=decision_source,
            decision_risk_level=decision_risk_level,
            since=since,
        )
        total_after_filter = len(records)
    else:
        if tool_name:
            records = [record for record in records if record.get("tool_name") == tool_name]
        total_after_filter = len(records)
    records = list(reversed(records))
    limited = records[: max(1, limit)]
    return {
        "session_id": selected_session_id,
        "records": limited,
        "total_records": total_after_filter,
        "returned_records": len(limited),
    }


def summarize_session(
    session_id: str | None = None,
    *,
    limit: int = 20,
    tool_name: str | None = None,
    ok: bool | None = None,
    decision_action: str | None = None,
    decision_source: str | None = None,
    decision_risk_level: str | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    recent = get_recent_tool_calls(
        limit=limit,
        tool_name=tool_name,
        session_id=session_id,
        ok=ok,
        decision_action=decision_action,
        decision_source=decision_source,
        decision_risk_level=decision_risk_level,
        since=since,
    )
    counts: dict[str, int] = {}
    failure_count = 0
    total_duration_ms = 0.0
    total_input_chars = 0
    total_output_chars = 0
    total_estimated_tokens = 0
    truncated_results = 0
    tool_token_totals: dict[str, int] = {}
    for record in recent["records"]:
        tool_name = str(record.get("tool_name", "unknown"))
        counts[tool_name] = counts.get(tool_name, 0) + 1
        total_duration_ms += float(record.get("duration_ms", 0.0) or 0.0)
        result = record.get("result", {})
        if isinstance(result, dict) and not result.get("ok", False):
            failure_count += 1
        telemetry = record.get("telemetry", {})
        if isinstance(telemetry, dict):
            input_chars = int(telemetry.get("input_chars", 0) or 0)
            output_chars = int(telemetry.get("output_chars", 0) or 0)
            estimated_total_tokens = int(telemetry.get("estimated_total_tokens", 0) or 0)
            total_input_chars += input_chars
            total_output_chars += output_chars
            total_estimated_tokens += estimated_total_tokens
            tool_token_totals[tool_name] = (
                tool_token_totals.get(tool_name, 0) + estimated_total_tokens
            )
            if telemetry.get("result_truncated") is True:
                truncated_results += 1
    anomaly_result = compute_anomaly_scores(recent["records"])

    return {
        "session_id": recent["session_id"],
        "recent_records": recent["records"],
        "total_records": recent["total_records"],
        "returned_records": recent["returned_records"],
        "tool_counts": counts,
        "failure_count": failure_count,
        "activity": build_activity_summary(recent["records"]),
        "anomaly_counts": anomaly_result["anomaly_counts"],
        "telemetry": {
            "total_duration_ms": round(total_duration_ms, 3),
            "avg_duration_ms": round(total_duration_ms / max(1, len(recent["records"])), 3),
            "total_input_chars": total_input_chars,
            "total_output_chars": total_output_chars,
            "total_estimated_tokens": total_estimated_tokens,
            "truncated_results": truncated_results,
            "tool_estimated_tokens": tool_token_totals,
        },
    }


# ---------------------------------------------------------------------------
# Appeal Data Models and Logging
# ---------------------------------------------------------------------------


@dataclass
class AppealRequest:
    """Request to appeal a policy decision.

    Attributes:
        appeal_id: Unique identifier for this appeal.
        original_record_id: Audit record ID of the original decision being appealed.
        justification: User-provided justification for the appeal.
        metadata: Optional additional context about the appeal.
    """

    appeal_id: str
    original_record_id: str
    justification: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "appeal_id": self.appeal_id,
            "original_record_id": self.original_record_id,
            "justification": self.justification,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def create(
        cls,
        original_record_id: str,
        justification: str,
        metadata: dict[str, Any] | None = None,
    ) -> "AppealRequest":
        """Create a new AppealRequest with a generated appeal_id.

        Args:
            original_record_id: Audit record ID being appealed.
            justification: Reason for the appeal.
            metadata: Optional additional context.

        Returns:
            A new AppealRequest instance.

        Raises:
            ValueError: If justification is empty or whitespace-only.
        """
        if not justification or not justification.strip():
            raise ValueError("justification cannot be empty")
        return cls(
            appeal_id=uuid.uuid4().hex,
            original_record_id=original_record_id,
            justification=justification.strip(),
            metadata=dict(metadata) if metadata else {},
        )


@dataclass
class AppealResult:
    """Result of processing an appeal.

    Attributes:
        appeal_id: Reference to the original AppealRequest.
        status: Final status of the appeal (pending, approved, rejected).
        reviewed_by: Identifier of the reviewer (user, admin, ai, etc.).
        decision_reason: Explanation for the appeal decision.
        metadata: Optional additional context about the decision.
        timestamp: ISO-8601 timestamp when the decision was made.
    """

    appeal_id: str
    status: str
    reviewed_by: str
    decision_reason: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "appeal_id": self.appeal_id,
            "status": self.status,
            "reviewed_by": self.reviewed_by,
            "decision_reason": self.decision_reason,
            "metadata": dict(self.metadata),
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppealResult":
        """Deserialize from a dictionary.

        Args:
            data: Dictionary with appeal result fields.

        Returns:
            An AppealResult instance.
        """
        return cls(
            appeal_id=str(data.get("appeal_id", "")),
            status=str(data.get("status", "pending")),
            reviewed_by=str(data.get("reviewed_by", "unknown")),
            decision_reason=str(data.get("decision_reason", "")),
            metadata=dict(data.get("metadata", {})),
            timestamp=str(data.get("timestamp", "")),
        )


class ExportFormat(str, Enum):
    """Supported audit export formats.

    - JSONL: one JSON object per line (raw records, same as on-disk format)
    - SUMMARY_JSON: a single JSON object with metadata and activity summary

    Default retention is 90 days and 100 sessions (see RetentionConfig).
    """

    JSONL = "jsonl"
    SUMMARY_JSON = "summary-json"


_DEFAULT_RETENTION_DAYS = 90
_DEFAULT_MAX_SESSIONS = 100
_DEFAULT_EXPORT_FORMAT = ExportFormat.JSONL
_DEFAULT_INCLUDE_TELEMETRY = True
_DEFAULT_INCLUDE_REDACTED = True


@dataclass
class RetentionConfig:
    """Audit retention and export configuration.

    Defaults:
        retention_days: 90 — records older than this are eligible for
            cleanup by :func:`apply_retention`.
        max_sessions: 100 — when exceeded, the oldest sessions are
            eligible for cleanup.
        export_format: :class:`ExportFormat`.JSONL — the default format
            used by :func:`export_audit_records`.
        include_telemetry: True — include token/cost telemetry in
            exports.
        include_redacted: True — include redacted (masked) sensitive
            values rather than stripping them entirely.
    """

    retention_days: int = _DEFAULT_RETENTION_DAYS
    max_sessions: int = _DEFAULT_MAX_SESSIONS
    export_format: ExportFormat = _DEFAULT_EXPORT_FORMAT
    include_telemetry: bool = _DEFAULT_INCLUDE_TELEMETRY
    include_redacted: bool = _DEFAULT_INCLUDE_REDACTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "retention_days": self.retention_days,
            "max_sessions": self.max_sessions,
            "export_format": self.export_format.value,
            "include_telemetry": self.include_telemetry,
            "include_redacted": self.include_redacted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RetentionConfig":
        export_raw = data.get("export_format", _DEFAULT_EXPORT_FORMAT.value)
        if isinstance(export_raw, ExportFormat):
            export_fmt = export_raw
        else:
            try:
                export_fmt = ExportFormat(str(export_raw))
            except ValueError:
                export_fmt = _DEFAULT_EXPORT_FORMAT
        return cls(
            retention_days=int(data.get("retention_days", _DEFAULT_RETENTION_DAYS)),
            max_sessions=int(data.get("max_sessions", _DEFAULT_MAX_SESSIONS)),
            export_format=export_fmt,
            include_telemetry=bool(data.get("include_telemetry", _DEFAULT_INCLUDE_TELEMETRY)),
            include_redacted=bool(data.get("include_redacted", _DEFAULT_INCLUDE_REDACTED)),
        )

    def is_record_expired(self, record: dict[str, Any], *, now_iso: str | None = None) -> bool:
        now = now_iso or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record_ts: str = str(record.get("timestamp", ""))
        if not record_ts:
            return False
        cutoff = _timestamp_offset_days(now, self.retention_days)
        return record_ts < cutoff


@dataclass
class AuditExport:
    """A packaged audit export with metadata.

    Attributes:
        session_id: The session that was exported.
        export_format: The format used for :attr:`records_payload`.
        records_payload: Raw JSONL lines (when jsonl) or summary dict
            (when summary-json).
        record_count: Number of records in the export.
        exported_at: ISO-8601 timestamp of when the export was created.
        retention_config: The retention configuration applied.
    """

    session_id: str
    export_format: ExportFormat
    records_payload: list[dict[str, Any]] | dict[str, Any]
    record_count: int
    exported_at: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    retention_config: RetentionConfig = field(default_factory=RetentionConfig)

    def to_dict(self) -> dict[str, Any]:
        payload: Any
        if isinstance(self.records_payload, list):
            payload = self.records_payload
        else:
            payload = self.records_payload
        return {
            "session_id": self.session_id,
            "export_format": self.export_format.value,
            "records_payload": payload,
            "record_count": self.record_count,
            "exported_at": self.exported_at,
            "retention_config": self.retention_config.to_dict(),
        }

    def to_jsonl(self) -> str:
        if self.export_format != ExportFormat.JSONL:
            raise ValueError("to_jsonl only valid for JSONL export format")
        assert isinstance(self.records_payload, list)
        lines: list[str] = []
        for record in self.records_payload:
            lines.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
        return "\n".join(lines) + "\n" if lines else ""

    def to_summary_json(self) -> str:
        if self.export_format != ExportFormat.SUMMARY_JSON:
            raise ValueError("to_summary_json only valid for summary-json export format")
        assert isinstance(self.records_payload, dict)
        return json.dumps(self.records_payload, ensure_ascii=False, sort_keys=True, indent=2)


def _timestamp_offset_days(reference_iso: str, days: int) -> str:
    """Return an ISO-8601 timestamp *days* before *reference_iso*."""
    import datetime

    dt = datetime.datetime.strptime(reference_iso, "%Y-%m-%dT%H:%M:%SZ")
    offset = dt - datetime.timedelta(days=days)
    return offset.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_retention_config(
    config: RetentionConfig | dict[str, Any] | None,
) -> RetentionConfig:
    if config is None:
        return RetentionConfig()
    if isinstance(config, RetentionConfig):
        return config
    return RetentionConfig.from_dict(config)


def export_audit_records(
    session_id: str | None = None,
    *,
    export_format: ExportFormat | None = None,
    retention_config: RetentionConfig | dict[str, Any] | None = None,
    limit: int | None = None,
) -> AuditExport:
    """Export audit records for a session in the requested format.

    Args:
        session_id: Session to export. Uses the latest session when None.
        export_format: Output format (defaults to the retention config
            format, which defaults to JSONL).
        retention_config: RetentionConfig or dict to control export.
        limit: Optional max number of records to include.

    Returns:
        An :class:`AuditExport` with the packaged records.
    """
    cfg = _parse_retention_config(retention_config)
    fmt = export_format or cfg.export_format

    selected_session = session_id or latest_session_id() or current_session_id()
    records = _load_records(selected_session)
    if limit is not None:
        records = records[:max(1, limit)]

    if not cfg.include_telemetry:
        records = [{k: v for k, v in r.items() if k != "telemetry"} for r in records]
    if not cfg.include_redacted:
        records = [_strip_redacted(r) for r in records]

    if fmt == ExportFormat.SUMMARY_JSON:
        summary = summarize_session(selected_session, limit=limit or 20)
        payload: list[dict[str, Any]] | dict[str, Any] = summary
    else:
        payload = records

    return AuditExport(
        session_id=selected_session,
        export_format=fmt,
        records_payload=payload,
        record_count=len(records),
        retention_config=cfg,
    )


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
        if value.get("redacted") is True and "sha256" in value:
            return "[REDACTED]"
        return {k: _strip_redacted_value(v, depth=depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_redacted_value(item, depth=depth + 1) for item in value]
    return value


def apply_retention(
    *,
    retention_config: RetentionConfig | dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply retention policy: remove expired sessions and trim old records.

    Defaults (see :class:`RetentionConfig`):
        - retention_days = 90
        - max_sessions = 100

    Args:
        retention_config: Override defaults with a RetentionConfig or dict.
        dry_run: When True, report what would be removed without deleting.

    Returns:
        A dict with ``sessions_removed``, ``records_expired``, and
        ``dry_run`` keys.
    """
    cfg = _parse_retention_config(retention_config)
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    all_sessions = _session_files_newest_first()
    sessions_removed = 0
    records_expired = 0

    excess_sessions = all_sessions[cfg.max_sessions :]
    for path in excess_sessions:
        if not dry_run:
            try:
                path.unlink()
            except OSError:
                continue
        sessions_removed += 1

    for path in all_sessions[: cfg.max_sessions]:
        sid = path.stem
        records = _load_records(sid)
        expired_indices: list[int] = []
        for idx, record in enumerate(records):
            if cfg.is_record_expired(record, now_iso=now_iso):
                expired_indices.append(idx)
        if not expired_indices:
            continue
        records_expired += len(expired_indices)
        kept = [r for i, r in enumerate(records) if i not in expired_indices]
        if not dry_run:
            try:
                with path.open("w", encoding="utf-8") as handle:
                    for record in kept:
                        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            except OSError:
                continue

    return {
        "sessions_removed": sessions_removed,
        "records_expired": records_expired,
        "dry_run": dry_run,
        "retention_config": cfg.to_dict(),
    }


def validate_appeal_justification(justification: str) -> tuple[bool, str | None]:
    """Validate that an appeal justification is non-empty.

    Args:
        justification: The justification string to validate.

    Returns:
        A tuple of (is_valid, error_message). If valid, error_message is None.
    """
    if not justification or not justification.strip():
        return False, "justification cannot be empty"
    return True, None


def get_appeal_history(
    record_id: str,
    *,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve all appeal events for a given original audit record.

    Scans session files (newest first) and returns every ``appeal_event``
    record whose ``original_record_id`` matches *record_id*.

    Args:
        record_id: The audit record_id whose appeals are requested.
        session_id: Optional session to limit the search to.

    Returns:
        A list of appeal audit records ordered newest-first.
    """
    results: list[dict[str, Any]] = []

    if session_id is not None:
        session_ids = [session_id]
    else:
        session_ids = _iter_session_ids_newest_first()

    for sid in session_ids:
        for record in _load_records(sid, max_lines=_MAX_AUDIT_RECORD_SCAN_LINES):
            if (
                record.get("tool_name") == "appeal_event"
                and record.get("original_record_id") == record_id
            ):
                results.append(record)

    return results


def process_appeal(
    record_id: str,
    justification: str,
    *,
    metadata: dict[str, Any] | None = None,
    reviewed_by: str = "user",
    session_id: str | None = None,
) -> dict[str, Any]:
    """Process an appeal for a given audit record.

    Looks up the original decision by *record_id*, runs a deterministic
    replay with the justification embedded as metadata, and produces an
    ``AppealResult`` that is chained to the audit log.

    When no AI evaluator is configured the replay is deterministic and the
    result status is ``"ask"`` (requires human review).

    Args:
        record_id: The audit record_id to appeal.
        justification: User-provided reason for the appeal.
        metadata: Optional additional context.
        reviewed_by: Identifier of the reviewer (default ``"user"``).
        session_id: Optional session to search within.

    Returns:
        A dict with keys ``appeal_request``, ``appeal_result``,
        ``original_record``, ``replay_result``, and ``appeal_history``.

    Raises:
        ValueError: If the original record is not found or justification
            is empty.
    """
    is_valid, error_msg = validate_appeal_justification(justification)
    if not is_valid:
        raise ValueError(error_msg or "invalid justification")

    original_record = find_audit_record(record_id)
    if original_record is None:
        raise ValueError(f"original record not found: {record_id}")

    from claude_bridge.replay import replay_with_justification

    replay_result = replay_with_justification(
        original_record,
        justification=justification,
    )

    appeal_req = AppealRequest.create(
        original_record_id=record_id,
        justification=justification,
        metadata=metadata,
    )

    replayed = replay_result.replayed_decision
    appeal_result = AppealResult(
        appeal_id=appeal_req.appeal_id,
        status=replayed.action.value,
        reviewed_by=reviewed_by,
        decision_reason=replayed.reason,
        metadata={
            "replay_changed": replay_result.changed,
            "replay_change_reason": replay_result.change_reason,
            "justification_provided": True,
            **(replay_result.metadata or {}),
        },
    )

    log_appeal_event(appeal_req, appeal_result)

    appeal_history = get_appeal_history(record_id, session_id=session_id)

    return {
        "appeal_request": appeal_req.to_dict(),
        "appeal_result": appeal_result.to_dict(),
        "original_record": {
            "record_id": original_record.get("record_id"),
            "tool_name": original_record.get("tool_name"),
            "timestamp": original_record.get("timestamp"),
            "decision_action": original_record.get("decision_action"),
            "decision_source": original_record.get("decision_source"),
            "decision_risk_level": original_record.get("decision_risk_level"),
        },
        "replay_result": replay_result.to_dict(),
        "appeal_history_count": len(appeal_history),
    }


def log_appeal_event(
    appeal_request: AppealRequest,
    appeal_result: AppealResult | None = None,
) -> None:
    """Log an appeal event to the audit log.

    Args:
        appeal_request: The appeal request details.
        appeal_result: Optional result of the appeal. If None, the appeal
            is logged as pending.
    """
    session_id = current_session_id()
    result_obj: dict[str, Any] = {
        "ok": True,
        "message": "appeal logged",
        "details": {
            "appeal": appeal_request.to_dict(),
        },
    }
    if appeal_result:
        result_obj["details"]["result"] = appeal_result.to_dict()

    result = json.dumps(result_obj, ensure_ascii=False, sort_keys=True)
    summary, result_hash = _result_summary(result)
    summary = _redact_sensitive_values(summary)
    params_summary = _summarize_value(appeal_request.to_dict())
    params_redacted = _redact_sensitive_values(params_summary)

    record: dict[str, Any] = {
        "record_id": uuid.uuid4().hex,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session_id": session_id,
        "tool_name": "appeal_event",
        "params": params_redacted,
        "params_hash": sha256(
            json.dumps(params_redacted, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "duration_ms": 0.0,
        "result": summary,
        "result_hash": result_hash,
        "telemetry": {
            "input_chars": len(json.dumps(params_redacted, ensure_ascii=False, sort_keys=True)),
            "output_chars": len(result),
            "estimated_input_tokens": _estimate_tokens(
                json.dumps(params_redacted, ensure_ascii=False, sort_keys=True)
            ),
            "estimated_output_tokens": _estimate_tokens(result),
            "estimated_total_tokens": _estimate_tokens(
                json.dumps(params_redacted, ensure_ascii=False, sort_keys=True)
            )
            + _estimate_tokens(result),
            "result_truncated": False,
        },
        "replay_context": {
            "tool_name": "appeal_event",
            "params": params_redacted,
        },
        "appeal_id": appeal_request.appeal_id,
        "original_record_id": appeal_request.original_record_id,
    }
    if appeal_result:
        record["appeal_status"] = appeal_result.status
        record["appeal_reviewed_by"] = appeal_result.reviewed_by

    path = _session_file(session_id)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    _append_audit_record(path, line)
