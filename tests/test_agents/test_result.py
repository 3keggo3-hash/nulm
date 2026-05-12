"""Tests for agent result dataclass."""

from claude_bridge.agents.result import AgentResult, AgentStatus


def test_agent_result_success():
    result = AgentResult.success(
        findings=["finding1", "finding2"],
        artifacts={"key": "value"},
        next_steps=["step1"],
        agent_name="test_agent",
    )
    assert result.status == AgentStatus.SUCCESS
    assert len(result.findings) == 2
    assert result.artifacts["key"] == "value"
    assert result.agent_name == "test_agent"
    assert result.error is None


def test_agent_result_failure():
    result = AgentResult.failure(
        error="Something went wrong",
        findings=["partial finding"],
        agent_name="test_agent",
    )
    assert result.status == AgentStatus.FAILURE
    assert result.error == "Something went wrong"
    assert result.agent_name == "test_agent"


def test_agent_result_to_dict():
    result = AgentResult.success(
        findings=["finding"],
        artifacts={"a": 1},
        next_steps=["step"],
        agent_name="agent",
    )
    d = result.to_dict()
    assert d["status"] == "success"
    assert d["findings"] == ["finding"]
    assert d["artifacts"] == {"a": 1}
    assert d["next_steps"] == ["step"]
    assert d["agent_name"] == "agent"


def test_agent_status_enum():
    assert AgentStatus.SUCCESS.value == "success"
    assert AgentStatus.FAILURE.value == "failure"
    assert AgentStatus.PARTIAL.value == "partial"
    assert AgentStatus.PENDING.value == "pending"