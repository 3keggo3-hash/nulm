"""Local control-plane state for tasks and approval requests."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Literal, Mapping, TypeVar, TypedDict, cast

CONTROL_PLANE_ENV_VAR = "CLAUDE_BRIDGE_CONTROL_PLANE_DIR"
SCHEMA_VERSION = "control_plane.v1"

TaskStatus = Literal[
    "pending",
    "queued",
    "planning",
    "running",
    "in_progress",
    "blocked",
    "approval_pending",
    "testing",
    "failed",
    "completed",
    "cancelled",
]
ApprovalStatus = Literal["pending", "approved", "denied", "cancelled", "expired"]
MessageStatus = Literal["queued", "acknowledged", "completed", "failed", "cancelled"]

_TASK_STATUSES: tuple[TaskStatus, ...] = (
    "pending",
    "queued",
    "planning",
    "running",
    "in_progress",
    "blocked",
    "approval_pending",
    "testing",
    "failed",
    "completed",
    "cancelled",
)
_APPROVAL_STATUSES: tuple[ApprovalStatus, ...] = (
    "pending",
    "approved",
    "denied",
    "cancelled",
    "expired",
)
_MESSAGE_STATUSES: tuple[MessageStatus, ...] = (
    "queued",
    "acknowledged",
    "completed",
    "failed",
    "cancelled",
)
_RecordT = TypeVar("_RecordT")


class ControlPlaneTask(TypedDict, total=False):
    schema_version: str
    id: str
    title: str
    status: TaskStatus
    created_at: str
    updated_at: str
    summary: str
    metadata: dict[str, Any]


class ControlPlaneApproval(TypedDict, total=False):
    schema_version: str
    id: str
    title: str
    status: ApprovalStatus
    created_at: str
    updated_at: str
    expires_at: str
    summary: str
    metadata: dict[str, Any]
    tool: str
    command: str
    reason: str


class ControlPlaneMessage(TypedDict, total=False):
    schema_version: str
    id: str
    status: MessageStatus
    created_at: str
    updated_at: str
    message: str
    response: str
    metadata: dict[str, Any]


DEFAULT_APPROVAL_EXPIRY_MINUTES = 30


class ControlPlaneSummary(TypedDict):
    schema_version: str
    total: int
    by_status: dict[str, int]


def control_plane_dir() -> Path:
    """Return the durable local control-plane directory."""
    override = os.environ.get(CONTROL_PLANE_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".claude-bridge" / "control-plane").resolve()


def create_task(
    title: str,
    *,
    summary: str = "",
    status: TaskStatus = "pending",
    metadata: dict[str, Any] | None = None,
) -> ControlPlaneTask:
    """Append a task record for future integrations."""
    _validate_status(status, _TASK_STATUSES, "task")
    now = _utc_timestamp()
    record: ControlPlaneTask = {
        "schema_version": SCHEMA_VERSION,
        "id": _new_id("task"),
        "title": title,
        "summary": summary,
        "status": status,
        "created_at": now,
        "updated_at": now,
    }
    if metadata is not None:
        record["metadata"] = metadata
    _append_record(_tasks_file(), record)
    return record


def create_approval(
    title: str,
    *,
    tool: str = "",
    command: str = "",
    reason: str = "",
    status: ApprovalStatus = "pending",
    metadata: dict[str, Any] | None = None,
    expires_at: str | None = None,
) -> ControlPlaneApproval:
    """Append an approval request record without changing runtime approval behavior."""
    _validate_status(status, _APPROVAL_STATUSES, "approval")
    now = _utc_timestamp()
    if expires_at is None:
        expires_at = _utc_timestamp(offset_minutes=DEFAULT_APPROVAL_EXPIRY_MINUTES)
    record: ControlPlaneApproval = {
        "schema_version": SCHEMA_VERSION,
        "id": _new_id("approval"),
        "title": title,
        "tool": tool,
        "command": command,
        "reason": reason,
        "summary": "",
        "status": status,
        "created_at": now,
        "updated_at": now,
        "expires_at": expires_at,
    }
    if metadata is not None:
        record["metadata"] = metadata
    _append_record(_approvals_file(), record)
    return record


def list_tasks(
    *,
    status: str | None = None,
    statuses: list[str] | None = None,
    limit: int | None = None,
) -> list[ControlPlaneTask]:
    records = [_coerce_task(record) for record in _read_jsonl(_tasks_file())]
    filtered = _latest_records_by_id([record for record in records if record is not None])
    if status is not None:
        filtered = [record for record in filtered if record.get("status") == status]
    if statuses is not None:
        filtered = [record for record in filtered if record.get("status") in statuses]
    return _apply_limit(filtered, limit)


def get_task(task_id: str) -> ControlPlaneTask | None:
    if task_id == "latest":
        tasks = list_tasks(limit=1)
        return tasks[-1] if tasks else None
    for task in list_tasks():
        if task.get("id") == task_id:
            return task
    return None


def update_task_status(
    task_id: str,
    status: TaskStatus,
    *,
    summary: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ControlPlaneTask | None:
    """Append a new task state event and return the updated task."""
    _validate_status(status, _TASK_STATUSES, "task")
    task = get_task(task_id)
    if task is None:
        return None
    updated = cast(ControlPlaneTask, dict(task))
    updated["status"] = status
    updated["updated_at"] = _utc_timestamp()
    if summary is not None:
        updated["summary"] = summary
    if metadata is not None:
        existing = dict(updated.get("metadata", {}))
        existing.update(metadata)
        updated["metadata"] = existing
    _append_record(_tasks_file(), updated)
    return updated


def summarize_tasks() -> ControlPlaneSummary:
    tasks = list_tasks()
    by_status: dict[str, int] = {status: 0 for status in _TASK_STATUSES}
    for task in tasks:
        status = task.get("status", "pending")
        by_status[status] = by_status.get(status, 0) + 1
    return {"schema_version": SCHEMA_VERSION, "total": len(tasks), "by_status": by_status}


def cancel_tasks(
    task_ids: list[str],
    *,
    reason: str = "",
    metadata: dict[str, Any] | None = None,
) -> list[ControlPlaneTask]:
    """Cancel multiple tasks and return the updated tasks."""
    updated = []
    for task_id in task_ids:
        task = update_task_status(
            task_id,
            "cancelled",
            summary=reason or None,
            metadata=metadata,
        )
        if task is not None:
            updated.append(task)
    return updated


def search_tasks(query: str, *, limit: int | None = None) -> list[ControlPlaneTask]:
    """Search tasks by title substring (case-insensitive)."""
    records = list_tasks()
    query_lower = query.lower()
    filtered = [record for record in records if query_lower in record.get("title", "").lower()]
    return _apply_limit(filtered, limit)


def get_tasks_by_status(statuses: list[str], *, limit: int | None = None) -> list[ControlPlaneTask]:
    """Get tasks matching any of the provided statuses."""
    return list_tasks(statuses=statuses, limit=limit)


def list_approvals(
    *, status: str | None = None, limit: int | None = None
) -> list[ControlPlaneApproval]:
    records = [_coerce_approval(record) for record in _read_jsonl(_approvals_file())]
    filtered = _latest_records_by_id([record for record in records if record is not None])
    if status is not None:
        filtered = [record for record in filtered if record.get("status") == status]
    return _apply_limit(filtered, limit)


def list_approvals_by_task(
    task_id: str,
    *,
    status: str | None = None,
    limit: int | None = None,
) -> list[ControlPlaneApproval]:
    """List approvals associated with a specific task."""
    records = list_approvals(status=status, limit=limit)
    return [rec for rec in records if rec.get("metadata", {}).get("task_id") == task_id]


def get_approval(approval_id: str) -> ControlPlaneApproval | None:
    if approval_id == "latest":
        approvals = list_approvals(limit=1)
        return approvals[-1] if approvals else None
    for approval in list_approvals():
        if approval.get("id") == approval_id:
            return approval
    return None


def resolve_approval(
    approval_id: str,
    status: Literal["approved", "denied"],
    *,
    reason: str = "",
    metadata: dict[str, Any] | None = None,
) -> ControlPlaneApproval | None:
    """Append an approval decision event and return the updated approval."""
    approval = get_approval(approval_id)
    if approval is None:
        return None
    if _is_approval_expired(approval):
        return None
    updated = cast(ControlPlaneApproval, dict(approval))
    updated["status"] = status
    updated["updated_at"] = _utc_timestamp()
    if reason:
        updated["reason"] = reason
    if metadata is not None:
        existing = dict(updated.get("metadata", {}))
        existing.update(metadata)
        updated["metadata"] = existing
    _append_record(_approvals_file(), updated)
    return updated


def check_approval_expiry(approval_id: str) -> bool:
    """Check if an approval has expired and update its status if so. Returns True if expired."""
    approval = get_approval(approval_id)
    if approval is None:
        return False
    if _is_approval_expired(approval):
        updated = cast(ControlPlaneApproval, dict(approval))
        updated["status"] = "expired"
        updated["updated_at"] = _utc_timestamp()
        _append_record(_approvals_file(), updated)
        return True
    return False


def create_message(
    message: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> ControlPlaneMessage:
    """Append a dashboard/user message for agents to pick up."""
    now = _utc_timestamp()
    record: ControlPlaneMessage = {
        "schema_version": SCHEMA_VERSION,
        "id": _new_id("message"),
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "message": message,
    }
    if metadata is not None:
        record["metadata"] = metadata
    _append_record(_messages_file(), record)
    return record


def list_messages(
    *,
    status: str | None = None,
    limit: int | None = None,
) -> list[ControlPlaneMessage]:
    records = [_coerce_message(record) for record in _read_jsonl(_messages_file())]
    filtered = _latest_records_by_id([record for record in records if record is not None])
    if status is not None:
        filtered = [record for record in filtered if record.get("status") == status]
    return _apply_limit(filtered, limit)


def update_message_status(
    message_id: str,
    status: MessageStatus,
    *,
    response: str = "",
    metadata: dict[str, Any] | None = None,
) -> ControlPlaneMessage | None:
    """Append a message state transition and return the updated message."""
    _validate_status(status, _MESSAGE_STATUSES, "message")
    message = _get_latest_by_id(list_messages(), message_id)
    if message is None:
        return None
    updated = cast(ControlPlaneMessage, dict(message))
    updated["status"] = status
    updated["updated_at"] = _utc_timestamp()
    if response:
        updated["response"] = response
    if metadata is not None:
        existing = dict(updated.get("metadata", {}))
        existing.update(metadata)
        updated["metadata"] = existing
    _append_record(_messages_file(), updated)
    return updated


def _is_approval_expired(approval: ControlPlaneApproval) -> bool:
    expires_at = approval.get("expires_at")
    if not expires_at:
        return False
    from datetime import datetime, timezone

    try:
        expiry_time = datetime.strptime(expires_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        return datetime.now(timezone.utc) > expiry_time
    except ValueError:
        return False


def _tasks_file() -> Path:
    return control_plane_dir() / "tasks.jsonl"


def _approvals_file() -> Path:
    return control_plane_dir() / "approvals.jsonl"


def _messages_file() -> Path:
    return control_plane_dir() / "messages.jsonl"


def _append_record(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _chmod_if_possible(path.parent, 0o700)
    is_new = not path.exists()
    if is_new:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    _chmod_if_possible(path, 0o600)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
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
                    records.append(cast(dict[str, Any], raw))
    except OSError:
        return []
    return records


def _coerce_task(record: dict[str, Any]) -> ControlPlaneTask | None:
    record_id = record.get("id")
    title = record.get("title")
    if not isinstance(record_id, str) or not isinstance(title, str):
        return None
    status = record.get("status", "pending")
    if not isinstance(status, str) or status not in _TASK_STATUSES:
        status = "pending"
    task: ControlPlaneTask = {
        "schema_version": _string_value(record.get("schema_version"), SCHEMA_VERSION),
        "id": record_id,
        "title": title,
        "status": cast(TaskStatus, status),
        "created_at": _string_value(record.get("created_at"), ""),
        "updated_at": _string_value(record.get("updated_at"), ""),
        "summary": _string_value(record.get("summary"), ""),
    }
    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        task["metadata"] = cast(dict[str, Any], metadata)
    return task


def _coerce_approval(record: dict[str, Any]) -> ControlPlaneApproval | None:
    task = _coerce_task(record)
    if task is None:
        return None
    status = record.get("status", "pending")
    if not isinstance(status, str) or status not in _APPROVAL_STATUSES:
        status = "pending"
    approval = cast(ControlPlaneApproval, dict(task))
    approval["status"] = cast(ApprovalStatus, status)
    approval["tool"] = _string_value(record.get("tool"), "")
    approval["command"] = _string_value(record.get("command"), "")
    approval["reason"] = _string_value(record.get("reason"), "")
    approval["expires_at"] = _string_value(record.get("expires_at"), "")
    return approval


def _coerce_message(record: dict[str, Any]) -> ControlPlaneMessage | None:
    record_id = record.get("id")
    message = record.get("message")
    if not isinstance(record_id, str) or not isinstance(message, str):
        return None
    status = record.get("status", "queued")
    if not isinstance(status, str) or status not in _MESSAGE_STATUSES:
        status = "queued"
    result: ControlPlaneMessage = {
        "schema_version": _string_value(record.get("schema_version"), SCHEMA_VERSION),
        "id": record_id,
        "status": cast(MessageStatus, status),
        "created_at": _string_value(record.get("created_at"), ""),
        "updated_at": _string_value(record.get("updated_at"), ""),
        "message": message,
        "response": _string_value(record.get("response"), ""),
    }
    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        result["metadata"] = cast(dict[str, Any], metadata)
    return result


def _apply_limit(records: list[_RecordT], limit: int | None) -> list[_RecordT]:
    if limit is None or limit <= 0:
        return records
    return records[-limit:]


def _latest_records_by_id(records: list[_RecordT]) -> list[_RecordT]:
    latest: dict[str, _RecordT] = {}
    order: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        record_id = record.get("id")
        if not isinstance(record_id, str):
            continue
        if record_id not in latest:
            order.append(record_id)
        latest[record_id] = record
    return [latest[record_id] for record_id in order]


def _string_value(value: object, default: str) -> str:
    if isinstance(value, str):
        return value
    return default


def _get_latest_by_id(records: list[_RecordT], record_id: str) -> _RecordT | None:
    for record in records:
        if isinstance(record, dict) and record.get("id") == record_id:
            return record
    return None


def _validate_status(status: str, valid_statuses: tuple[str, ...], label: str) -> None:
    if status not in valid_statuses:
        valid = ", ".join(valid_statuses)
        raise ValueError(f"invalid {label} status {status!r}; expected one of: {valid}")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _utc_timestamp(offset_minutes: int = 0) -> str:
    from datetime import datetime, timedelta, timezone

    if offset_minutes:
        future = datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
        return future.strftime("%Y-%m-%dT%H:%M:%SZ")
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _chmod_if_possible(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        return
