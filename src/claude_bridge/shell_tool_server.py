"""Registration helpers for shell-related MCP tools."""

from __future__ import annotations

from typing import Any, Callable

from claude_bridge.tool_registration import ToolRegistrationContext


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
    ai_provider_getter: Callable[[], Any] | None = None,
    enabled_names: set[str] | None = None,
) -> dict[str, Any]:
    ctx = ToolRegistrationContext(
        mcp=mcp,
        tool_options=tool_options,
        audit_tool_call=audit_tool_call,
        enabled_names=enabled_names,
    )
    _get_ai = ai_provider_getter

    def _is_interactive_command(command: str) -> bool:
        return bool(
            analyze_shell_command_impl(command).get("code") == "interactive_command_unsupported"
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

    ctx.add_extra("_is_interactive_command", _is_interactive_command)
    ctx.add_extra("_normalize_command_for_safety", _normalize_command_for_safety)
    ctx.add_extra("_blocked_command_reason", _blocked_command_reason)

    if ctx.should_register("analyze_shell_command"):

        async def analyze_shell_command(command: str) -> str:
            started_at = ctx.now_ms()
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

        ctx.register(
            "analyze_shell_command",
            "Analyze a shell command without executing it.",
            analyze_shell_command,
            read_only=True,
        )

    if ctx.should_register("run_shell"):

        async def run_shell(command: str) -> str:
            started_at = ctx.now_ms()
            result = await run_shell_impl(
                command,
                request_approval=request_approval,
                project_dir=project_dir,
                shell_timeout=shell_timeout,
                ai_provider=_get_ai() if _get_ai else None,
            )
            return audit_tool_call("run_shell", {"command": command}, result, started_at=started_at)

        ctx.register(
            "run_shell",
            "Run a non-interactive shell command with approval.",
            run_shell,
            destructive=True,
            open_world=True,
        )

    if ctx.should_register("start_process"):

        async def start_process(command: str) -> str:
            started_at = ctx.now_ms()
            result = await start_process_impl(
                command,
                request_approval=request_approval,
                project_dir=project_dir,
                ai_provider=_get_ai() if _get_ai else None,
            )
            return audit_tool_call(
                "start_process", {"command": command}, result, started_at=started_at
            )

        ctx.register(
            "start_process",
            "Start a long-running non-interactive process with approval.",
            start_process,
            destructive=True,
            open_world=True,
        )

    if ctx.should_register("read_process_output"):

        async def read_process_output(session_id: str, offset: int = 0, limit: int = 4000) -> str:
            started_at = ctx.now_ms()
            result = await read_process_output_impl(
                session_id=session_id, offset=offset, limit=limit
            )
            return audit_tool_call(
                "read_process_output",
                {"session_id": session_id, "offset": offset, "limit": limit},
                result,
                started_at=started_at,
            )

        ctx.register(
            "read_process_output",
            "Read paginated output from a previously started process session.",
            read_process_output,
            read_only=True,
        )

    if ctx.should_register("list_process_sessions"):

        async def list_process_sessions() -> str:
            started_at = ctx.now_ms()
            result = await list_process_sessions_impl()
            return audit_tool_call("list_process_sessions", {}, result, started_at=started_at)

        ctx.register(
            "list_process_sessions",
            "List active and recent process sessions.",
            list_process_sessions,
            read_only=True,
        )

    if ctx.should_register("kill_process"):

        async def kill_process(session_id: str, force: bool = False) -> str:
            started_at = ctx.now_ms()
            result = await kill_process_impl(
                session_id=session_id, force=force, request_approval=request_approval
            )
            return audit_tool_call(
                "kill_process",
                {"session_id": session_id, "force": force},
                result,
                started_at=started_at,
            )

        ctx.register(
            "kill_process",
            "Terminate a process session by id; use force for immediate SIGKILL-style termination.",
            kill_process,
            destructive=True,
        )

    if ctx.should_register("interact_with_process"):

        async def interact_with_process(
            session_id: str, input: str = "", close_stdin: bool = False
        ) -> str:
            started_at = ctx.now_ms()
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

        ctx.register(
            "interact_with_process",
            "Send input to a running process session.",
            interact_with_process,
            destructive=True,
            open_world=True,
        )

    return ctx.results
