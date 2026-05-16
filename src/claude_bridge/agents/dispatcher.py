"""Task dispatcher for distributing work to sub-agents."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import asyncio
from typing import Any, cast

from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.result import AgentResult
from claude_bridge.agents.shared_memory import SharedMemorySpace


class TaskDispatcher:
    """Dispatches tasks to sub-agents using asyncio.gather."""

    def __init__(self, shared_memory: SharedMemorySpace | None = None) -> None:
        self.shared_memory = shared_memory or SharedMemorySpace()

    async def distribute(
        self,
        subtasks: list[dict[str, Any]],
        agents: list[BaseAgent],
    ) -> list[AgentResult]:
        """Distribute subtasks to agents and execute them in parallel.

        Args:
            subtasks: List of subtask dictionaries with 'task' and 'agent_name' keys.
            agents: List of BaseAgent instances to execute subtasks.

        Returns:
            List of AgentResult from each subtask execution.
        """
        agent_map = {agent.name: agent for agent in agents}

        async def execute_subtask(subtask: dict[str, Any]) -> AgentResult:
            agent_name = subtask.get("agent_name", "")
            task = subtask.get("task", "")

            agent = agent_map.get(agent_name)
            if agent is None:
                return AgentResult.failure(
                    error=f"Agent '{agent_name}' not found",
                    agent_name=agent_name,
                )

            context = {
                "shared_memory": self.shared_memory,
                "subtask_id": subtask.get("id"),
            }

            try:
                return await agent.execute(task, context)
            except Exception as e:
                return AgentResult.failure(
                    error=str(e),
                    agent_name=agent_name,
                )

        tasks = [execute_subtask(st) for st in subtasks]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_results: list[AgentResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                agent_name = subtasks[i].get("agent_name", "unknown")
                processed_results.append(
                    AgentResult.failure(
                        error=str(result),
                        agent_name=agent_name,
                    )
                )
            else:
                processed_results.append(cast(AgentResult, result))

        return processed_results

    async def distribute_single(
        self,
        task: str,
        agent: BaseAgent,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Execute a single task with an agent.

        Args:
            task: The task to execute.
            agent: The agent to execute with.
            context: Optional context dict.

        Returns:
            AgentResult from the execution.
        """
        ctx = dict(context) if context else {}
        ctx["shared_memory"] = self.shared_memory

        try:
            return await agent.execute(task, ctx)
        except Exception as e:
            return AgentResult.failure(error=str(e), agent_name=agent.name)
