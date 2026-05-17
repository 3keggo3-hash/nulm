"""MCP registration for AI council tools."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Any, Callable

from claude_bridge.tool_registration import ToolRegistrationContext


def register_council_tools(
    *,
    mcp: Any,
    tool_options: Callable[..., dict[str, Any]],
    audit_tool_call: Callable[..., str],
    json_response: Callable[..., str],
    run_council_session_impl: Any,
    router_getter: Callable[[], Any],
    enabled_names: set[str] | None = None,
) -> dict[str, Any]:
    ctx = ToolRegistrationContext(
        mcp=mcp,
        tool_options=tool_options,
        audit_tool_call=audit_tool_call,
        enabled_names=enabled_names,
    )

    if ctx.should_register("run_council_session"):

        async def run_council_session(
            task: str,
            target: str = ".",
            agent_count: int = 5,
            rounds: int = 2,
            model_profile: str = "auto",
            language: str = "Turkish",
        ) -> str:
            started_at = ctx.now_ms()
            result = run_council_session_impl(
                task=task,
                target=target,
                agent_count=agent_count,
                rounds=rounds,
                model_profile=model_profile,
                language=language,
                router=router_getter(),
            )
            if not isinstance(result, dict):
                result = {"ok": False, "message": "Council returned invalid result"}
            payload = json_response(
                bool(result.get("ok", False)),
                str(result.get("message", "Council session completed")),
                code=result.get("code"),
                details=result.get("details", {}),
            )
            return audit_tool_call(
                "run_council_session",
                {
                    "task": task,
                    "target": target,
                    "agent_count": agent_count,
                    "rounds": rounds,
                    "model_profile": model_profile,
                    "language": language,
                },
                payload,
                started_at=started_at,
            )

        ctx.register(
            "run_council_session",
            "Run a read-only AI council debate and synthesize an approval-gated plan.",
            run_council_session,
            read_only=True,
            open_world=True,
        )

    return ctx.results
