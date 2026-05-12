"""Review agent for code quality review and self-critique."""

from __future__ import annotations

from typing import Any

from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.result import AgentResult, AgentStatus
from claude_bridge.self_critique import self_critique


class ReviewAgent(BaseAgent):
    """Agent specialized in code review and quality checks."""

    def __init__(self, permission_matrix: PermissionMatrix | None = None) -> None:
        super().__init__("review_agent", permission_matrix)

    async def execute(self, task: str, context: dict[str, Any]) -> AgentResult:
        """Execute a review task.

        Args:
            task: The review task to execute.
            context: Execution context.

        Returns:
            AgentResult with review findings.
        """
        if not self.can_use_tool("file_read"):
            return AgentResult.failure(
                error="Permission denied: file_read tool not allowed",
                agent_name=self.name,
            )

        task_lower = task.lower()

        if "review" in task_lower or "change" in task_lower:
            return await self.review_changes(task)
        if "quality" in task_lower or "check" in task_lower:
            return await self.check_quality()

        return await self.check_quality()

    async def review_changes(self, task: str) -> AgentResult:
        """Review code changes.

        Args:
            task: Task with change description.

        Returns:
            AgentResult with review findings.
        """
        result = self_critique("project", criteria=["style", "security"])

        findings = [result.get("message", "Review complete")]
        if "details" in result:
            summary = result["details"].get("summary", {})
            total = summary.get("total_issues", 0)
            findings.append(f"Total issues found: {total}")

        return AgentResult(
            status=AgentStatus.SUCCESS if result.get("ok") else AgentStatus.PARTIAL,
            findings=findings,
            artifacts={"review_result": result},
            agent_name=self.name,
        )

    async def check_quality(self) -> AgentResult:
        """Check code quality across the project.

        Returns:
            AgentResult with quality metrics.
        """
        result = self_critique(
            "project",
            criteria=["complexity", "style", "naming", "test_coverage"],
        )

        findings = [result.get("message", "Quality check complete")]
        if "details" in result:
            summary = result["details"].get("summary", {})
            by_category = summary.get("by_category", {})
            findings.append(f"Issues by category: {by_category}")

        return AgentResult(
            status=AgentStatus.SUCCESS if result.get("ok") else AgentStatus.PARTIAL,
            findings=findings,
            artifacts={"quality_result": result},
            next_steps=["Review issues", "Apply fixes if needed"],
            agent_name=self.name,
        )