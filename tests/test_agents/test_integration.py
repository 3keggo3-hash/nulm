"""Integration tests for multi-agent system."""

import pytest

from claude_bridge.agents.orchestrator import OrchestratorAgent
from claude_bridge.agents.sub import (
    GitAgent,
    SecurityAgent,
    DebugAgent,
    ResearchAgent,
    ReviewAgent,
)
from claude_bridge.agents.shared_memory import SharedMemorySpace
from claude_bridge.agents.dispatcher import TaskDispatcher
from claude_bridge.agents.result import AgentStatus


@pytest.mark.asyncio
async def test_full_orchestration_flow():
    orchestrator = OrchestratorAgent()
    agents = [
        GitAgent(),
        SecurityAgent(),
        DebugAgent(),
        ResearchAgent(),
        ReviewAgent(),
    ]

    result = await orchestrator.orchestrate(
        "analyze codebase and check for security issues",
        agents,
    )

    assert result.status in (AgentStatus.SUCCESS, AgentStatus.PARTIAL)
    assert len(result.findings) > 0


@pytest.mark.asyncio
async def test_shared_memory_between_agents():
    memory = SharedMemorySpace()
    dispatcher = TaskDispatcher(memory)

    memory.write("task_context", "important_data")

    research_agent = ResearchAgent()
    result = await dispatcher.distribute_single("find files", research_agent)

    assert result.status == AgentStatus.SUCCESS


@pytest.mark.asyncio
async def test_parallel_agent_execution():
    agents = [ResearchAgent(), ResearchAgent()]

    subtasks = [
        {"id": "1", "task": "task1", "agent_name": "research_agent"},
        {"id": "2", "task": "task2", "agent_name": "research_agent"},
    ]

    dispatcher = TaskDispatcher()
    results = await dispatcher.distribute(subtasks, agents)

    assert len(results) == 2
    assert all(r.status == AgentStatus.SUCCESS for r in results)


@pytest.mark.asyncio
async def test_agent_permissions_enforced():
    from claude_bridge.permissions import PermissionMatrix

    matrix = PermissionMatrix()
    matrix.override_permission("git_agent", {"shell", "git"}, 300)

    git_agent = GitAgent(matrix)
    assert git_agent.can_use_tool("shell") is True

    matrix._overrides.clear()


@pytest.mark.asyncio
async def test_orchestrator_handles_partial_failure():
    orchestrator = OrchestratorAgent()

    class FailingAgent(ResearchAgent):
        async def execute(self, task: str, context: dict):
            from claude_bridge.agents.result import AgentResult

            return AgentResult.failure(error="Simulated failure", agent_name=self.name)

    agents = [FailingAgent()]

    result = await orchestrator.orchestrate("do something", agents)

    assert result.status == AgentStatus.PARTIAL
    assert result.error is not None


@pytest.mark.asyncio
async def test_multi_keyword_decomposition():
    orchestrator = OrchestratorAgent()

    subtasks = await orchestrator.decompose(
        "git commit and security audit with debug",
    )

    agent_names = [st["agent_name"] for st in subtasks]
    assert "git_agent" in agent_names
    assert "security_agent" in agent_names
    assert "debug_agent" in agent_names
