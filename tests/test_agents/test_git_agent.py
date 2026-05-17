"""Tests for git agent."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


import pytest
from unittest.mock import patch, MagicMock

from claude_bridge.agents.sub.git_agent import GitAgent
from claude_bridge.agents.result import AgentStatus


@pytest.mark.asyncio
async def test_git_agent_init():
    agent = GitAgent()
    assert agent.name == "git_agent"


@pytest.mark.asyncio
async def test_git_agent_execute_status():
    agent = GitAgent()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout=" M file1.py\n?? file2.py",
            stderr="",
            returncode=0,
        )

        result = await agent.execute("git status", {})

        assert result.status == AgentStatus.SUCCESS
        assert any("file(s) changed" in f for f in result.findings)


@pytest.mark.asyncio
async def test_git_agent_execute_log():
    agent = GitAgent()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="abc1234 Fix bug\ndef5678 Add feature",
            stderr="",
            returncode=0,
        )

        result = await agent.execute("git log", {})

        assert result.status == AgentStatus.SUCCESS
        assert "commits" in result.artifacts


@pytest.mark.asyncio
async def test_git_agent_with_denied_file_operation():
    from claude_bridge.permissions import PermissionMatrix

    matrix = PermissionMatrix()
    agent = GitAgent(matrix)

    result = await agent.execute("git status with write", {})

    assert result.status == AgentStatus.SUCCESS


@pytest.mark.asyncio
async def test_git_status():
    agent = GitAgent()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=" M src/main.py", returncode=0)

        result = await agent.git_status()

        assert result.status == AgentStatus.SUCCESS
        assert result.agent_name == "git_agent"


@pytest.mark.asyncio
async def test_git_log():
    agent = GitAgent()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="abc1234 Test", returncode=0)

        result = await agent.git_log(limit=5)

        assert result.status == AgentStatus.SUCCESS
        assert "commits" in result.artifacts
