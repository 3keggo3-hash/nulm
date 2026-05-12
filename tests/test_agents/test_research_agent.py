"""Tests for research agent."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from claude_bridge.agents.sub.research_agent import ResearchAgent
from claude_bridge.agents.result import AgentStatus


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
async def test_research_agent_permission_denied():
    from claude_bridge.permissions import PermissionMatrix

    matrix = PermissionMatrix()
    matrix._overrides = {}

    agent = ResearchAgent(matrix)

    result = await agent.execute("find files", {})

    assert result.status == AgentStatus.FAILURE
    assert "Permission denied" in result.error


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