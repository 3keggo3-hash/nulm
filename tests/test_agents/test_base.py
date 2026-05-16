"""Tests for base agent."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


import pytest

from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.result import AgentResult
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
