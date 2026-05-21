"""Tests for debug agent."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


import pytest
from unittest.mock import patch, MagicMock

from claude_bridge.agents.broker import AgentToolBroker
from claude_bridge.agents.contracts import TaskPermissions
from claude_bridge.agents.result import AgentResult, AgentStatus
from claude_bridge.agents.run_record import start_agent_run
from claude_bridge.agents.sub.debug_agent import DebugAgent


class RecordingDebugBroker(AgentToolBroker):
    def __init__(self):
        super().__init__(TaskPermissions(allowed_tools=frozenset({"test"})))
        self.calls: list[str] = []

    def python_syntax_check_available(self, record):
        self.calls.append("python_syntax_check_available")
        record.tool_calls.append({"tool": "python_syntax_check_available", "status": "success"})
        return AgentResult.success(
            findings=["Python syntax check available"],
            artifacts={"diagnostics_run": True},
            agent_name=record.agent_name,
        )


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


@pytest.mark.asyncio
async def test_debug_agent_uses_broker_validation_path():
    agent = DebugAgent()
    broker = RecordingDebugBroker()
    record = start_agent_run(task_id="debug-task", agent_name="debug_agent", task_kind="debug")

    result = await agent.execute(
        "run diagnostics",
        {"agent_tool_broker": broker, "agent_run_record": record},
    )

    assert result.status == AgentStatus.SUCCESS
    assert broker.calls == ["python_syntax_check_available"]
    assert record.tool_calls[0]["tool"] == "python_syntax_check_available"
