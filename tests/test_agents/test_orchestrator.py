"""Tests for orchestrator agent."""

import pytest

from claude_bridge.agents.orchestrator import OrchestratorAgent
from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.result import AgentResult, AgentStatus


class DummySubAgent(BaseAgent):
    async def execute(self, task: str, context: dict) -> AgentResult:
        return AgentResult.success(
            findings=[f"{self.name} processed: {task}"],
            artifacts={"from": self.name},
            agent_name=self.name,
        )


@pytest.mark.asyncio
async def test_orchestrator_decompose_git_task():
    orchestrator = OrchestratorAgent()
    subtasks = await orchestrator.decompose("git commit -m 'test'")

    assert len(subtasks) >= 1
    assert any(st["agent_name"] == "git_agent" for st in subtasks)


@pytest.mark.asyncio
async def test_orchestrator_decompose_security_task():
    orchestrator = OrchestratorAgent()
    subtasks = await orchestrator.decompose("scan for vulnerabilities")

    assert len(subtasks) >= 1
    assert any(st["agent_name"] == "security_agent" for st in subtasks)


@pytest.mark.asyncio
async def test_orchestrator_decompose_debug_task():
    orchestrator = OrchestratorAgent()
    subtasks = await orchestrator.decompose("debug the error")

    assert len(subtasks) >= 1
    assert any(st["agent_name"] == "debug_agent" for st in subtasks)


@pytest.mark.asyncio
async def test_orchestrator_decompose_multiple_keywords():
    orchestrator = OrchestratorAgent()
    subtasks = await orchestrator.decompose("git commit and security audit")

    agent_names = [st["agent_name"] for st in subtasks]
    assert "git_agent" in agent_names
    assert "security_agent" in agent_names


@pytest.mark.asyncio
async def test_orchestrator_synthesize_success():
    orchestrator = OrchestratorAgent()
    results = [
        AgentResult.success(findings=["finding1"], agent_name="agent1"),
        AgentResult.success(findings=["finding2"], agent_name="agent2"),
    ]

    synthesized = await orchestrator.synthesize(results)

    assert synthesized.status == AgentStatus.SUCCESS
    assert "finding1" in synthesized.findings
    assert "finding2" in synthesized.findings


@pytest.mark.asyncio
async def test_orchestrator_synthesize_with_errors():
    orchestrator = OrchestratorAgent()
    results = [
        AgentResult.success(findings=["finding1"], agent_name="agent1"),
        AgentResult.failure(error="error1", agent_name="agent2"),
    ]

    synthesized = await orchestrator.synthesize(results)

    assert synthesized.status == AgentStatus.PARTIAL
    assert "error1" in synthesized.error


@pytest.mark.asyncio
async def test_orchestrator_orchestrate():
    orchestrator = OrchestratorAgent()
    agents = [DummySubAgent("research_agent")]

    result = await orchestrator.orchestrate("analyze the codebase", agents)

    assert result.status == AgentStatus.SUCCESS
    assert len(result.findings) > 0


@pytest.mark.asyncio
async def test_orchestrator_execute():
    orchestrator = OrchestratorAgent()
    context = {"agents": [DummySubAgent("research_agent")]}

    result = await orchestrator.execute("find relevant files", context)

    assert result.status == AgentStatus.SUCCESS