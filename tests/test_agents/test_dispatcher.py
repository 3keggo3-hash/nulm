"""Tests for task dispatcher."""

import pytest

from claude_bridge.agents.dispatcher import TaskDispatcher
from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.result import AgentResult, AgentStatus
from claude_bridge.agents.shared_memory import SharedMemorySpace


class DummyAgent(BaseAgent):
    async def execute(self, task: str, context: dict) -> AgentResult:
        return AgentResult.success(
            findings=[f"executed: {task}"],
            agent_name=self.name,
        )


@pytest.mark.asyncio
async def test_distribute_single_task():
    dispatcher = TaskDispatcher()
    agent = DummyAgent("test_agent")

    result = await dispatcher.distribute_single("test task", agent)

    assert result.status == AgentStatus.SUCCESS
    assert "executed: test task" in result.findings


@pytest.mark.asyncio
async def test_distribute_multiple_subtasks():
    dispatcher = TaskDispatcher()
    agents = [DummyAgent("agent1"), DummyAgent("agent2")]

    subtasks = [
        {"id": "1", "task": "task1", "agent_name": "agent1"},
        {"id": "2", "task": "task2", "agent_name": "agent2"},
    ]

    results = await dispatcher.distribute(subtasks, agents)

    assert len(results) == 2
    assert all(r.status == AgentStatus.SUCCESS for r in results)


@pytest.mark.asyncio
async def test_distribute_unknown_agent():
    dispatcher = TaskDispatcher()
    agents = [DummyAgent("known_agent")]

    subtasks = [
        {"id": "1", "task": "task1", "agent_name": "unknown_agent"},
    ]

    results = await dispatcher.distribute(subtasks, agents)

    assert len(results) == 1
    assert results[0].status == AgentStatus.FAILURE
    assert "not found" in results[0].error


@pytest.mark.asyncio
async def test_distribute_with_shared_memory():
    memory = SharedMemorySpace()
    dispatcher = TaskDispatcher(memory)
    agent = DummyAgent("test_agent")

    memory.write("shared_key", "shared_value")

    result = await dispatcher.distribute_single("test", agent)

    assert result.status == AgentStatus.SUCCESS