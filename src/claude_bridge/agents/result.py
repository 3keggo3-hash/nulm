"""Result dataclass for agent execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentStatus(Enum):
    """Agent execution status."""

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    PENDING = "pending"


@dataclass
class AgentResult:
    """Result returned by an agent after task execution."""

    status: AgentStatus
    findings: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    next_steps: list[str] = field(default_factory=list)
    agent_name: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "findings": self.findings,
            "artifacts": self.artifacts,
            "next_steps": self.next_steps,
            "agent_name": self.agent_name,
            "error": self.error,
        }

    @classmethod
    def success(
        cls,
        findings: list[str] | None = None,
        artifacts: dict[str, Any] | None = None,
        next_steps: list[str] | None = None,
        agent_name: str = "",
    ) -> AgentResult:
        return cls(
            status=AgentStatus.SUCCESS,
            findings=findings or [],
            artifacts=artifacts or {},
            next_steps=next_steps or [],
            agent_name=agent_name,
        )

    @classmethod
    def failure(
        cls,
        error: str,
        findings: list[str] | None = None,
        agent_name: str = "",
    ) -> AgentResult:
        return cls(
            status=AgentStatus.FAILURE,
            findings=findings or [],
            artifacts={},
            next_steps=[],
            agent_name=agent_name,
            error=error,
        )