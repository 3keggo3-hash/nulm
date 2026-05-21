"""Git agent for version control operations."""

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


class GitAgent(BaseAgent):
    """Agent specialized in git operations."""

    def __init__(self, permission_matrix: PermissionMatrix | None = None) -> None:
        super().__init__("git_agent", permission_matrix)

    async def execute(self, task: str, context: dict[str, Any]) -> AgentResult:
        """Execute a git-related task.

        Args:
            task: The git task to execute.
            context: Execution context.

        Returns:
            AgentResult with git operation results.
        """
        if not self.can_use_tool("git"):
            return AgentResult.failure(
                error="Permission denied: git tool not allowed",
                agent_name=self.name,
            )

        task_lower = task.lower()

        if "status" in task_lower:
            return await self.git_status(context)
        if "log" in task_lower:
            return await self.git_log(context=context)
        if "blame" in task_lower:
            return await self.git_blame(task, context)

        return await self.git_status(context)

    async def git_status(self, context: dict[str, Any] | None = None) -> AgentResult:
        """Get git status of the repository.

        Returns:
            AgentResult with status information.
        """
        broker = self._broker(context)
        record = self._record(context)
        return broker.git_status(record)

    async def git_log(
        self,
        limit: int = 10,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Get recent git commits.

        Args:
            limit: Number of commits to retrieve.

        Returns:
            AgentResult with commit history.
        """
        broker = self._broker(context)
        record = self._record(context)
        return broker.git_log(record, limit=limit)

    async def git_blame(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Get git blame for a file.

        Args:
            task: Task containing file path.

        Returns:
            AgentResult with blame information.
        """
        file_path = task.replace("blame", "").replace("git", "").strip()
        if not file_path:
            return AgentResult.failure(
                error="No file path specified for blame",
                agent_name=self.name,
            )
        broker = self._broker(context)
        record = self._record(context)
        return broker.git_blame(record, file_path)

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
        return start_agent_run(task_id="single", agent_name=self.name, task_kind="git")

    def _task_permissions(self, context: dict[str, Any] | None) -> TaskPermissions:
        subtask = context.get("subtask") if context else None
        permissions = getattr(subtask, "permissions", None)
        if isinstance(permissions, TaskPermissions) and permissions.allowed_tools:
            return permissions
        return TaskPermissions(allowed_tools=frozenset(self.get_allowed_tools()))
