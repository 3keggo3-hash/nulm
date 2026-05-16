"""Base agent abstract class."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from claude_bridge.agents.result import AgentResult
from claude_bridge.permissions import PermissionMatrix


class BaseAgent(ABC):
    """Abstract base class for all agents."""

    def __init__(self, name: str, permission_matrix: PermissionMatrix | None = None) -> None:
        self.name = name
        self._permission_matrix = permission_matrix or PermissionMatrix()

    @abstractmethod
    async def execute(self, task: str, context: dict[str, Any]) -> AgentResult:
        """Execute a task with the given context.

        Args:
            task: The task to execute.
            context: Shared context including shared_memory and other agents' outputs.

        Returns:
            AgentResult with status, findings, artifacts, and next_steps.
        """

    def can_use_tool(self, tool: str) -> bool:
        """Check if this agent is permitted to use the given tool.

        Args:
            tool: The tool name to check.

        Returns:
            True if the tool is allowed for this agent.
        """
        return self._permission_matrix.can_execute(self.name, tool)

    def get_allowed_tools(self) -> set[str]:
        """Get all tools this agent is allowed to use.

        Returns:
            Set of tool names.
        """
        return self._permission_matrix.get_agent_tools(self.name)
