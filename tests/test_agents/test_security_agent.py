"""Tests for security agent."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


import pytest

from claude_bridge.agents.sub.security_agent import SecurityAgent
from claude_bridge.agents.result import AgentStatus


@pytest.mark.asyncio
async def test_security_agent_init():
    agent = SecurityAgent()
    assert agent.name == "security_agent"


@pytest.mark.asyncio
async def test_security_agent_execute_scan():
    agent = SecurityAgent()

    result = await agent.execute("scan for vulnerabilities", {})

    assert result.status == AgentStatus.SUCCESS
    assert len(result.findings) > 0


@pytest.mark.asyncio
async def test_security_agent_execute_secrets():
    agent = SecurityAgent()

    result = await agent.execute("check for secrets", {})

    assert result.status == AgentStatus.SUCCESS


@pytest.mark.asyncio
async def test_security_agent_with_denied_operation():
    from claude_bridge.permissions import PermissionMatrix

    matrix = PermissionMatrix()
    agent = SecurityAgent(matrix)

    result = await agent.execute("scan vulnerabilities", {})

    assert result.status == AgentStatus.SUCCESS


@pytest.mark.asyncio
async def test_scan_vulnerabilities():
    agent = SecurityAgent()

    result = await agent.scan_vulnerabilities()

    assert result.status == AgentStatus.SUCCESS
    assert "vulnerabilities" in result.artifacts


@pytest.mark.asyncio
async def test_check_secrets():
    agent = SecurityAgent()

    result = await agent.check_secrets()

    assert result.status == AgentStatus.SUCCESS
    assert "secrets_found" in result.artifacts
