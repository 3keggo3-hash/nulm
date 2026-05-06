"""Appeal request/result models and appeal processing."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from claude_bridge._audit_core import (
    current_session_id,
    _session_file,
    _append_audit_record,
    _load_records_at_offsets,
    find_audit_record,
    _iter_session_ids_newest_first,
    _load_records,
    _MAX_AUDIT_RECORD_SCAN_LINES,
)
from claude_bridge._audit_index import append_audit_index_record, load_audit_index
from claude_bridge._audit_redaction import (
    _result_summary,
    _summarize_value,
    _redact_sensitive_values,
    _estimate_tokens,
)


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


@dataclass
class EscalationEvent:
    """Local audit-backed escalation for a denied appeal."""

    escalation_id: str
    original_record_id: str
    appeal_id: str
    target: str = "team_lead"
    status: str = "pending"
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "escalation_id": self.escalation_id,
            "original_record_id": self.original_record_id,
            "appeal_id": self.appeal_id,
            "target": self.target,
            "status": self.status,
            "reason": self.reason,
            "metadata": dict(self.metadata),
            "timestamp": self.timestamp,
        }

    @classmethod
    def create(
        cls,
        *,
        original_record_id: str,
        appeal_id: str,
        target: str = "team_lead",
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> "EscalationEvent":
        return cls(
            escalation_id=uuid.uuid4().hex,
            original_record_id=original_record_id,
            appeal_id=appeal_id,
            target=target,
            reason=reason,
            metadata=dict(metadata) if metadata else {},
        )


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
        entries = load_audit_index(sid)
        if entries:
            offsets = [
                int(entry["offset"])
                for entry in reversed(entries)
                if (
                    entry.get("tool_name") == "appeal_event"
                    and entry.get("original_record_id") == record_id
                )
            ]
            results.extend(_load_records_at_offsets(sid, offsets))
            continue
        for record in _load_records(sid, max_lines=_MAX_AUDIT_RECORD_SCAN_LINES):
            if (
                record.get("tool_name") == "appeal_event"
                and record.get("original_record_id") == record_id
            ):
                results.append(record)

    return results


def get_pending_escalations(
    *,
    session_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Return pending local escalation audit events, newest first."""
    results: list[dict[str, Any]] = []

    if session_id is not None:
        session_ids = [session_id]
    else:
        session_ids = _iter_session_ids_newest_first()

    for sid in session_ids:
        entries = load_audit_index(sid)
        if entries:
            offsets = [
                int(entry["offset"])
                for entry in reversed(entries)
                if (
                    entry.get("tool_name") == "escalation_event"
                    and entry.get("escalation_status") == "pending"
                )
            ]
            results.extend(_load_records_at_offsets(sid, offsets))
            continue
        for record in _load_records(sid, max_lines=_MAX_AUDIT_RECORD_SCAN_LINES):
            if (
                record.get("tool_name") == "escalation_event"
                and record.get("escalation_status") == "pending"
            ):
                results.append(record)

    results = list(reversed(results))
    safe_limit = max(1, limit)
    return {
        "records": results[:safe_limit],
        "total_pending": len(results),
        "returned_records": min(len(results), safe_limit),
    }


def process_appeal(
    record_id: str,
    justification: str,
    *,
    metadata: dict[str, Any] | None = None,
    reviewed_by: str = "user",
    session_id: str | None = None,
    escalate: bool = False,
    escalation_target: str = "team_lead",
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
    escalation: dict[str, Any] | None = None
    if escalate:
        if appeal_result.status == "deny":
            escalation_event = EscalationEvent.create(
                original_record_id=record_id,
                appeal_id=appeal_req.appeal_id,
                target=escalation_target,
                reason=appeal_result.decision_reason,
                metadata={
                    "reviewed_by": reviewed_by,
                    "appeal_status": appeal_result.status,
                },
            )
            log_escalation_event(escalation_event)
            escalation = {
                "requested": True,
                "created": True,
                "event": escalation_event.to_dict(),
            }
        else:
            escalation = {
                "requested": True,
                "created": False,
                "reason": "appeal result did not require escalation",
                "appeal_status": appeal_result.status,
            }

    appeal_history = get_appeal_history(record_id, session_id=session_id)

    response = {
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
    if escalation is not None:
        response["escalation"] = escalation
    return response


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
    offset = _append_audit_record(path, line)
    append_audit_index_record(session_id, record, offset=offset)


def log_escalation_event(escalation_event: EscalationEvent) -> None:
    """Log a pending escalation event to the audit log."""
    session_id = current_session_id()
    result_obj: dict[str, Any] = {
        "ok": True,
        "message": "escalation logged",
        "details": {"escalation": escalation_event.to_dict()},
    }
    result = json.dumps(result_obj, ensure_ascii=False, sort_keys=True)
    summary, result_hash = _result_summary(result)
    summary = _redact_sensitive_values(summary)
    params_summary = _summarize_value(escalation_event.to_dict())
    params_redacted = _redact_sensitive_values(params_summary)

    record: dict[str, Any] = {
        "record_id": uuid.uuid4().hex,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session_id": session_id,
        "tool_name": "escalation_event",
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
            "tool_name": "escalation_event",
            "params": params_redacted,
        },
        "escalation_id": escalation_event.escalation_id,
        "original_record_id": escalation_event.original_record_id,
        "appeal_id": escalation_event.appeal_id,
        "escalation_target": escalation_event.target,
        "escalation_status": escalation_event.status,
    }
    path = _session_file(session_id)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    offset = _append_audit_record(path, line)
    append_audit_index_record(session_id, record, offset=offset)
