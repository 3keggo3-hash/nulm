"""Orchestrator agent for task decomposition and result synthesis."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.dispatcher import TaskDispatcher
from claude_bridge.agents.result import AgentResult, AgentStatus
from claude_bridge.agents.shared_memory import SharedMemorySpace

if TYPE_CHECKING:
    from claude_bridge.permissions import PermissionMatrix


class OrchestratorAgent(BaseAgent):
    """Orchestrator agent that decomposes tasks and coordinates sub-agents."""

    def __init__(
        self,
        permission_matrix: PermissionMatrix | None = None,
        shared_memory: SharedMemorySpace | None = None,
    ) -> None:
        super().__init__("orchestrator", permission_matrix)
        self._shared_memory = shared_memory or SharedMemorySpace()
        self._dispatcher = TaskDispatcher(self._shared_memory)

    async def execute(self, task: str, context: dict[str, Any]) -> AgentResult:
        """Execute task through orchestration.

        Args:
            task: The task to orchestrate.
            context: Context with shared_memory and sub-agents.

        Returns:
            Synthesized AgentResult from all sub-agents.
        """
        subtasks = await self.decompose(task)

        agents: list[BaseAgent] = context.get("agents", [])
        results = await self._dispatcher.distribute(subtasks, agents)

        return await self.synthesize(results)

    async def decompose(self, task: str) -> list[dict[str, Any]]:
        """Decompose a task into subtasks for sub-agents.

        Args:
            task: The task to decompose.

        Returns:
            List of subtask dictionaries.
        """
        task_lower = task.lower()
        subtasks: list[dict[str, Any]] = []

        if any(kw in task_lower for kw in ["git", "commit", "branch", "diff", "log"]):
            subtasks.append({
                "id": "git_task",
                "task": task,
                "agent_name": "git_agent",
            })

        if any(kw in task_lower for kw in ["security", "vuln", "secret", "audit"]):
            subtasks.append({
                "id": "security_task",
                "task": task,
                "agent_name": "security_agent",
            })

        if any(kw in task_lower for kw in ["debug", "error", "fix", "crash"]):
            subtasks.append({
                "id": "debug_task",
                "task": task,
                "agent_name": "debug_agent",
            })

        if any(kw in task_lower for kw in ["research", "find", "search", "analyze"]):
            subtasks.append({
                "id": "research_task",
                "task": task,
                "agent_name": "research_agent",
            })

        if any(kw in task_lower for kw in ["review", "check", "quality", "critique"]):
            subtasks.append({
                "id": "review_task",
                "task": task,
                "agent_name": "review_agent",
            })

        if not subtasks:
            subtasks.append({
                "id": "general_task",
                "task": task,
                "agent_name": "research_agent",
            })

        return subtasks

    async def synthesize(self, results: list[AgentResult]) -> AgentResult:
        """Synthesize results from sub-agents into a single response.

        Args:
            results: List of AgentResult from sub-agents.

        Returns:
            Synthesized AgentResult.
        """
        all_findings: list[str] = []
        all_artifacts: dict[str, Any] = {}
        all_next_steps: list[str] = []
        errors: list[str] = []

        for result in results:
            all_findings.extend(result.findings)
            all_artifacts.update(result.artifacts)
            all_next_steps.extend(result.next_steps)
            if result.error:
                errors.append(result.error)

        if errors:
            return AgentResult(
                status=AgentStatus.PARTIAL,
                findings=all_findings,
                artifacts=all_artifacts,
                next_steps=all_next_steps,
                agent_name=self.name,
                error="; ".join(errors),
            )

        return AgentResult(
            status=AgentStatus.SUCCESS,
            findings=all_findings,
            artifacts=all_artifacts,
            next_steps=all_next_steps,
            agent_name=self.name,
        )

    async def orchestrate(self, task: str, agents: list[BaseAgent]) -> AgentResult:
        """Main entry point for orchestration.

        Args:
            task: The task to orchestrate.
            agents: List of sub-agents to distribute work to.

        Returns:
            Synthesized result from all agents.
        """
        context = {
            "agents": agents,
            "shared_memory": self._shared_memory,
        }
        return await self.execute(task, context)