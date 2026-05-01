"""Structured audit logging for Claude Bridge tool calls."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from hashlib import sha256
from pathlib import Path
from typing import Any

_AUDIT_LOCK = threading.RLock()
_CURRENT_SESSION_ID = ""
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


def _session_file(session_id: str) -> Path:
    return _audit_dir() / f"{session_id}.jsonl"


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
        "policy": _compute_policy_decision_counts(records),
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
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except OSError:
        return


def _load_records(session_id: str) -> list[dict[str, Any]]:
    path = _session_file(session_id)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            records.append(raw)
    return records


def latest_session_id() -> str | None:
    audit_dir = _audit_dir()
    if not audit_dir.exists():
        return None
    candidates = sorted(
        [path for path in audit_dir.glob("*.jsonl") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return None
    return candidates[0].stem


def _iter_session_ids_newest_first() -> list[str]:
    audit_dir = _audit_dir()
    if not audit_dir.exists():
        return []
    candidates = sorted(
        [path for path in audit_dir.glob("*.jsonl") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return [path.stem for path in candidates]


def find_audit_record(record_id: str) -> dict[str, Any] | None:
    for session_id in _iter_session_ids_newest_first():
        for record in _load_records(session_id):
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
    return {
        "session_id": recent["session_id"],
        "recent_records": recent["records"],
        "total_records": recent["total_records"],
        "returned_records": recent["returned_records"],
        "tool_counts": counts,
        "failure_count": failure_count,
        "activity": build_activity_summary(recent["records"]),
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


reset_audit_session()
