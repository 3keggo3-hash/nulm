"""Durable record models for future agent DAG reconstruction."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Literal, TypeVar, cast

AGENT_DAG_RUN_SCHEMA_VERSION = "agent_dag_run.v1"
AGENT_DAG_NODE_SCHEMA_VERSION = "agent_dag_node.v1"
AGENT_DAG_ARTIFACT_SCHEMA_VERSION = "agent_dag_artifact.v1"
AGENT_DAG_CONFLICT_SCHEMA_VERSION = "agent_dag_conflict.v1"

AgentDagStatus = Literal[
    "pending",
    "ready",
    "leased",
    "running",
    "blocked",
    "completed",
    "failed",
    "cancelled",
]

AgentDagNodeEvent = Literal[
    "node_ready",
    "node_leased",
    "node_running",
    "node_completed",
    "node_failed",
    "node_blocked",
    "lease_expired",
]

AGENT_DAG_STATUSES: tuple[AgentDagStatus, ...] = (
    "pending",
    "ready",
    "leased",
    "running",
    "blocked",
    "completed",
    "failed",
    "cancelled",
)

AGENT_DAG_NODE_EVENTS: tuple[AgentDagNodeEvent, ...] = (
    "node_ready",
    "node_leased",
    "node_running",
    "node_completed",
    "node_failed",
    "node_blocked",
    "lease_expired",
)

_RecordT = TypeVar("_RecordT")


@dataclass(frozen=True)
class AgentDagRunRecord:
    """Append-only state record for one logical agent DAG run."""

    run_id: str
    goal: str
    status: AgentDagStatus
    created_at: float
    updated_at: float
    root_node_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = AGENT_DAG_RUN_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "goal": self.goal,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "root_node_ids": list(self.root_node_ids),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentDagRunRecord:
        _require_schema(data, AGENT_DAG_RUN_SCHEMA_VERSION)
        status = _status(data.get("status"))
        return cls(
            run_id=_required_str(data, "run_id"),
            goal=_required_str(data, "goal"),
            status=status,
            created_at=_required_float(data, "created_at"),
            updated_at=_required_float(data, "updated_at"),
            root_node_ids=_string_tuple(data.get("root_node_ids", ())),
            metadata=_metadata(data.get("metadata")),
        )


@dataclass(frozen=True)
class AgentDagNodeRecord:
    """Append-only state record for one future DAG node."""

    node_id: str
    run_id: str
    task_id: str
    agent_name: str
    kind: str
    status: AgentDagStatus
    dependencies: tuple[str, ...] = ()
    read_set: tuple[str, ...] = ()
    write_set: tuple[str, ...] = ()
    context_manifest_id: str | None = None
    artifact_ids: tuple[str, ...] = ()
    idempotency_key: str = ""
    lease_owner: str | None = None
    lease_expires_at: float | None = None
    retry_count: int = 0
    failure_class: str | None = None
    failure_message: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    node_event: AgentDagNodeEvent | None = None
    schema_version: str = AGENT_DAG_NODE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.node_event is None:
            object.__setattr__(self, "node_event", _event_from_status(self.status))
        elif self.node_event not in AGENT_DAG_NODE_EVENTS:
            raise ValueError(f"invalid DAG node_event {self.node_event!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "node_id": self.node_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "kind": self.kind,
            "status": self.status,
            "node_event": self.node_event or _event_from_status(self.status),
            "dependencies": list(self.dependencies),
            "read_set": list(self.read_set),
            "write_set": list(self.write_set),
            "context_manifest_id": self.context_manifest_id,
            "artifact_ids": list(self.artifact_ids),
            "idempotency_key": self.idempotency_key,
            "lease_owner": self.lease_owner,
            "lease_expires_at": self.lease_expires_at,
            "retry_count": self.retry_count,
            "failure_class": self.failure_class,
            "failure_message": self.failure_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentDagNodeRecord:
        _require_schema(data, AGENT_DAG_NODE_SCHEMA_VERSION)
        status = _status(data.get("status"))
        return cls(
            node_id=_required_str(data, "node_id"),
            run_id=_required_str(data, "run_id"),
            task_id=_required_str(data, "task_id"),
            agent_name=_required_str(data, "agent_name"),
            kind=_required_str(data, "kind"),
            status=status,
            node_event=_node_event(data.get("node_event"), status=status),
            dependencies=_string_tuple(data.get("dependencies", ())),
            read_set=_string_tuple(data.get("read_set", ())),
            write_set=_string_tuple(data.get("write_set", ())),
            context_manifest_id=_optional_str(data.get("context_manifest_id")),
            artifact_ids=_string_tuple(data.get("artifact_ids", ())),
            idempotency_key=_string_value(data.get("idempotency_key"), ""),
            lease_owner=_optional_str(data.get("lease_owner")),
            lease_expires_at=_optional_float(data.get("lease_expires_at")),
            retry_count=_int_value(data.get("retry_count"), 0),
            failure_class=_optional_str(data.get("failure_class")),
            failure_message=_optional_str(data.get("failure_message")),
            created_at=_required_float(data, "created_at"),
            updated_at=_required_float(data, "updated_at"),
            metadata=_metadata(data.get("metadata")),
        )


@dataclass(frozen=True)
class AgentDagArtifactRecord:
    """Append-only record for an artifact produced by a future DAG node."""

    artifact_id: str
    run_id: str
    node_id: str
    kind: str
    digest: str
    summary: str
    path: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    schema_version: str = AGENT_DAG_ARTIFACT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "run_id": self.run_id,
            "node_id": self.node_id,
            "kind": self.kind,
            "digest": self.digest,
            "summary": self.summary,
            "path": self.path,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentDagArtifactRecord:
        _require_schema(data, AGENT_DAG_ARTIFACT_SCHEMA_VERSION)
        return cls(
            artifact_id=_required_str(data, "artifact_id"),
            run_id=_required_str(data, "run_id"),
            node_id=_required_str(data, "node_id"),
            kind=_required_str(data, "kind"),
            digest=_required_str(data, "digest"),
            summary=_string_value(data.get("summary"), ""),
            path=_string_value(data.get("path"), ""),
            metadata=_metadata(data.get("metadata")),
            created_at=_required_float(data, "created_at"),
        )


@dataclass(frozen=True)
class AgentDagConflictRecord:
    """Append-only conflict signal for future DAG adjudication."""

    conflict_id: str
    run_id: str
    node_ids: tuple[str, ...]
    type: str
    files: tuple[str, ...]
    signal: str
    resolution: str = ""
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = AGENT_DAG_CONFLICT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "conflict_id": self.conflict_id,
            "run_id": self.run_id,
            "node_ids": list(self.node_ids),
            "type": self.type,
            "files": list(self.files),
            "signal": self.signal,
            "resolution": self.resolution,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentDagConflictRecord:
        _require_schema(data, AGENT_DAG_CONFLICT_SCHEMA_VERSION)
        return cls(
            conflict_id=_required_str(data, "conflict_id"),
            run_id=_required_str(data, "run_id"),
            node_ids=_string_tuple(data.get("node_ids", ())),
            type=_required_str(data, "type"),
            files=_string_tuple(data.get("files", ())),
            signal=_required_str(data, "signal"),
            resolution=_string_value(data.get("resolution"), ""),
            created_at=_required_float(data, "created_at"),
            metadata=_metadata(data.get("metadata")),
        )


def make_agent_dag_id(prefix: str, fields: dict[str, Any]) -> str:
    """Return a deterministic sha256-based id from stable JSON fields."""
    raw = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"{prefix}_{sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def make_node_id(
    *,
    run_id: str,
    task_id: str,
    agent_name: str,
    kind: str,
    read_set: tuple[str, ...] = (),
    write_set: tuple[str, ...] = (),
) -> str:
    return make_agent_dag_id(
        "node",
        _node_identity_fields(
            run_id=run_id,
            task_id=task_id,
            agent_name=agent_name,
            kind=kind,
            read_set=read_set,
            write_set=write_set,
        ),
    )


def make_node_idempotency_key(
    *,
    run_id: str,
    task_id: str,
    agent_name: str,
    kind: str,
    read_set: tuple[str, ...] = (),
    write_set: tuple[str, ...] = (),
) -> str:
    return make_agent_dag_id(
        "idem",
        _node_identity_fields(
            run_id=run_id,
            task_id=task_id,
            agent_name=agent_name,
            kind=kind,
            read_set=read_set,
            write_set=write_set,
        ),
    )


def make_artifact_id(*, run_id: str, node_id: str, kind: str, digest: str) -> str:
    return make_agent_dag_id(
        "artifact",
        {
            "digest": digest,
            "kind": kind,
            "node_id": node_id,
            "run_id": run_id,
        },
    )


def _node_identity_fields(
    *,
    run_id: str,
    task_id: str,
    agent_name: str,
    kind: str,
    read_set: tuple[str, ...],
    write_set: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "agent_name": agent_name,
        "kind": kind,
        "read_set": sorted(read_set),
        "run_id": run_id,
        "task_id": task_id,
        "write_set": sorted(write_set),
    }


def _require_schema(data: dict[str, Any], expected: str) -> None:
    actual = data.get("schema_version")
    if actual != expected:
        raise ValueError(f"invalid schema_version {actual!r}; expected {expected!r}")


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} is required")
    return value


def _required_float(data: dict[str, Any], key: str) -> float:
    value = data.get(key)
    if value is None:
        raise ValueError(f"{key} is required")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} is required") from exc


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _status(value: Any) -> AgentDagStatus:
    if value not in AGENT_DAG_STATUSES:
        raise ValueError(f"invalid DAG status {value!r}")
    return cast(AgentDagStatus, value)


def _node_event(value: Any, *, status: AgentDagStatus) -> AgentDagNodeEvent:
    if value is None:
        return _event_from_status(status)
    if value not in AGENT_DAG_NODE_EVENTS:
        raise ValueError(f"invalid DAG node_event {value!r}")
    return cast(AgentDagNodeEvent, value)


def _event_from_status(status: AgentDagStatus) -> AgentDagNodeEvent:
    if status == "ready":
        return "node_ready"
    if status == "leased":
        return "node_leased"
    if status == "running":
        return "node_running"
    if status == "completed":
        return "node_completed"
    if status == "failed":
        return "node_failed"
    if status == "blocked":
        return "node_blocked"
    return "node_ready"


def _string_tuple(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list | tuple | set):
        return ()
    return tuple(str(item) for item in raw if str(item))


def _metadata(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _string_value(value: Any, default: str) -> str:
    return value if isinstance(value, str) else default


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
