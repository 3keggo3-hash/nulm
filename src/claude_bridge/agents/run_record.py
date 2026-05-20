"""Agent run records for traceable multi-agent execution."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from claude_bridge._audit_core import (
    _append_audit_record,
    _compute_hmac_signature,
    _session_file,
    current_session_id,
    ensure_session_start_logged,
)
from claude_bridge._audit_index import append_audit_index_record


AGENT_RUN_SCHEMA_VERSION = "agent_run.v1"


@dataclass
class AgentRunRecord:
    """Trace record for one agent subtask execution."""

    run_id: str
    task_id: str
    agent_name: str
    task_kind: str
    started_at: float
    ended_at: float | None = None
    status: str = "pending"
    duration_ms: float | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    model_route: dict[str, Any] | None = None
    context_manifest_id: str | None = None
    artifact_ids: list[str] = field(default_factory=list)
    error_class: str | None = None
    error_message: str | None = None

    def finish(
        self,
        *,
        ended_at: float,
        status: str,
        error_class: str | None = None,
        error_message: str | None = None,
        artifact_ids: list[str] | None = None,
    ) -> None:
        """Mark the run complete and derive duration."""
        self.ended_at = ended_at
        self.status = status
        self.duration_ms = max(0.0, (ended_at - self.started_at) * 1000)
        self.error_class = error_class
        self.error_message = error_message
        if artifact_ids is not None:
            self.artifact_ids = artifact_ids

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "schema_version": AGENT_RUN_SCHEMA_VERSION,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "task_kind": self.task_kind,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "tool_calls": self.tool_calls,
            "model_route": self.model_route,
            "context_manifest_id": self.context_manifest_id,
            "artifact_ids": self.artifact_ids,
            "error_class": self.error_class,
            "error_message": self.error_message,
        }


def compact_run_summary(records: list[AgentRunRecord]) -> dict[str, Any]:
    """Summarize agent run records for CLI/dashboard display."""
    status_counts: dict[str, int] = {}
    total_duration_ms = 0.0
    failures: list[dict[str, str | None]] = []

    for record in records:
        status_counts[record.status] = status_counts.get(record.status, 0) + 1
        total_duration_ms += record.duration_ms or 0.0
        if record.error_class or record.error_message:
            failures.append(
                {
                    "task_id": record.task_id,
                    "agent_name": record.agent_name,
                    "error_class": record.error_class,
                    "error_message": record.error_message,
                }
            )

    return {
        "schema_version": "agent_run_summary.v1",
        "run_count": len(records),
        "status_counts": status_counts,
        "total_duration_ms": total_duration_ms,
        "failures": failures,
    }


def compact_run_summary_from_audit_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize agent runs embedded in audit records."""
    agent_records: list[AgentRunRecord] = []
    for record in records:
        if record.get("tool_name") != "agent_run":
            continue
        result = record.get("result", {})
        if not isinstance(result, dict):
            continue
        payload = result.get("agent_run", {})
        if not isinstance(payload, dict):
            continue
        try:
            agent_records.append(
                AgentRunRecord(
                    run_id=str(payload.get("run_id", "")),
                    task_id=str(payload.get("task_id", "")),
                    agent_name=str(payload.get("agent_name", "")),
                    task_kind=str(payload.get("task_kind", "")),
                    started_at=float(payload.get("started_at", 0.0) or 0.0),
                    ended_at=(
                        float(payload["ended_at"]) if payload.get("ended_at") is not None else None
                    ),
                    status=str(payload.get("status", "unknown")),
                    duration_ms=(
                        float(payload["duration_ms"])
                        if payload.get("duration_ms") is not None
                        else None
                    ),
                    tool_calls=list(payload.get("tool_calls", [])),
                    model_route=(
                        dict(payload["model_route"])
                        if isinstance(payload.get("model_route"), dict)
                        else None
                    ),
                    context_manifest_id=(
                        str(payload["context_manifest_id"])
                        if payload.get("context_manifest_id") is not None
                        else None
                    ),
                    artifact_ids=[str(item) for item in payload.get("artifact_ids", [])],
                    error_class=(
                        str(payload["error_class"])
                        if payload.get("error_class") is not None
                        else None
                    ),
                    error_message=(
                        str(payload["error_message"])
                        if payload.get("error_message") is not None
                        else None
                    ),
                )
            )
        except (TypeError, ValueError):
            continue
    summary = compact_run_summary(agent_records)
    summary["agent_names"] = sorted({record.agent_name for record in agent_records})
    return summary


def start_agent_run(*, task_id: str, agent_name: str, task_kind: str) -> AgentRunRecord:
    """Create a running agent run record."""
    return AgentRunRecord(
        run_id=uuid.uuid4().hex,
        task_id=task_id,
        agent_name=agent_name,
        task_kind=task_kind,
        started_at=time.time(),
        status="running",
    )


def finish_agent_run(
    record: AgentRunRecord,
    result: Any,
    *,
    error_class: str | None = None,
    error_message: str | None = None,
) -> None:
    """Finish and persist a run record from an agent result-like object."""
    status = result.status.value
    derived_error_class = error_class
    result_error = getattr(result, "error", None)
    if derived_error_class is None and result_error:
        derived_error_class = "AgentFailure"
    artifacts = getattr(result, "artifacts", {})
    record.finish(
        ended_at=time.time(),
        status=status,
        error_class=derived_error_class,
        error_message=error_message if error_message is not None else result_error,
        artifact_ids=sorted(artifacts),
    )
    log_agent_run_record(record)


def log_agent_run_record(record: AgentRunRecord) -> None:
    """Append an agent run record to the current audit session."""
    try:
        session_id = current_session_id()
        ensure_session_start_logged(session_id, record.agent_name)
        record_payload = record.to_dict()
        params = {
            "run_id": record.run_id,
            "task_id": record.task_id,
            "agent_name": record.agent_name,
            "task_kind": record.task_kind,
        }
        ok = record.status == "success"
        result = {
            "ok": ok,
            "message": f"agent run {record.status}",
            "schema_version": AGENT_RUN_SCHEMA_VERSION,
            "agent_run": record_payload,
        }
        record_id = uuid.uuid4().hex
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        params_hash = sha256(
            json.dumps(params, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        result_hash = sha256(
            json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        audit_record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "session_id": session_id,
            "tool_name": "agent_run",
            "params": params,
            "params_hash": params_hash,
            "duration_ms": round(record.duration_ms or 0.0, 3),
            "result": result,
            "result_hash": result_hash,
            "hmac_signature": _compute_hmac_signature(
                record_id, timestamp, session_id, "agent_run", params_hash, result_hash
            ),
            "agent_id": record.agent_name,
            "agent_run_schema_version": AGENT_RUN_SCHEMA_VERSION,
            "agent_run_id": record.run_id,
            "agent_task_id": record.task_id,
            "agent_status": record.status,
            "agent_error_class": record.error_class,
            "telemetry": {
                "input_chars": 0,
                "output_chars": 0,
                "estimated_input_tokens": 0,
                "estimated_output_tokens": 0,
                "estimated_total_tokens": 0,
                "result_truncated": False,
            },
            "replay_context": {
                "tool_name": "agent_run",
                "params": params,
            },
        }
        offset = _append_audit_record(_session_file(session_id), audit_record, session_id=session_id)
        append_audit_index_record(session_id, audit_record, offset=offset)
    except Exception:
        return
