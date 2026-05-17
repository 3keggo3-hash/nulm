"""Activity summary building, validation tracking, filtering, and policy decision extraction."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
from typing import Any

from claude_bridge._audit_redaction import (
    _plain_string,
    _redact_sensitive_values,
)

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
_ACTIVITY_MAX_ITEMS = 20

_VALID_DECISION_ACTIONS = {"allow", "deny", "ask"}
_VALID_DECISION_SOURCES = {"default", "builtin_guard", "rule", "approval", "ai"}
_VALID_RISK_LEVELS = {"low", "medium", "high", "critical"}


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
