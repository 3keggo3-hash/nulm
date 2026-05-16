"""Structured audit operations for Phase 2 Audit Log feature.

Records operations with structured schema in project-local .claude-bridge/audit/
as JSONL files, one per session.
"""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import csv
import json
import os
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from claude_bridge._audit_core import (
    _append_audit_record,
    _iter_session_ids_newest_first,
)

AUDIT_SCHEMA: dict[str, str] = {
    "timestamp": "ISO-8601 timestamp",
    "operation": "operation type string",
    "agent": "agent identifier",
    "details": "nested dict with files, lines_changed, etc.",
    "parent_operation": "optional parent operation id",
}

_OPERATION_FILE_VERSION = "1"


def _project_audit_dir() -> Path:
    """Return project-local audit directory (.claude-bridge/audit/).

    Respects CLAUDE_BRIDGE_AUDIT_DIR env var for override,
    otherwise uses .claude-bridge/audit/ relative to cwd.
    """
    override = os.environ.get("CLAUDE_BRIDGE_AUDIT_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.cwd() / ".claude-bridge" / "audit").resolve()


def _ops_session_file(session_id: str) -> Path:
    """Return path for an audit operations file in project-local directory."""
    return _project_audit_dir() / f"{session_id}.jsonl"


def _ops_load_records(session_id: str) -> list[dict[str, Any]]:
    """Load all operation records from a session file in project audit dir."""
    path = _ops_session_file(session_id)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
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


class AuditLogger:
    """Structured audit logger for Phase 2 Audit Log feature.

    Stores operation records in project-local .claude-bridge/audit/ as JSONL.
    Uses session-based files matching the existing audit system pattern.
    """

    AUDIT_DIR: Path = Path(".claude-bridge/audit")
    DEFAULT_RETENTION_DAYS: int = 30

    def __init__(self, *, retention_days: int | None = None) -> None:
        """Initialize AuditLogger.

        Args:
            retention_days: Override default retention period (default 30 days).
        """
        self.retention_days = retention_days or self.DEFAULT_RETENTION_DAYS

    def log_operation(
        self,
        operation: str,
        agent: str,
        files: list[str],
        lines_changed: int = 0,
        risk_score: int = 0,
        backup_created: bool = False,
        test_passed: bool | None = None,
        parent_operation: str | None = None,
    ) -> str:
        """Log an operation to the audit trail.

        Args:
            operation: Operation type (e.g. "file_modify", "git_commit").
            agent: Agent identifier (e.g. "git_agent", "orchestrator").
            files: List of files affected by the operation.
            lines_changed: Number of lines added/removed.
            risk_score: Risk score 0-100.
            backup_created: Whether a backup was created before operation.
            test_passed: Whether tests passed after operation (None = not run).
            parent_operation: Optional parent operation ID for grouping.

        Returns:
            The record_id of the created audit record.
        """
        record_id = uuid.uuid4().hex[:16]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "operation": operation,
            "agent": agent,
            "details": {
                "files": files,
                "lines_changed": lines_changed,
                "risk_score": risk_score,
                "backup_created": backup_created,
                "test_passed": test_passed,
            },
            "parent_operation": parent_operation,
        }

        session_id = self._current_session_id()
        path = _ops_session_file(session_id)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        _append_audit_record(path, line, session_id=session_id, skip_hash_chain=True)
        return record_id

    def list_operations(
        self,
        since: datetime | None = None,
        operation: str | None = None,
        agent: str | None = None,
    ) -> list[dict[str, Any]]:
        """List operations from audit trail, optionally filtered.

        Args:
            since: Only return operations after this datetime.
            operation: Filter by operation type.
            agent: Filter by agent name.

        Returns:
            List of matching operation records, newest first.
        """
        all_records: list[dict[str, Any]] = []
        for session_id in _iter_session_ids_newest_first():
            all_records.extend(_ops_load_records(session_id))

        if since is not None:
            since_ts = since.strftime("%Y-%m-%dT%H:%M:%SZ")
            all_records = [r for r in all_records if r.get("timestamp", "") >= since_ts]

        if agent is not None:
            all_records = [r for r in all_records if r.get("agent") == agent]

        if operation is not None:
            all_records = [r for r in all_records if r.get("operation") == operation]

        all_records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return all_records

    def export_csv(
        self,
        path: Path,
        since: datetime | None = None,
    ) -> None:
        """Export operations to a CSV file.

        Args:
            path: Destination CSV file path.
            since: Only export operations after this datetime.
        """
        records = self.list_operations(since=since)
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "timestamp",
                    "operation",
                    "agent",
                    "files",
                    "lines_changed",
                    "risk_score",
                    "backup_created",
                    "test_passed",
                    "parent_operation",
                ]
            )

            for record in records:
                details = record.get("details", {})
                files = details.get("files", [])
                writer.writerow(
                    [
                        record.get("timestamp", ""),
                        record.get("operation", ""),
                        record.get("agent", ""),
                        ";".join(files) if files else "",
                        details.get("lines_changed", 0),
                        details.get("risk_score", 0),
                        details.get("backup_created", False),
                        details.get("test_passed", ""),
                        record.get("parent_operation", ""),
                    ]
                )

    def search(
        self,
        agent: str | None = None,
        risk: str | None = None,
        operation: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search operations by various criteria.

        Args:
            agent: Filter by agent name.
            risk: Filter by risk level ("low", "medium", "high", "critical").
            operation: Filter by operation type.

        Returns:
            List of matching operation records, newest first.
        """
        records: list[dict[str, Any]] = []
        for session_id in _iter_session_ids_newest_first():
            session_records = _ops_load_records(session_id)
            for record in session_records:
                if agent is not None and record.get("agent") != agent:
                    continue
                details = record.get("details", {})
                rec_risk = details.get("risk_score", 0)
                if risk is not None:
                    rec_risk_level = self._risk_score_to_level(rec_risk)
                    if rec_risk_level != risk.lower():
                        continue
                if operation is not None and record.get("operation") != operation:
                    continue
                records.append(record)

        records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return records

    def apply_retention(self) -> dict[str, Any]:
        """Remove operation records older than retention period.

        Returns:
            Dict with count of removed records and sessions.
        """
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cutoff_ts = self._timestamp_offset_days(now_iso, self.retention_days)

        sessions_removed = 0
        records_expired = 0

        audit_dir = _project_audit_dir()
        if not audit_dir.exists():
            return {
                "sessions_removed": 0,
                "records_expired": 0,
                "retention_days": self.retention_days,
            }

        for session_path in sorted(audit_dir.glob("*.jsonl")):
            if session_path.name.endswith(".index.jsonl"):
                continue
            session_id = session_path.stem
            records = _ops_load_records(session_id)
            kept = [r for r in records if r.get("timestamp", "") >= cutoff_ts]
            expired_count = len(records) - len(kept)

            if expired_count > 0:
                records_expired += expired_count
                if len(kept) == 0:
                    try:
                        session_path.unlink()
                        sessions_removed += 1
                    except OSError:
                        pass
                else:
                    try:
                        with session_path.open("w", encoding="utf-8") as handle:
                            for record in kept:
                                handle.write(
                                    json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
                                )
                    except OSError:
                        pass

        return {
            "sessions_removed": sessions_removed,
            "records_expired": records_expired,
            "retention_days": self.retention_days,
        }

    def _current_session_id(self) -> str:
        """Get or create current session ID for operations."""
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        return f"{stamp}-{uuid.uuid4().hex[:12]}"

    def _risk_score_to_level(self, score: int) -> str:
        """Convert numeric risk score to categorical level."""
        if score <= 20:
            return "low"
        elif score <= 40:
            return "medium"
        elif score <= 80:
            return "high"
        return "critical"

    def _timestamp_offset_days(self, reference_iso: str, days: int) -> str:
        """Return an ISO-8601 timestamp *days* before *reference_iso*."""
        dt = datetime.strptime(reference_iso, "%Y-%m-%dT%H:%M:%SZ")
        offset = dt - timedelta(days=days)
        return offset.strftime("%Y-%m-%dT%H:%M:%SZ")
