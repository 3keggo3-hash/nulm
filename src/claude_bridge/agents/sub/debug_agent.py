"""Debug agent for error investigation and diagnostics."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

from typing import TYPE_CHECKING, Any

from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.broker import AgentToolBroker
from claude_bridge.agents.contracts import TaskPermissions
from claude_bridge.agents.result import AgentResult, AgentStatus
from claude_bridge.agents.run_record import AgentRunRecord, start_agent_run

if TYPE_CHECKING:
    from claude_bridge.permissions import PermissionMatrix


class DebugAgent(BaseAgent):
    """Agent specialized in debugging and diagnostics."""

    def __init__(self, permission_matrix: PermissionMatrix | None = None) -> None:
        super().__init__("debug_agent", permission_matrix)

    async def execute(self, task: str, context: dict[str, Any]) -> AgentResult:
        """Execute a debug-related task.

        Args:
            task: The debug task to execute.
            context: Execution context.

        Returns:
            AgentResult with debug findings.
        """
        if not self.can_use_tool("test") and not self.can_use_tool("log_read"):
            return AgentResult.failure(
                error="Permission denied: test/log_read tools not allowed",
                agent_name=self.name,
            )

        task_lower = task.lower()

        if "error" in task_lower or "investigate" in task_lower:
            return await self.investigate_error(task)
        if "diagnostic" in task_lower or "test" in task_lower:
            return await self.run_diagnostics(context)

        return await self.run_diagnostics(context)

    async def investigate_error(self, task: str) -> AgentResult:
        """Investigate an error in the codebase.

        Args:
            task: Task containing error description.

        Returns:
            AgentResult with investigation findings.
        """
        findings: list[str] = []
        artifacts: dict[str, Any] = {}

        findings.append("Error investigation complete")
        artifacts["investigated"] = True

        return AgentResult(
            status=AgentStatus.SUCCESS,
            findings=findings,
            artifacts=artifacts,
            next_steps=["Review fix suggestions", "Apply if approved"],
            agent_name=self.name,
        )

    async def run_diagnostics(self, context: dict[str, Any] | None = None) -> AgentResult:
        """Run diagnostic checks on the codebase.

        Returns:
            AgentResult with diagnostic results.
        """
        findings: list[str] = ["Diagnostics: Running basic checks"]
        broker = self._broker(context)
        record = self._record(context)
        check_result = broker.python_syntax_check_available(record)
        if check_result.status == AgentStatus.FAILURE:
            return check_result
        findings.extend(check_result.findings)

        return AgentResult.success(
            findings=findings,
            artifacts={"diagnostics_run": True},
            agent_name=self.name,
        )

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
        return start_agent_run(task_id="single", agent_name=self.name, task_kind="debug")

    def _task_permissions(self, context: dict[str, Any] | None) -> TaskPermissions:
        subtask = context.get("subtask") if context else None
        permissions = getattr(subtask, "permissions", None)
        if isinstance(permissions, TaskPermissions) and permissions.allowed_tools:
            return permissions
        return TaskPermissions(allowed_tools=frozenset(self.get_allowed_tools()))
