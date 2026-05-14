"""Compact audit index helpers for faster recent-call queries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claude_bridge._audit_core import _append_audit_record, _session_file


def _audit_index_file(session_id: str) -> Path:
    session_path = _session_file(session_id)
    return session_path.with_name(f"{session_path.stem}.index.jsonl")


def _record_ok(record: dict[str, Any]) -> bool:
    result = record.get("result", {})
    return bool(result.get("ok", False)) if isinstance(result, dict) else False


def _index_entry_from_record(record: dict[str, Any], *, offset: int) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "offset": offset,
        "record_id": record.get("record_id"),
        "timestamp": record.get("timestamp"),
        "tool_name": record.get("tool_name"),
        "ok": _record_ok(record),
    }
    for key in (
        "decision_action",
        "decision_source",
        "decision_risk_level",
        "original_record_id",
        "appeal_id",
        "appeal_status",
        "escalation_id",
        "escalation_status",
    ):
        value = record.get(key)
        if value is not None:
            entry[key] = value
    return entry


def append_audit_index_record(
    session_id: str,
    record: dict[str, Any],
    *,
    offset: int | None,
) -> None:
    if offset is None:
        return
    entry = _index_entry_from_record(record, offset=offset)
    line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
    _append_audit_record(_audit_index_file(session_id), line, skip_hash_chain=True)


def load_audit_index(session_id: str) -> list[dict[str, Any]]:
    path = _audit_index_file(session_id)
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(raw, dict) and isinstance(raw.get("offset"), int):
                    entries.append(raw)
    except OSError:
        return []
    return entries
