"""Tests for research agent."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from claude_bridge.agents.broker import AgentToolBroker
from claude_bridge.agents.contracts import TaskPermissions
from claude_bridge.agents.result import AgentResult, AgentStatus
from claude_bridge.agents.run_record import start_agent_run
from claude_bridge.agents.sub.research_agent import ResearchAgent


class RecordingResearchBroker(AgentToolBroker):
    def __init__(self):
        super().__init__(TaskPermissions(allowed_tools=frozenset({"search", "file_read"})))
        self.calls: list[str] = []

    def search_python_files(self, record, query, limit=20):
        self.calls.append("search_python_files")
        record.tool_calls.append({"tool": "search_python_files", "status": "success"})
        return AgentResult.success(
            findings=["Found 1 Python files"],
            artifacts={"files_found": ["src/example.py"]},
            agent_name=record.agent_name,
        )

    def count_python_files(self, record):
        self.calls.append("count_python_files")
        record.tool_calls.append({"tool": "count_python_files", "status": "success"})
        return AgentResult.success(
            findings=["Codebase analysis complete", "Total Python files: 1"],
            artifacts={"structure": {"py_file_count": 1}},
            agent_name=record.agent_name,
        )


@pytest.mark.asyncio
async def test_research_agent_init():
    agent = ResearchAgent()
    assert agent.name == "research_agent"


@pytest.mark.asyncio
async def test_research_agent_execute_find():
    agent = ResearchAgent()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="file1.py\nfile2.py", returncode=0)

        result = await agent.execute("find relevant files", {})

        assert result.status == AgentStatus.SUCCESS


@pytest.mark.asyncio
async def test_research_agent_execute_analyze():
    agent = ResearchAgent()

    with patch.object(Path, "rglob") as mock_rglob:
        mock_rglob.return_value = [Path("a.py"), Path("b.py")]

        result = await agent.execute("analyze codebase", {})

        assert result.status == AgentStatus.SUCCESS


@pytest.mark.asyncio
async def test_research_agent_with_denied_operation():
    from claude_bridge.permissions import PermissionMatrix

    matrix = PermissionMatrix()
    agent = ResearchAgent(matrix)

    result = await agent.execute("find relevant files", {})

    assert result.status == AgentStatus.SUCCESS


@pytest.mark.asyncio
async def test_find_relevant():
    agent = ResearchAgent()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="a.py\nb.py\nc.py", returncode=0)

        result = await agent.find_relevant("test task")

        assert result.status == AgentStatus.SUCCESS
        assert "files_found" in result.artifacts


@pytest.mark.asyncio
async def test_analyze_codebase():
    agent = ResearchAgent()

    with patch.object(Path, "rglob") as mock_rglob:
        mock_rglob.return_value = [Path("test.py")]

        result = await agent.analyze_codebase()

        assert result.status == AgentStatus.SUCCESS
        assert "structure" in result.artifacts


@pytest.mark.asyncio
async def test_research_agent_uses_broker_search_path():
    agent = ResearchAgent()
    broker = RecordingResearchBroker()
    record = start_agent_run(
        task_id="research-task",
        agent_name="research_agent",
        task_kind="research",
    )

    result = await agent.execute(
        "find relevant files",
        {"agent_tool_broker": broker, "agent_run_record": record},
    )

    assert result.status == AgentStatus.SUCCESS
    assert broker.calls == ["search_python_files"]
    assert record.tool_calls[0]["tool"] == "search_python_files"


@pytest.mark.asyncio
async def test_research_agent_uses_broker_analysis_path():
    agent = ResearchAgent()
    broker = RecordingResearchBroker()
    record = start_agent_run(
        task_id="research-task",
        agent_name="research_agent",
        task_kind="research",
    )

    result = await agent.execute(
        "analyze codebase",
        {"agent_tool_broker": broker, "agent_run_record": record},
    )

    assert result.status == AgentStatus.SUCCESS
    assert broker.calls == ["count_python_files"]
    assert record.tool_calls[0]["tool"] == "count_python_files"
