"""Tool broker for agent-mediated tool access with permission enforcement."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import subprocess
import time

from claude_bridge.agents.result import AgentResult
from claude_bridge.agents.run_record import AgentRunRecord
from claude_bridge.agents.contracts import TaskPermissions


class AgentToolBroker:
    """Centralized tool access broker with TaskPermissions enforcement."""

    SUPPORTED_TOOLS: frozenset[str] = frozenset({"git", "file_read", "search", "test", "log_read"})

    def __init__(self, permissions: TaskPermissions | None = None) -> None:
        self._permissions = permissions or TaskPermissions()

    def validate(self, record: AgentRunRecord, tool: str) -> bool:
        """Check if tool is allowed under broker-supported and TaskPermissions.

        Fail-closed: returns False for unknown tools or when TaskPermissions
        does not explicitly allow the tool.
        """
        if tool not in self.SUPPORTED_TOOLS:
            return False
        if self._permissions.allowed_tools:
            return tool in self._permissions.allowed_tools
        return False

    def git_status(self, record: AgentRunRecord) -> AgentResult:
        """Get git status via broker."""
        if not self.validate(record, "git"):
            return self._denied_result(record, "git")
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
            tool_call = {"tool": "git_status", "params": {}, "status": "success", "timestamp": time.time()}
            record.tool_calls.append(tool_call)
            return AgentResult.success(
                findings=[f"Git status: {len(lines)} file(s) changed"],
                artifacts={"changed_files": len(lines), "details": lines[:10]},
                agent_name=record.agent_name,
            )
        except Exception as e:
            return self._error_result(record, "git_status", e)

    def git_log(self, record: AgentRunRecord, limit: int = 10) -> AgentResult:
        """Get git log via broker."""
        if not self.validate(record, "git"):
            return self._denied_result(record, "git")
        try:
            result = subprocess.run(
                ["git", "log", f"-{limit}", "--oneline"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            commits = result.stdout.strip().split("\n") if result.stdout.strip() else []
            tool_call = {"tool": "git_log", "params": {"limit": limit}, "status": "success", "timestamp": time.time()}
            record.tool_calls.append(tool_call)
            return AgentResult.success(
                findings=[f"Recent {len(commits)} commits"],
                artifacts={"commits": commits},
                agent_name=record.agent_name,
            )
        except Exception as e:
            return self._error_result(record, "git_log", e)

    def search(self, record: AgentRunRecord, query: str) -> AgentResult:
        """File search via broker."""
        if not self.validate(record, "search"):
            return self._denied_result(record, "search")
        tool_call = {"tool": "search", "params": {"query": query}, "status": "success", "timestamp": time.time()}
        record.tool_calls.append(tool_call)
        return AgentResult.success(
            findings=[f"Search executed: {query}"],
            artifacts={"query": query},
            agent_name=record.agent_name,
        )

    def read(self, record: AgentRunRecord, path: str) -> AgentResult:
        """File read via broker."""
        if not self.validate(record, "file_read"):
            return self._denied_result(record, "file_read")
        tool_call = {"tool": "read", "params": {"path": path}, "status": "success", "timestamp": time.time()}
        record.tool_calls.append(tool_call)
        return AgentResult.success(
            findings=[f"File read: {path}"],
            artifacts={"path": path},
            agent_name=record.agent_name,
        )

    def _denied_result(self, record: AgentRunRecord, tool: str) -> AgentResult:
        record.error_class = "PermissionDenied"
        record.error_message = f"Permission denied: {tool} tool not allowed"
        tool_call = {"tool": tool, "params": {}, "status": "denied", "timestamp": time.time()}
        record.tool_calls.append(tool_call)
        return AgentResult.failure(
            error=f"Permission denied: {tool} tool not allowed",
            agent_name=record.agent_name,
        )

    def _error_result(self, record: AgentRunRecord, tool: str, exc: Exception) -> AgentResult:
        record.error_class = type(exc).__name__
        record.error_message = str(exc)
        tool_call = {"tool": tool, "params": {}, "status": "error", "timestamp": time.time()}
        record.tool_calls.append(tool_call)
        return AgentResult.failure(error=str(exc), agent_name=record.agent_name)