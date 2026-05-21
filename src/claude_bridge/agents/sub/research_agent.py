"""Research agent for codebase analysis and documentation."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

from typing import TYPE_CHECKING, Any

from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.broker import AgentToolBroker
from claude_bridge.agents.contracts import TaskPermissions
from claude_bridge.agents.result import AgentResult
from claude_bridge.agents.run_record import AgentRunRecord, start_agent_run

if TYPE_CHECKING:
    from claude_bridge.permissions import PermissionMatrix


class ResearchAgent(BaseAgent):
    """Agent specialized in research and code analysis."""

    def __init__(self, permission_matrix: PermissionMatrix | None = None) -> None:
        super().__init__("research_agent", permission_matrix)

    async def execute(self, task: str, context: dict[str, Any]) -> AgentResult:
        """Execute a research task.

        Args:
            task: The research task to execute.
            context: Execution context.

        Returns:
            AgentResult with research findings.
        """
        if not self.can_use_tool("file_read") and not self.can_use_tool("search"):
            return AgentResult.failure(
                error="Permission denied: file_read/search tools not allowed",
                agent_name=self.name,
            )

        task_lower = task.lower()

        if "find" in task_lower or "search" in task_lower:
            return await self.find_relevant(task, context)
        if "analyze" in task_lower or "codebase" in task_lower:
            return await self.analyze_codebase(context)

        return await self.analyze_codebase(context)

    async def find_relevant(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Find relevant files and code for a task.

        Args:
            task: Task description.

        Returns:
            AgentResult with relevant file paths.
        """
        broker = self._broker(context)
        record = self._record(context)
        return broker.search_python_files(record, task, limit=20)

    async def analyze_codebase(self, context: dict[str, Any] | None = None) -> AgentResult:
        """Analyze the codebase structure.

        Returns:
            AgentResult with codebase analysis.
        """
        broker = self._broker(context)
        record = self._record(context)
        return broker.count_python_files(record)

    def _broker(self, context: dict[str, Any] | None) -> AgentToolBroker:
        if context:
            broker = context.get("agent_tool_broker")
            if isinstance(broker, AgentToolBroker):
                return broker
        return AgentToolBroker(self._task_permissions(context))

    def _record(self, context: dict[str, Any] | None) -> AgentRunRecord:
        record = context.get("agent_run_record") if context else None
        if isinstance(record, AgentRunRecord):
            return record
        return start_agent_run(task_id="single", agent_name=self.name, task_kind="research")

    def _task_permissions(self, context: dict[str, Any] | None) -> TaskPermissions:
        subtask = context.get("subtask") if context else None
        permissions = getattr(subtask, "permissions", None)
        if isinstance(permissions, TaskPermissions) and permissions.allowed_tools:
            return permissions
        return TaskPermissions(allowed_tools=frozenset(self.get_allowed_tools()))
