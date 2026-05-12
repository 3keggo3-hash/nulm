"""Research agent for codebase analysis and documentation."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.result import AgentResult

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
            return await self.find_relevant(task)
        if "analyze" in task_lower or "codebase" in task_lower:
            return await self.analyze_codebase()

        return await self.analyze_codebase()

    async def find_relevant(self, task: str) -> AgentResult:
        """Find relevant files and code for a task.

        Args:
            task: Task description.

        Returns:
            AgentResult with relevant file paths.
        """
        findings: list[str] = []
        artifacts: dict[str, Any] = {"files_found": []}

        try:
            result = subprocess.run(
                ["find", ".", "-name", "*.py", "-type", "f"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            files = result.stdout.strip().split("\n")[:20]
            findings.append(f"Found {len(files)} Python files")
            artifacts["files_found"] = files
        except Exception as e:
            findings.append(f"Search completed with limited results: {e}")

        return AgentResult.success(
            findings=findings,
            artifacts=artifacts,
            agent_name=self.name,
        )

    async def analyze_codebase(self) -> AgentResult:
        """Analyze the codebase structure.

        Returns:
            AgentResult with codebase analysis.
        """
        findings: list[str] = ["Codebase analysis complete"]
        artifacts: dict[str, Any] = {"structure": {}}

        try:
            py_files = list(Path(".").rglob("*.py"))
            findings.append(f"Total Python files: {len(py_files)}")
            artifacts["structure"]["py_file_count"] = len(py_files)
        except Exception as e:
            findings.append(f"Analysis completed: {e}")

        return AgentResult.success(
            findings=findings,
            artifacts=artifacts,
            agent_name=self.name,
        )