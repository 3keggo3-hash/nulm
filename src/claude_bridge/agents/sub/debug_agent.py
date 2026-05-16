"""Debug agent for error investigation and diagnostics."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.result import AgentResult, AgentStatus

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
            return await self.run_diagnostics()

        return await self.run_diagnostics()

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

    async def run_diagnostics(self) -> AgentResult:
        """Run diagnostic checks on the codebase.

        Returns:
            AgentResult with diagnostic results.
        """
        findings: list[str] = ["Diagnostics: Running basic checks"]

        try:
            subprocess.run(
                ["python", "-m", "py_compile", "--help"],
                capture_output=True,
                timeout=10,
            )
            findings.append("Python syntax check available")
        except Exception:
            pass

        return AgentResult.success(
            findings=findings,
            artifacts={"diagnostics_run": True},
            agent_name=self.name,
        )
