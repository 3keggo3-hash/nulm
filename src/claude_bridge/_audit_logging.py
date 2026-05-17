"""Audit tool call logging entry point."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import time
import uuid
from hashlib import sha256
from typing import Any

from claude_bridge._audit_core import (
    current_session_id,
    _session_file,
    _append_audit_record,
    ensure_session_start_logged,
)
from claude_bridge._audit_index import append_audit_index_record
from claude_bridge._audit_redaction import (
    _result_summary,
    _summarize_value,
    _redact_sensitive_values,
    _telemetry_summary,
)
from claude_bridge._audit_activity import _extract_policy_decision


def log_tool_call(
    tool_name: str,
    params: dict[str, Any],
    result: str,
    *,
    duration_ms: float,
    agent_id: str | None = None,
) -> None:
    session_id = current_session_id()
    ensure_session_start_logged(session_id, agent_id)
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
    if agent_id is not None:
        record["agent_id"] = agent_id
    decision_fields = _extract_policy_decision(result)
    if decision_fields:
        record.update(decision_fields)

    path = _session_file(session_id)
    offset = _append_audit_record(path, record, session_id=session_id)
    append_audit_index_record(session_id, record, offset=offset)
