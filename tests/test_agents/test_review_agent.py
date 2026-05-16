"""Tests for review agent."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


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

        assert result.status in (AgentStatus.SUCCESS, AgentStatus.PARTIAL)


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

        assert result.status in (AgentStatus.SUCCESS, AgentStatus.PARTIAL)


@pytest.mark.asyncio
async def test_review_agent_with_denied_operation():
    from claude_bridge.permissions import PermissionMatrix

    matrix = PermissionMatrix()
    agent = ReviewAgent(matrix)

    result = await agent.execute("review changes", {})

    assert result.status in (AgentStatus.SUCCESS, AgentStatus.PARTIAL)


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

        assert result.status in (AgentStatus.SUCCESS, AgentStatus.PARTIAL)
        assert result.next_steps
