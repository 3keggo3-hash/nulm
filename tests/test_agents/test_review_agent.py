"""Tests for review agent."""

import pytest
from unittest.mock import patch

from claude_bridge.agents.sub.review_agent import ReviewAgent
from claude_bridge.agents.result import AgentStatus


@pytest.mark.asyncio
async def test_review_agent_init():
    agent = ReviewAgent()
    assert agent.name == "review_agent"


@pytest.mark.asyncio
async def test_review_agent_execute_review():
    agent = ReviewAgent()

    with patch("claude_bridge.self_critique.self_critique") as mock_critique:
        mock_critique.return_value = {
            "ok": True,
            "message": "No issues found",
            "details": {"summary": {"total_issues": 0}},
        }

        result = await agent.execute("review changes", {})

        assert result.status == AgentStatus.SUCCESS


@pytest.mark.asyncio
async def test_review_agent_execute_quality():
    agent = ReviewAgent()

    with patch("claude_bridge.self_critique.self_critique") as mock_critique:
        mock_critique.return_value = {
            "ok": True,
            "message": "Quality check complete",
            "details": {"summary": {"by_category": {}}},
        }

        result = await agent.execute("check quality", {})

        assert result.status == AgentStatus.SUCCESS


@pytest.mark.asyncio
async def test_review_agent_permission_denied():
    from claude_bridge.permissions import PermissionMatrix

    matrix = PermissionMatrix()
    matrix._overrides = {}

    agent = ReviewAgent(matrix)

    result = await agent.execute("review code", {})

    assert result.status == AgentStatus.FAILURE
    assert "Permission denied" in result.error


@pytest.mark.asyncio
async def test_review_changes():
    agent = ReviewAgent()

    with patch("claude_bridge.self_critique.self_critique") as mock_critique:
        mock_critique.return_value = {
            "ok": False,
            "message": "2 issues found",
            "details": {"summary": {"total_issues": 2}},
        }

        result = await agent.review_changes("test")

        assert result.status == AgentStatus.PARTIAL


@pytest.mark.asyncio
async def test_check_quality():
    agent = ReviewAgent()

    with patch("claude_bridge.self_critique.self_critique") as mock_critique:
        mock_critique.return_value = {
            "ok": True,
            "message": "Quality check complete",
            "details": {"summary": {"by_category": {"style": 1}}},
        }

        result = await agent.check_quality()

        assert result.status == AgentStatus.SUCCESS
        assert result.next_steps