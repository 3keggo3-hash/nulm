"""Registration helpers for shell-related MCP tools."""

from __future__ import annotations

import time
from typing import Any, Callable


def register_shell_tools(
    *,
    mcp: Any,
    tool_options: Callable[..., dict[str, Any]],
    audit_tool_call: Callable[..., str],
    json_response: Callable[..., str],
    analyze_shell_command_impl: Any,
    run_shell_impl: Any,
    start_process_impl: Any,
    read_process_output_impl: Any,
    list_process_sessions_impl: Any,
    kill_process_impl: Any,
    interact_with_process_impl: Any,
    request_approval: Any,
    project_dir: Any,
    shell_timeout: Any,
) -> dict[str, Any]:
    """Register all shell-related MCP tools and return a dict of callables."""

    def _is_interactive_command(command: str) -> bool:
        return bool(
            analyze_shell_command_impl(command).get("code")
            == "interactive_command_unsupported"
        )

    def _normalize_command_for_safety(command: str) -> str:
        details = analyze_shell_command_impl(command).get("details", {})
        return str(details.get("normalized_command", command.strip().lower()))

    def _blocked_command_reason(stripped: str, tokens: list[str]) -> str | None:
        analysis = analyze_shell_command_impl(stripped)
        if analysis.get("code") == "blocked_command":
            details = analysis.get("details", {})
            if isinstance(details, dict):
                blocked_pattern = details.get("blocked_pattern")
                return blocked_pattern if isinstance(blocked_pattern, str) else None
        return None

    @mcp.tool(
        **tool_options(
            "Analyze a shell command without executing it. Use this before risky "
            "commands or when you need to explain command risk to the user.",
            read_only=True,
        )
    )
    async def analyze_shell_command(command: str) -> str:
        started_at = time.perf_counter()
        analysis = analyze_shell_command_impl(command)
        result = json_response(
            analysis["ok"],
            analysis["message"],
            code=analysis.get("code"),
            details=analysis["details"],
        )
        return audit_tool_call(
            "analyze_shell_command", {"command": command}, result, started_at=started_at
        )

    @mcp.tool(
        **tool_options(
            "Run a non-interactive shell command with approval. Prefer read-only or "
            "validation commands such as pytest, ruff, git status, or ls. "
            "Never use this to bypass file tools, and inspect failures before "
            "retrying with a different command.",
            destructive=True,
            open_world=True,
        )
    )
    async def run_shell(command: str) -> str:
        started_at = time.perf_counter()
        result = await run_shell_impl(
            command,
            request_approval=request_approval,
            project_dir=project_dir,
            shell_timeout=shell_timeout,
        )
        return audit_tool_call("run_shell", {"command": command}, result, started_at=started_at)

    @mcp.tool(
        **tool_options(
            "Start a long-running non-interactive process with approval. Use this for "
            "watchers, dev servers, or commands that may exceed run_shell timeout.",
            destructive=True,
            open_world=True,
        )
    )
    async def start_process(command: str) -> str:
        started_at = time.perf_counter()
        result = await start_process_impl(
            command,
            request_approval=request_approval,
            project_dir=project_dir,
        )
        return audit_tool_call("start_process", {"command": command}, result, started_at=started_at)

    @mcp.tool(
        **tool_options(
            "Read paginated output from a previously started process session. "
            "Use offset and limit to fetch the next output window without "
            "rerunning the command.",
            read_only=True,
        )
    )
    async def read_process_output(session_id: str, offset: int = 0, limit: int = 4000) -> str:
        started_at = time.perf_counter()
        result = await read_process_output_impl(session_id=session_id, offset=offset, limit=limit)
        return audit_tool_call(
            "read_process_output",
            {"session_id": session_id, "offset": offset, "limit": limit},
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "List active and recent process sessions started by Claude Bridge. "
            "Use this to find session ids before reading output or terminating "
            "a process.",
            read_only=True,
        )
    )
    async def list_process_sessions() -> str:
        started_at = time.perf_counter()
        result = await list_process_sessions_impl()
        return audit_tool_call("list_process_sessions", {}, result, started_at=started_at)

    @mcp.tool(
        **tool_options(
            "Terminate a Claude Bridge managed process session by id. "
            "Use this to stop a watcher or server that you started earlier.",
            destructive=True,
        )
    )
    async def kill_process(session_id: str) -> str:
        started_at = time.perf_counter()
        result = await kill_process_impl(session_id=session_id, request_approval=request_approval)
        return audit_tool_call(
            "kill_process", {"session_id": session_id}, result, started_at=started_at
        )

    @mcp.tool(
        **tool_options(
            "Send input to a running process session. Optionally close stdin to "
            "deliver EOF for commands that wait on end-of-input before exiting.",
            destructive=True,
            open_world=True,
        )
    )
    async def interact_with_process(
        session_id: str, input: str = "", close_stdin: bool = False
    ) -> str:
        started_at = time.perf_counter()
        result = await interact_with_process_impl(
            session_id=session_id,
            input=input,
            close_stdin=close_stdin,
            request_approval=request_approval,
        )
        return audit_tool_call(
            "interact_with_process",
            {
                "session_id": session_id,
                "input_length": len(input),
                "close_stdin": close_stdin,
            },
            result,
            started_at=started_at,
        )

    return {
        "analyze_shell_command": analyze_shell_command,
        "run_shell": run_shell,
        "start_process": start_process,
        "read_process_output": read_process_output,
        "list_process_sessions": list_process_sessions,
        "kill_process": kill_process,
        "interact_with_process": interact_with_process,
        "_is_interactive_command": _is_interactive_command,
        "_normalize_command_for_safety": _normalize_command_for_safety,
        "_blocked_command_reason": _blocked_command_reason,
    }
