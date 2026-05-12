"""Tests for permissions module."""

import pytest
import time

from claude_bridge.permissions import (
    PermissionMatrix,
    PermissionOverride,
    AgentPermissionError,
    get_agent,
)
from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.result import AgentResult


class DummyTestAgent(BaseAgent):
    async def execute(self, task: str, context: dict) -> AgentResult:
        return AgentResult.success(agent_name=self.name)


def test_permission_matrix_can_execute_allowed():
    matrix = PermissionMatrix()
    assert matrix.can_execute("git_agent", "git") is True
    assert matrix.can_execute("git_agent", "file_read") is True


def test_permission_matrix_can_execute_denied():
    matrix = PermissionMatrix()
    assert matrix.can_execute("git_agent", "shell") is False
    assert matrix.can_execute("git_agent", "network") is False


def test_permission_matrix_unknown_agent():
    matrix = PermissionMatrix()
    assert matrix.can_execute("unknown_agent", "git") is False


def test_permission_matrix_override():
    matrix = PermissionMatrix()
    matrix.override_permission("git_agent", {"shell"}, 5)

    assert matrix.can_execute("git_agent", "shell") is True


def test_permission_matrix_override_expires():
    matrix = PermissionMatrix()
    matrix.override_permission("git_agent", {"shell"}, 1)
    time.sleep(1.1)

    assert matrix.can_execute("git_agent", "shell") is False


def test_permission_matrix_get_agent_tools():
    matrix = PermissionMatrix()
    tools = matrix.get_agent_tools("git_agent")

    assert "git" in tools
    assert "file_read" in tools


def test_permission_matrix_clear_expired():
    matrix = PermissionMatrix()
    matrix.override_permission("git_agent", {"shell"}, 1)
    time.sleep(1.1)

    matrix.clear_expired_overrides()

    assert matrix.can_execute("git_agent", "shell") is False


def test_permission_override_is_active():
    override = PermissionOverride(
        agent="test",
        allow={"tool1"},
        duration=10,
        expires_at=time.monotonic() + 5,
    )
    assert override.is_active() is True


def test_permission_override_expired():
    override = PermissionOverride(
        agent="test",
        allow={"tool1"},
        duration=10,
        expires_at=time.monotonic() - 1,
    )
    assert override.is_active() is False


def test_agent_permission_error():
    error = AgentPermissionError("git_agent", "shell")
    assert error.agent == "git_agent"
    assert error.tool == "shell"
    assert "git_agent" in str(error)
    assert "shell" in str(error)


def test_get_agent_git():
    agent = get_agent("git_agent")
    assert agent.name == "git_agent"


def test_get_agent_security():
    agent = get_agent("security_agent")
    assert agent.name == "security_agent"


def test_get_agent_debug():
    agent = get_agent("debug_agent")
    assert agent.name == "debug_agent"


def test_get_agent_research():
    agent = get_agent("research_agent")
    assert agent.name == "research_agent"


def test_get_agent_review():
    agent = get_agent("review_agent")
    assert agent.name == "review_agent"


def test_get_agent_orchestrator():
    agent = get_agent("orchestrator")
    assert agent.name == "orchestrator"


def test_get_agent_unknown():
    with pytest.raises(ValueError, match="Unknown agent"):
        get_agent("nonexistent_agent")


@pytest.mark.asyncio
async def test_get_agent_executes():
    agent = get_agent("research_agent")
    result = await agent.execute("test task", {})

    assert result.agent_name == "research_agent"