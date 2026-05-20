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

    @classmethod
    def from_raw(cls, raw: Any) -> TaskBudget:
        if not isinstance(raw, dict):
            return cls()
        max_tool_calls = raw.get("max_tool_calls")
        timeout_seconds = raw.get("timeout_seconds")
        return cls(
            max_tool_calls=int(max_tool_calls) if max_tool_calls is not None else None,
            timeout_seconds=int(timeout_seconds) if timeout_seconds is not None else None,
        )


@dataclass(frozen=True)
class TaskPermissions:
    """Permission hints for an agent task."""

    allowed_tools: frozenset[str] = frozenset()
    allow_mutation: bool = False
    allow_network: bool = False

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
            allow_mutation=bool(raw.get("allow_mutation", False)),
            allow_network=bool(raw.get("allow_network", False)),
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
    read_set: tuple[str, ...] = ()
    write_set: tuple[str, ...] = ()
    budget: TaskBudget = field(default_factory=TaskBudget)
    permissions: TaskPermissions = field(default_factory=TaskPermissions)
    expected_artifacts: tuple[str, ...] = ()
    priority: int = 2

    @classmethod
    def from_legacy_dict(cls, raw: dict[str, Any]) -> TaskSpec:
        task_id = str(raw.get("id") or raw.get("task_id") or "")
        goal = str(raw.get("task") or raw.get("goal") or "")
        agent_name = str(raw.get("agent_name") or "")
        kind = str(raw.get("kind") or agent_name.removesuffix("_agent") or "general")
        priority = int(raw.get("priority", 2) or 2)
        return cls(
            task_id=task_id,
            kind=kind,
            goal=goal,
            agent_name=agent_name,
            read_set=_string_tuple(raw.get("read_set", ())),
            write_set=_string_tuple(raw.get("write_set", ())),
            budget=TaskBudget.from_raw(raw.get("budget")),
            permissions=TaskPermissions.from_raw(raw.get("permissions")),
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
            "priority": self.priority,
        }


def coerce_task_spec(raw: TaskSpec | dict[str, Any]) -> TaskSpec:
    """Convert legacy subtask dictionaries into typed task specs."""
    if isinstance(raw, TaskSpec):
        return raw
    return TaskSpec.from_legacy_dict(raw)


def _string_tuple(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list | tuple | set):
        return ()
    return tuple(str(item) for item in raw)
