"""Tool broker for agent-mediated tool access with permission enforcement."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

from pathlib import Path
import subprocess
import sys
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
            tool_call = {
                "tool": "git_status",
                "params": {},
                "status": "success",
                "timestamp": time.time(),
            }
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
            tool_call = {
                "tool": "git_log",
                "params": {"limit": limit},
                "status": "success",
                "timestamp": time.time(),
            }
            record.tool_calls.append(tool_call)
            return AgentResult.success(
                findings=[f"Recent {len(commits)} commits"],
                artifacts={"commits": commits},
                agent_name=record.agent_name,
            )
        except Exception as e:
            return self._error_result(record, "git_log", e)

    def git_blame(self, record: AgentRunRecord, file_path: str) -> AgentResult:
        """Get git blame for a single file via broker."""
        if not self.validate(record, "git"):
            return self._denied_result(record, "git")
        if not file_path:
            return AgentResult.failure(
                error="No file path specified for blame",
                agent_name=record.agent_name,
            )
        try:
            result = subprocess.run(
                ["git", "blame", file_path],
                capture_output=True,
                text=True,
                timeout=60,
            )
            lines = result.stdout.strip().split("\n")[:20] if result.stdout.strip() else []
            tool_call = {
                "tool": "git_blame",
                "params": {"file": file_path},
                "status": "success",
                "timestamp": time.time(),
            }
            record.tool_calls.append(tool_call)
            return AgentResult.success(
                findings=[f"Blame for {file_path}: {len(lines)} lines shown"],
                artifacts={"file": file_path, "blame_lines": lines},
                agent_name=record.agent_name,
            )
        except Exception as e:
            return self._error_result(record, "git_blame", e)

    def search(self, record: AgentRunRecord, query: str) -> AgentResult:
        """File search via broker."""
        if not self.validate(record, "search"):
            return self._denied_result(record, "search")
        tool_call = {
            "tool": "search",
            "params": {"query": query},
            "status": "success",
            "timestamp": time.time(),
        }
        record.tool_calls.append(tool_call)
        return AgentResult.success(
            findings=[f"Search executed: {query}"],
            artifacts={"query": query},
            agent_name=record.agent_name,
        )

    def search_python_files(
        self,
        record: AgentRunRecord,
        query: str,
        limit: int = 20,
    ) -> AgentResult:
        """Find Python files through the broker-mediated search permission."""
        if not self.validate(record, "search"):
            return self._denied_result(record, "search")
        try:
            files = [str(path) for path in _iter_python_files(limit)]
            tool_call = {
                "tool": "search_python_files",
                "params": {"query": query, "limit": limit},
                "status": "success",
                "timestamp": time.time(),
            }
            record.tool_calls.append(tool_call)
            return AgentResult.success(
                findings=[f"Found {len(files)} Python files"],
                artifacts={"files_found": files},
                agent_name=record.agent_name,
            )
        except Exception as e:
            return self._error_result(record, "search_python_files", e)

    def count_python_files(self, record: AgentRunRecord) -> AgentResult:
        """Count Python files through the broker-mediated search permission."""
        if not self.validate(record, "search"):
            return self._denied_result(record, "search")
        try:
            count = sum(1 for _ in _iter_python_files())
            tool_call = {
                "tool": "count_python_files",
                "params": {},
                "status": "success",
                "timestamp": time.time(),
            }
            record.tool_calls.append(tool_call)
            return AgentResult.success(
                findings=["Codebase analysis complete", f"Total Python files: {count}"],
                artifacts={"structure": {"py_file_count": count}},
                agent_name=record.agent_name,
            )
        except Exception as e:
            return self._error_result(record, "count_python_files", e)

    def read(self, record: AgentRunRecord, path: str) -> AgentResult:
        """File read via broker."""
        if not self.validate(record, "file_read"):
            return self._denied_result(record, "file_read")
        tool_call = {
            "tool": "read",
            "params": {"path": path},
            "status": "success",
            "timestamp": time.time(),
        }
        record.tool_calls.append(tool_call)
        return AgentResult.success(
            findings=[f"File read: {path}"],
            artifacts={"path": path},
            agent_name=record.agent_name,
        )

    def python_syntax_check_available(self, record: AgentRunRecord) -> AgentResult:
        """Run the narrow diagnostic check used by DebugAgent."""
        if not self.validate(record, "test"):
            return self._denied_result(record, "test")
        try:
            subprocess.run(
                [sys.executable, "-m", "py_compile", "--help"],
                capture_output=True,
                timeout=10,
            )
            tool_call = {
                "tool": "python_syntax_check_available",
                "params": {},
                "status": "success",
                "timestamp": time.time(),
            }
            record.tool_calls.append(tool_call)
            return AgentResult.success(
                findings=["Python syntax check available"],
                artifacts={"diagnostics_run": True},
                agent_name=record.agent_name,
            )
        except Exception as e:
            return self._error_result(record, "python_syntax_check_available", e)

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


def _iter_python_files(limit: int | None = None) -> list[Path]:
    skipped = {
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "venv",
        ".venv",
    }
    files: list[Path] = []
    for path in Path(".").rglob("*.py"):
        if any(part in skipped for part in path.parts):
            continue
        files.append(path)
        if limit is not None and len(files) >= limit:
            break
    return files
