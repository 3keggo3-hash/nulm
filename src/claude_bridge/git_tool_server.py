"""Registration helpers for git-oriented MCP tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from claude_bridge.tool_registration import ToolRegistrationContext


def register_git_tools(
    *,
    mcp: Any,
    tool_options: Callable[..., dict[str, Any]],
    audit_tool_call: Callable[..., str],
    json_response: Callable[..., str],
    project_dir: Callable[[], Path],
    enabled_names: set[str] | None = None,
) -> dict[str, Any]:
    ctx = ToolRegistrationContext(
        mcp=mcp,
        tool_options=tool_options,
        audit_tool_call=audit_tool_call,
        enabled_names=enabled_names,
    )

    if ctx.should_register("commit_changes"):

        async def commit_changes(message: str) -> str:
            from claude_bridge.git_ops import commit_changes as _commit_changes

            started_at = ctx.now_ms()
            if not message.strip():
                result = json_response(
                    False,
                    "Commit message cannot be empty",
                    code="empty_message",
                    details={},
                )
                return audit_tool_call(
                    "commit_changes",
                    {"message": message},
                    result,
                    started_at=started_at,
                )
            payload = _commit_changes(message, project_dir=project_dir())
            result = json_response(
                payload["commit"],
                "Changes committed" if payload["commit"] else "Commit failed",
                details=payload,
            )
            return audit_tool_call(
                "commit_changes",
                {"message": message},
                result,
                started_at=started_at,
            )

        ctx.register(
            "commit_changes",
            "Commit all staged and unstaged changes in the current project with a message. "
            "Use this for batch commits when auto_commit is set to False on individual "
            "write_file / patch_file calls.",
            commit_changes,
            destructive=True,
        )

    return ctx.results
