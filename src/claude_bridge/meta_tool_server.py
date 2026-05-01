"""Registration helpers for meta/configuration MCP tools and prompt catalogue."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp.prompts.base import Message, Prompt, PromptArgument


def register_meta_tools(
    *,
    mcp: Any,
    tool_options: Callable[..., dict[str, Any]],
    audit_tool_call: Callable[..., str],
    json_response: Callable[..., str],
    # Audit implementations
    get_recent_tool_calls_impl: Any,
    summarize_session_impl: Any,
    # Config
    current_config: Callable[[], dict[str, Any]],
    update_runtime_config: Callable[..., dict[str, Any]],
    approval_presets: dict[str, Any],
    budget_profiles: dict[str, Any],
    # Smart
    smart_compact_intent: Any,
    smart_available: Any,
    # Tool utils
    project_dir: Callable[[], Path],
    allowed_roots: Callable[[], list[Path]],
    infer_project_root: Callable[..., Any],
    set_active_project_dir: Callable[..., Any],
    path_outside_project_details: Callable[..., dict[str, Any]],
    # Onboarding
    reset_onboarding_state: Callable[[], None],
    # Workflow presets
    prompt_shortcut_catalog: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Register all meta/configuration MCP tools and return a dict of callables."""

    @mcp.tool(
        **tool_options(
            "Show recent Claude Bridge tool calls from the current or latest audit session. "
            "Use this to explain what the bridge did recently.",
            read_only=True,
        )
    )
    async def get_recent_tool_calls(
        limit: int = 20, tool_name: str | None = None
    ) -> str:
        started_at = time.perf_counter()
        safe_limit = max(1, min(limit, 100))
        result = json_response(
            True,
            "Recent tool calls loaded",
            details=get_recent_tool_calls_impl(
                limit=safe_limit, tool_name=tool_name
            ),
        )
        return audit_tool_call(
            "get_recent_tool_calls",
            {"limit": safe_limit, "tool_name": tool_name},
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Show session-level telemetry such as approximate token usage, "
            "input/output sizes, truncation count, and tool-level cost hotspots.",
            read_only=True,
        )
    )
    async def session_insights(limit: int = 50) -> str:
        started_at = time.perf_counter()
        safe_limit = max(1, min(limit, 200))
        summary = summarize_session_impl(limit=safe_limit)
        result = json_response(
            True,
            "Session insights loaded",
            details=summary,
        )
        return audit_tool_call(
            "session_insights",
            {"limit": safe_limit},
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Show usage-focused telemetry with token hotspots and truncation signals. "
            "Use this when you want to reduce cost or identify noisy tools.",
            read_only=True,
        )
    )
    async def usage_insights(limit: int = 50) -> str:
        started_at = time.perf_counter()
        safe_limit = max(1, min(limit, 200))
        summary = summarize_session_impl(limit=safe_limit)
        telemetry = summary.get("telemetry", {})
        top_tools: list[dict[str, Any]] = []
        if isinstance(telemetry, dict):
            tool_estimated_tokens = telemetry.get(
                "tool_estimated_tokens", {}
            )
            if isinstance(tool_estimated_tokens, dict):
                top_tools = [
                    {
                        "tool_name": str(tool_name),
                        "estimated_tokens": int(tokens),
                    }
                    for tool_name, tokens in sorted(
                        tool_estimated_tokens.items(),
                        key=lambda item: int(item[1]),
                        reverse=True,
                    )
                ]
        result = json_response(
            True,
            "Usage insights loaded",
            details={
                "session_id": summary["session_id"],
                "telemetry": telemetry,
                "top_cost_tools": top_tools,
                "recommended_next_step": (
                    "Use narrow_context, compact, or a lower context budget "
                    "profile if one tool is dominating token usage."
                ),
            },
        )
        return audit_tool_call(
            "usage_insights",
            {"limit": safe_limit},
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Show the most useful current runtime status in one place: workspace, "
            "budget profile, approvals, smart features, and recent telemetry.",
            read_only=True,
        )
    )
    async def bridge_status() -> str:
        started_at = time.perf_counter()
        config_snapshot = current_config()
        session_summary = summarize_session_impl(limit=20)
        smart_avail = smart_available()
        profile_name = str(
            config_snapshot.get("context_budget_profile", "balanced")
        )
        profile = budget_profiles.get(profile_name, {})
        result = json_response(
            True,
            "Bridge status loaded",
            details={
                "active_project_dir": str(config_snapshot["project_dir"]),
                "allowed_roots": [
                    str(root) for root in config_snapshot["allowed_roots"]
                ],
                "approval_preset": config_snapshot["approval_preset"],
                "auto_approve": config_snapshot["auto_approve"],
                "client_managed_approval": config_snapshot[
                    "client_managed_approval"
                ],
                "context_budget_profile": profile_name,
                "context_budget_tokens": profile.get(
                    "context_budget_tokens"
                ),
                "budget_profile_description": profile.get("description"),
                "intent_compaction_enabled": config_snapshot[
                    "intent_compaction_enabled"
                ],
                "smart_features": smart_avail,
                "session_telemetry": session_summary.get("telemetry", {}),
            },
        )
        return audit_tool_call(
            "bridge_status", {}, result, started_at=started_at
        )

    @mcp.tool(
        **tool_options(
            "List the most useful Claude Bridge tools, grouped by purpose, "
            "with a note about lower-token entrypoints.",
            read_only=True,
        )
    )
    async def tools_overview() -> str:
        started_at = time.perf_counter()
        result = json_response(
            True,
            "Tools overview loaded",
            details={
                "groups": {
                    "orientation": [
                        "workspace_status",
                        "list_directory",
                        "tools_overview",
                        "bridge_status",
                    ],
                    "low_cost_context": [
                        "compact_user_intent",
                        "find_relevant_files",
                        "narrow_context",
                        "build_context_pack",
                        "read_file",
                        "read_multiple_files",
                        "read_image",
                        "read_pdf",
                    ],
                    "analysis": [
                        "run_workflow",
                        "prompt_shortcuts",
                        "project_insights",
                        "todo_scan",
                    ],
                    "execution": [
                        "run_shell",
                        "start_process",
                        "interact_with_process",
                        "run_agent_loop_step",
                    ],
                    "telemetry": [
                        "session_insights",
                        "usage_insights",
                        "get_recent_tool_calls",
                        "smart_status",
                    ],
                },
                "notes": [
                    "Prefer prompt_shortcuts or MCP prompt UI for lower-token entrypoints.",
                    "Use compact_user_intent when you want to normalize a long request into a smaller internal task object.",
                    "Prefer narrow_context before broad read_file usage when cost matters.",
                    "Use usage_insights to see which tools are driving token-like cost the most.",
                ],
            },
        )
        return audit_tool_call(
            "tools_overview", {}, result, started_at=started_at
        )

    @mcp.tool(
        **tool_options(
            "Show the current Claude Bridge runtime configuration, including "
            "approval mode and active preset. Use this before changing config values.",
            read_only=True,
        )
    )
    async def get_config() -> str:
        started_at = time.perf_counter()
        snapshot = current_config()
        result = json_response(
            True,
            "Runtime configuration loaded",
            details={
                **snapshot,
                "project_dir": str(snapshot["project_dir"]),
                "allowed_roots": [
                    str(root) for root in snapshot["allowed_roots"]
                ],
                "approval_presets": approval_presets,
                "budget_profiles": budget_profiles,
                "editable_keys": [
                    "approval_preset",
                    "auto_approve",
                    "client_managed_approval",
                    "shell_timeout",
                    "onboarding_enabled",
                    "context_budget_profile",
                    "intent_compaction_enabled",
                ],
            },
        )
        return audit_tool_call(
            "get_config", {}, result, started_at=started_at
        )

    @mcp.tool(
        **tool_options(
            "Update a single Claude Bridge runtime configuration value. "
            "Supported keys: approval_preset, auto_approve, "
            "client_managed_approval, shell_timeout, onboarding_enabled, "
            "context_budget_profile, intent_compaction_enabled.",
            destructive=True,
        )
    )
    async def set_config_value(key: str, value: Any) -> str:
        started_at = time.perf_counter()
        try:
            updated = update_runtime_config(key, value)
        except ValueError as exc:
            result = json_response(
                False,
                str(exc),
                code="invalid_config_value",
                details={"key": key, "value": value},
            )
            return audit_tool_call(
                "set_config_value",
                {"key": key, "value": value},
                result,
                started_at=started_at,
            )

        result = json_response(
            True,
            f"Updated runtime config: {key}",
            details={
                **updated,
                "project_dir": str(updated["project_dir"]),
                "allowed_roots": [
                    str(root) for root in updated["allowed_roots"]
                ],
            },
        )
        return audit_tool_call(
            "set_config_value",
            {"key": key, "value": value},
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Compact a natural-language request into a smaller canonical intent "
            "object. Enable this mode when you want cheaper internal routing "
            "without automatic translation.",
            read_only=True,
        )
    )
    async def compact_user_intent(
        text: str,
        preserve_language: bool = True,
    ) -> str:
        started_at = time.perf_counter()
        enabled = bool(
            current_config().get("intent_compaction_enabled", False)
        )
        details = smart_compact_intent(
            text, preserve_language=preserve_language
        )
        details["intent_compaction_enabled"] = enabled
        details["mode_behavior"] = (
            "active"
            if enabled
            else "available but inactive until intent_compaction_enabled is turned on"
        )
        details["recommended_next_step"] = (
            "Turn on intent_compaction_enabled if you want clients or future "
            "workflows to prefer this compact form by default."
        )
        result = json_response(
            True,
            "User intent compacted",
            details=details,
        )
        return audit_tool_call(
            "compact_user_intent",
            {
                "text_length": len(text),
                "preserve_language": preserve_language,
            },
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Show the active project root and the full list of allowed roots. "
            "Use this when a path fails or before switching workspaces.",
            read_only=True,
        )
    )
    async def workspace_status() -> str:
        started_at = time.perf_counter()
        result = json_response(
            True,
            "Workspace status",
            details={
                "active_project_dir": str(project_dir()),
                "allowed_roots": [
                    str(root) for root in allowed_roots()
                ],
                "root_rules": {
                    "can_switch_to_subdirectories": True,
                    "explanation": (
                        "Any existing subdirectory inside an allowed root "
                        "can be selected as the active project root."
                    ),
                    "example": (
                        "If '/Users/me/Desktop' is allowed, you can switch "
                        "to '/Users/me/Desktop/tertis'."
                    ),
                },
            },
        )
        return audit_tool_call(
            "workspace_status", {}, result, started_at=started_at
        )

    @mcp.tool(
        **tool_options(
            "Switch the active project root to another allowed directory. "
            "Use this only when the current task clearly belongs in a "
            "different allowed workspace.",
            destructive=True,
        )
    )
    async def switch_project_root(path: str) -> str:
        started_at = time.perf_counter()
        reset_onboarding_state()
        candidate = Path(path)
        target = (
            candidate.resolve()
            if candidate.is_absolute()
            else (project_dir() / candidate).resolve()
        )
        if not target.exists():
            result = json_response(
                False,
                f"Directory not found: {path}",
                code="directory_not_found",
                details={"path": path},
            )
            return audit_tool_call(
                "switch_project_root",
                {"path": path},
                result,
                started_at=started_at,
            )
        if not target.is_dir():
            result = json_response(
                False,
                f"Not a directory: {path}",
                code="not_a_directory",
                details={"path": path},
            )
            return audit_tool_call(
                "switch_project_root",
                {"path": path},
                result,
                started_at=started_at,
            )
        try:
            infer_project_root(target)
            set_active_project_dir(target)
        except PermissionError as exc:
            result = json_response(
                False,
                str(exc),
                code="path_outside_project",
                details=path_outside_project_details(path),
            )
            return audit_tool_call(
                "switch_project_root",
                {"path": path},
                result,
                started_at=started_at,
            )

        result = json_response(
            True,
            f"Active project root switched to: {target}",
            details={
                "active_project_dir": str(project_dir()),
                "allowed_roots": [str(root) for root in allowed_roots()],
                "switched_from_subdirectory_rule": True,
            },
        )
        return audit_tool_call(
            "switch_project_root",
            {"path": path},
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "List Claude Bridge prompt shortcuts and explain which ones can "
            "truly avoid a full chat planning turn. Use this when you want "
            "lower-token entrypoints such as MCP prompts or slash-style shortcuts.",
            read_only=True,
        )
    )
    async def prompt_shortcuts() -> str:
        started_at = time.perf_counter()
        catalog = prompt_shortcut_catalog()
        details = {
            "shortcuts": catalog["shortcuts"],
            "client_side_only": catalog["client_side_only"],
            "notes": catalog["notes"],
            "recommended_path": (
                "Use an MCP prompt or slash UI when the client exposes it; "
                "fall back to run_workflow or a natural-language request "
                "only when necessary."
            ),
        }
        result = json_response(
            True,
            "Prompt shortcuts loaded",
            details=details,
        )
        return audit_tool_call(
            "prompt_shortcuts", {}, result, started_at=started_at
        )

    return {
        "get_recent_tool_calls": get_recent_tool_calls,
        "session_insights": session_insights,
        "usage_insights": usage_insights,
        "bridge_status": bridge_status,
        "tools_overview": tools_overview,
        "get_config": get_config,
        "set_config_value": set_config_value,
        "compact_user_intent": compact_user_intent,
        "workspace_status": workspace_status,
        "switch_project_root": switch_project_root,
        "prompt_shortcuts": prompt_shortcuts,
    }


def register_prompts(
    *,
    mcp: Any,
    prompt_shortcuts: list[dict[str, Any]],
    prompt_arguments: dict[str, list[dict[str, Any]]],
    prompt_focus_arg: dict[str, str],
    workflow_default_focus: dict[str, str],
    prompt_custom_builders: dict[str, Any],
    custom_prompt_defaults: dict[str, str],
    workflow_prompt: Callable[..., str],
) -> None:
    """Register every prompt from the shared shortcut catalogue."""

    for shortcut in prompt_shortcuts:
        name: str = shortcut["name"]
        description: str = shortcut["description"]

        arg_defs = prompt_arguments[name]
        arguments = [
            PromptArgument(
                name=ad["name"],
                description=ad["description"],
                required=ad.get("required", False),
            )
            for ad in arg_defs
        ]

        # ── custom message builders (compact / shadow / benchmark / platform) ──
        if name in prompt_custom_builders:
            builder = prompt_custom_builders[name]
            second_default = custom_prompt_defaults[name]

            def _make_custom_fn(
                _name: str, _builder: Any, _second_default: str
            ) -> Any:
                def _fn(target: str = ".", **kwargs: Any) -> Message:
                    second_arg_name: str = prompt_arguments[_name][1]["name"]
                    second_value = kwargs.get(
                        second_arg_name, _second_default
                    )
                    return Message(
                        _builder(
                            target, second_value, language="Turkish"
                        ),
                        role="user",
                    )

                return _fn

            fn = _make_custom_fn(name, builder, second_default)

        # ── standard workflow-template prompts ──
        else:
            focus_arg_name: str = prompt_focus_arg[name]
            focus_default: str = workflow_default_focus[name]

            def _make_workflow_fn(
                _name: str, _focus_arg_name: str, _focus_default: str
            ) -> Any:
                def _fn(target: str = ".", **kwargs: Any) -> Message:
                    focus_value = kwargs.get(
                        _focus_arg_name, _focus_default
                    )
                    language = kwargs.get("language", "Turkish")
                    return Message(
                        workflow_prompt(
                            _name, target, focus_value, language
                        ),
                        role="user",
                    )

                return _fn

            fn = _make_workflow_fn(name, focus_arg_name, focus_default)

        mcp.add_prompt(
            Prompt(
                name=name,
                title=description,
                description=description,
                arguments=arguments,
                fn=fn,
                context_kwarg=None,
            )
        )
