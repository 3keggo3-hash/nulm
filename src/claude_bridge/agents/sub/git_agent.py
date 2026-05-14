"""Git agent for version control operations."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.result import AgentResult

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
            return await self.git_status()
        if "log" in task_lower:
            return await self.git_log()
        if "blame" in task_lower:
            return await self.git_blame(task)

        return await self.git_status()

    async def git_status(self) -> AgentResult:
        """Get git status of the repository.

        Returns:
            AgentResult with status information.
        """
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
            findings = [f"Git status: {len(lines)} file(s) changed"]
            if lines:
                findings.extend(lines[:10])
            return AgentResult.success(
                findings=findings,
                artifacts={"changed_files": len(lines), "details": lines},
                agent_name=self.name,
            )
        except Exception as e:
            return AgentResult.failure(error=str(e), agent_name=self.name)

    async def git_log(self, limit: int = 10) -> AgentResult:
        """Get recent git commits.

        Args:
            limit: Number of commits to retrieve.

        Returns:
            AgentResult with commit history.
        """
        try:
            result = subprocess.run(
                ["git", "log", f"-{limit}", "--oneline"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            commits = result.stdout.strip().split("\n") if result.stdout.strip() else []
            return AgentResult.success(
                findings=[f"Recent {len(commits)} commits"],
                artifacts={"commits": commits},
                agent_name=self.name,
            )
        except Exception as e:
            return AgentResult.failure(error=str(e), agent_name=self.name)

    async def git_blame(self, task: str) -> AgentResult:
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
        try:
            result = subprocess.run(
                ["git", "blame", file_path],
                capture_output=True,
                text=True,
                timeout=60,
            )
            lines = result.stdout.strip().split("\n")[:20]
            return AgentResult.success(
                findings=[f"Blame for {file_path}: {len(lines)} lines shown"],
                artifacts={"file": file_path, "blame_lines": lines},
                agent_name=self.name,
            )
        except Exception as e:
            return AgentResult.failure(error=str(e), agent_name=self.name)
