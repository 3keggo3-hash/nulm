"""Tests for base agent."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


import pytest

from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.result import AgentResult
from claude_bridge.audit import _load_records, current_session_id
from claude_bridge.permissions import PermissionMatrix


class DummyAgent(BaseAgent):
    async def execute(self, task: str, context: dict) -> AgentResult:
        return AgentResult.success(agent_name=self.name)


def test_base_agent_init():
    agent = DummyAgent("test_agent")
    assert agent.name == "test_agent"


def test_base_agent_can_use_tool_allowed():
    matrix = PermissionMatrix()
    agent = DummyAgent("git_agent", matrix)
    assert agent.can_use_tool("git") is True


def test_base_agent_can_use_tool_denied():
    matrix = PermissionMatrix()
    agent = DummyAgent("git_agent", matrix)
    assert agent.can_use_tool("shell") is False


def test_get_allowed_tools():
    matrix = PermissionMatrix()
    agent = DummyAgent("git_agent", matrix)
    tools = agent.get_allowed_tools()
    assert "git" in tools
    assert "file_read" in tools


def test_base_agent_abstract():
    with pytest.raises(TypeError):
        BaseAgent("abstract")  # Cannot instantiate abstract class


@pytest.mark.asyncio
async def test_execute_traced_records_direct_agent_run():
    agent = DummyAgent("research_agent")

    result, record = await agent.execute_traced("inspect", {}, task_id="direct_task")

    assert result.agent_name == "research_agent"
    assert record.task_id == "direct_task"
    assert record.status == "success"
    audit_records = _load_records(current_session_id())
    agent_records = [item for item in audit_records if item.get("tool_name") == "agent_run"]
    assert agent_records[-1]["params"]["task_id"] == "direct_task"
