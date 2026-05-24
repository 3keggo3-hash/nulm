"""Typed contracts for internal agent task orchestration."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TaskBudget:
    """Execution budget for an agent task."""

    max_tool_calls: int | None = None
    timeout_seconds: int | None = None

    def __post_init__(self) -> None:
        if self.max_tool_calls is not None and self.max_tool_calls <= 0:
            raise ValueError("max_tool_calls must be positive")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    @classmethod
    def from_raw(cls, raw: Any) -> TaskBudget:
        if not isinstance(raw, dict):
            return cls()
        max_tool_calls = raw.get("max_tool_calls")
        timeout_seconds = raw.get("timeout_seconds")
        try:
            mc = int(max_tool_calls) if max_tool_calls is not None else None
        except (ValueError, TypeError):
            mc = None
        try:
            ts = int(timeout_seconds) if timeout_seconds is not None else None
        except (ValueError, TypeError):
            ts = None
        return cls(max_tool_calls=mc, timeout_seconds=ts)


@dataclass(frozen=True)
class TaskPermissions:
    """Permission hints for an agent task."""

    allowed_tools: frozenset[str] = frozenset()
    allow_mutation: bool = False
    allow_network: bool = False

    def __post_init__(self) -> None:
        if self.allow_mutation and not self.allowed_tools:
            raise ValueError("allowed_tools required when allow_mutation is True")

    @classmethod
    def from_raw(cls, raw: Any) -> TaskPermissions:
        if not isinstance(raw, dict):
            return cls()
        raw_tools = raw.get("allowed_tools", [])
        allowed_tools = (
            frozenset(str(tool) for tool in raw_tools)
            if isinstance(raw_tools, list | tuple | set)
            else frozenset()
        )
        return cls(
            allowed_tools=allowed_tools,
            allow_mutation=_bool_value(raw.get("allow_mutation", False)),
            allow_network=_bool_value(raw.get("allow_network", False)),
        )


@dataclass(frozen=True)
class EvidenceRef:
    """Reference to evidence used or produced by an agent."""

    kind: str
    ref: str
    summary: str = ""


@dataclass(frozen=True)
class AgentArtifact:
    """Typed artifact metadata for agent output contracts."""

    artifact_id: str
    kind: str
    producer: str
    evidence: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True)
class TaskSpec:
    """Typed internal representation of a subtask."""

    task_id: str
    kind: str
    goal: str
    agent_name: str
    question: str = ""
    read_set: tuple[str, ...] = ()
    write_set: tuple[str, ...] = ()
    budget: TaskBudget = field(default_factory=TaskBudget)
    permissions: TaskPermissions = field(default_factory=TaskPermissions)
    acceptance_criteria: tuple[str, ...] = ()
    escalation_policy: str = ""
    allowed_failure_classes: tuple[str, ...] = ()
    expected_evidence: tuple[str, ...] = ()
    expected_artifacts: tuple[str, ...] = ()
    priority: int = 2

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("task_id is required")
        if not self.goal:
            raise ValueError("goal is required")
        if not self.agent_name:
            raise ValueError("agent_name is required")
        if not (1 <= self.priority <= 3):
            raise ValueError("priority must be 1, 2, or 3")

    @classmethod
    def from_legacy_dict(cls, raw: dict[str, Any]) -> TaskSpec:
        task_id = str(raw.get("id") or raw.get("task_id") or "")
        goal = str(raw.get("task") or raw.get("goal") or "")
        agent_name = str(raw.get("agent_name") or "")
        kind = str(raw.get("kind") or agent_name.removesuffix("_agent") or "general")
        try:
            priority = int(raw.get("priority", 2) or 2)
        except (ValueError, TypeError):
            priority = 2
        return cls(
            task_id=task_id,
            kind=kind,
            goal=goal,
            agent_name=agent_name,
            question=_string_value(raw.get("question"), ""),
            read_set=_string_tuple(raw.get("read_set", ())),
            write_set=_string_tuple(raw.get("write_set", ())),
            budget=TaskBudget.from_raw(raw.get("budget")),
            permissions=TaskPermissions.from_raw(raw.get("permissions")),
            acceptance_criteria=_string_tuple(raw.get("acceptance_criteria", ())),
            escalation_policy=_string_value(raw.get("escalation_policy"), ""),
            allowed_failure_classes=_string_tuple(raw.get("allowed_failure_classes", ())),
            expected_evidence=_string_tuple(raw.get("expected_evidence", ())),
            expected_artifacts=_string_tuple(raw.get("expected_artifacts", ())),
            priority=priority,
        )

    def to_legacy_context(self) -> dict[str, Any]:
        """Return a compatibility dict for current agent context consumers."""
        return {
            "id": self.task_id,
            "task": self.goal,
            "agent_name": self.agent_name,
            "kind": self.kind,
            "question": self.question,
            "acceptance_criteria": list(self.acceptance_criteria),
            "escalation_policy": self.escalation_policy,
            "allowed_failure_classes": list(self.allowed_failure_classes),
            "expected_evidence": list(self.expected_evidence),
            "priority": self.priority,
        }


def coerce_task_spec(raw: TaskSpec | dict[str, Any]) -> TaskSpec:
    """Convert legacy subtask dictionaries into typed task specs.

    Fail-closed: returns a minimal valid TaskSpec on any error rather than
    propagating exceptions that could crash the dispatcher.
    """
    if isinstance(raw, TaskSpec):
        return raw
    if not isinstance(raw, dict):
        return TaskSpec(task_id="_invalid", kind="general", goal="_invalid", agent_name="_invalid")
    try:
        return TaskSpec.from_legacy_dict(raw)
    except (ValueError, TypeError, KeyError):
        return TaskSpec(task_id="_invalid", kind="general", goal="_invalid", agent_name="_invalid")


def _string_tuple(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list | tuple | set):
        return ()
    return tuple(str(item) for item in raw if str(item))


def _string_value(raw: Any, default: str) -> str:
    if raw is None:
        return default
    if isinstance(raw, str):
        return raw
    return default


def _bool_value(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(raw, int):
        return raw != 0
    return False


@dataclass(frozen=True)
class BudgetLedger:
    """Token budget tracking for a context manifest."""

    budget_allocated: int = 0
    budget_consumed: int = 0
    budget_remaining: int = 0
    within_budget: bool = True

    @classmethod
    def from_allocated(cls, allocated: int, consumed: int = 0) -> BudgetLedger:
        remaining = max(0, allocated - consumed)
        return cls(
            budget_allocated=allocated,
            budget_consumed=consumed,
            budget_remaining=remaining,
            within_budget=consumed <= allocated,
        )


@dataclass(frozen=True)
class ContextManifest:
    """Snapshot reference for agent execution context."""

    manifest_id: str
    session_id: str
    created_at: float
    goal: str
    target: str
    selected_files: tuple[str, ...] = ()
    file_signatures: tuple[dict[str, str], ...] = ()
    token_budget: int = 0
    estimated_tokens: int = 0
    digest: str = ""
    summary_text: str = ""
    source_reason: str = "none"
    taint: str = "none"
    labels: tuple[str, ...] = ()
    duplicate_ratio: float = 0.0
    parent_manifest_id: str | None = None
    budget_ledger: BudgetLedger = field(default_factory=BudgetLedger)

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "goal": self.goal,
            "target": self.target,
            "selected_files": list(self.selected_files),
            "file_signatures": list(self.file_signatures),
            "token_budget": self.token_budget,
            "estimated_tokens": self.estimated_tokens,
            "digest": self.digest,
            "summary_text": self.summary_text,
            "source_reason": self.source_reason,
            "taint": self.taint,
            "labels": list(self.labels),
            "duplicate_ratio": self.duplicate_ratio,
            "parent_manifest_id": self.parent_manifest_id,
            "budget_ledger": {
                "budget_allocated": self.budget_ledger.budget_allocated,
                "budget_consumed": self.budget_ledger.budget_consumed,
                "budget_remaining": self.budget_ledger.budget_remaining,
                "within_budget": self.budget_ledger.within_budget,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextManifest:
        budget_data = data.get("budget_ledger", {})
        ledger = BudgetLedger(
            budget_allocated=budget_data.get("budget_allocated", 0),
            budget_consumed=budget_data.get("budget_consumed", 0),
            budget_remaining=budget_data.get("budget_remaining", 0),
            within_budget=budget_data.get("within_budget", True),
        )
        return cls(
            manifest_id=data["manifest_id"],
            session_id=data["session_id"],
            created_at=data["created_at"],
            goal=data["goal"],
            target=data["target"],
            selected_files=tuple(data.get("selected_files", [])),
            file_signatures=tuple(data.get("file_signatures", [])),
            token_budget=data.get("token_budget", 0),
            estimated_tokens=data.get("estimated_tokens", 0),
            digest=data.get("digest", ""),
            summary_text=data.get("summary_text", ""),
            source_reason=data.get("source_reason", "none"),
            taint=data.get("taint", "none"),
            labels=tuple(data.get("labels", [])),
            duplicate_ratio=data.get("duplicate_ratio", 0.0),
            parent_manifest_id=data.get("parent_manifest_id"),
            budget_ledger=ledger,
        )
