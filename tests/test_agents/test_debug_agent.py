"""Tests for debug agent."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


import pytest
from unittest.mock import patch, MagicMock

from claude_bridge.agents.sub.debug_agent import DebugAgent
from claude_bridge.agents.result import AgentStatus


@pytest.mark.asyncio
async def test_debug_agent_init():
    agent = DebugAgent()
    assert agent.name == "debug_agent"


@pytest.mark.asyncio
async def test_debug_agent_execute_error():
    agent = DebugAgent()

    result = await agent.execute("investigate error", {})

    assert result.status == AgentStatus.SUCCESS


@pytest.mark.asyncio
async def test_debug_agent_execute_diagnostics():
    agent = DebugAgent()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", returncode=0)

        result = await agent.execute("run diagnostics", {})

        assert result.status == AgentStatus.SUCCESS


@pytest.mark.asyncio
async def test_debug_agent_with_denied_operation():
    from claude_bridge.permissions import PermissionMatrix

    matrix = PermissionMatrix()
    agent = DebugAgent(matrix)

    result = await agent.execute("run diagnostics", {})

    assert result.status == AgentStatus.SUCCESS


@pytest.mark.asyncio
async def test_investigate_error():
    agent = DebugAgent()

    result = await agent.investigate_error("error in code")

    assert result.status == AgentStatus.SUCCESS
    assert result.next_steps


@pytest.mark.asyncio
async def test_run_diagnostics():
    agent = DebugAgent()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", returncode=0)

        result = await agent.run_diagnostics()

        assert result.status == AgentStatus.SUCCESS
        assert "diagnostics_run" in result.artifacts
