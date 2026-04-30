"""Structured audit logging for Claude Bridge tool calls."""

from __future__ import annotations

import json
import os
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


def log_tool_call(tool_name: str, params: dict[str, Any], result: str, *, duration_ms: float) -> None:
    session_id = current_session_id()
    summary, result_hash = _result_summary(result)
    params_summary = _summarize_value(params)
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session_id": session_id,
        "tool_name": tool_name,
        "params": params_summary,
        "params_hash": sha256(json.dumps(params_summary, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        "duration_ms": round(duration_ms, 3),
        "result": summary,
        "result_hash": result_hash,
        "telemetry": _telemetry_summary(params, result),
    }

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


def get_recent_tool_calls(
    *,
    limit: int = 20,
    tool_name: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    selected_session_id = session_id or latest_session_id() or current_session_id()
    records = _load_records(selected_session_id)
    if tool_name:
        records = [record for record in records if record.get("tool_name") == tool_name]
    records = list(reversed(records))
    limited = records[: max(1, limit)]
    return {
        "session_id": selected_session_id,
        "records": limited,
        "total_records": len(records),
        "returned_records": len(limited),
    }


def summarize_session(session_id: str | None = None, *, limit: int = 20) -> dict[str, Any]:
    recent = get_recent_tool_calls(limit=limit, session_id=session_id)
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
            tool_token_totals[tool_name] = tool_token_totals.get(tool_name, 0) + estimated_total_tokens
            if telemetry.get("result_truncated") is True:
                truncated_results += 1
    return {
        "session_id": recent["session_id"],
        "recent_records": recent["records"],
        "total_records": recent["total_records"],
        "returned_records": recent["returned_records"],
        "tool_counts": counts,
        "failure_count": failure_count,
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
