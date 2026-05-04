"""Registration helpers for meta/configuration MCP tools and prompt catalogue."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp.prompts.base import Message, Prompt, PromptArgument

from claude_bridge.anomaly import build_anomaly_summary
from claude_bridge.audit import process_appeal
from claude_bridge.git_ops import generate_pr_description
from claude_bridge.guard_policy import default_allow_decision, load_guard_policy

_COMMON_SHELL_COMMANDS = sorted(
    {
        "git", "pytest", "ruff", "black", "mypy", "pip", "pip3", "npm", "pnpm", "yarn",
        "python", "python3", "node", "cargo", "go", "make", "cmake", "docker",
        "ls", "cat", "echo", "mkdir", "cp", "mv", "rm", "find", "grep", "sed",
        "awk", "sort", "uniq", "wc", "head", "tail", "diff", "ssh", "scp", "rsync",
        "curl", "wget",
    }
)


def _autocomplete_suggestions(
    partial_input: str,
    *,
    project_dir: Callable[[], Path],
    context: str = "",
) -> dict[str, Any]:
    """Return file/tool/command suggestions for a partial input string.

    Detects intent (file path, tool name, shell command) and returns up to
    10 ranked suggestions.
    """
    stripped = partial_input.strip()
    intent = "unknown"
    if stripped.startswith("/") or stripped.startswith("./") or stripped.startswith("~"):
        intent = "file"
    elif " " in stripped:
        intent = "command"
    elif "." in stripped:
        intent = "file"
    else:
        # Could be a single-word tool name, command, or file prefix
        intent = "any"

    suggestions: list[dict[str, Any]] = []
    seen: set[str] = set()

    # ── file path suggestions ──
    if intent in {"file", "any"}:
        base_dir = project_dir()
        if stripped:
            parent = os.path.dirname(stripped) or "."
            prefix = os.path.basename(stripped)
        else:
            parent = "."
            prefix = ""
        search_root = (base_dir / parent).resolve()
        if search_root.exists() and search_root.is_dir():
            try:
                entries = sorted(search_root.iterdir(), key=lambda e: (not e.is_dir(), e.name))
            except OSError:
                entries = []
            for entry in entries:
                try:
                    rel = str(entry.relative_to(base_dir))
                except ValueError:
                    continue
                if prefix and not entry.name.startswith(prefix):
                    continue
                if rel in seen:
                    continue
                entry_type = "directory" if entry.is_dir() else "file"
                if entry.is_dir():
                    display = rel + os.sep
                else:
                    display = rel
                seen.add(rel)
                suggestions.append(
                    {
                        "text": display,
                        "type": entry_type,
                        "intent": "file",
                    }
                )
        # Also add from context if provided
        if context and not stripped:
            ctx_path = (base_dir / context).resolve()
            if ctx_path.exists() and ctx_path.is_dir():
                try:
                    ctx_entries = sorted(ctx_path.iterdir(), key=lambda e: (not e.is_dir(), e.name))
                except OSError:
                    ctx_entries = []
                for entry in ctx_entries:
                    try:
                        rel = str(entry.relative_to(base_dir))
                    except ValueError:
                        continue
                    if rel in seen:
                        continue
                    entry_type = "directory" if entry.is_dir() else "file"
                    if entry.is_dir():
                        display = rel + os.sep
                    else:
                        display = rel
                    seen.add(rel)
                    suggestions.append(
                        {
                            "text": display,
                            "type": entry_type,
                            "intent": "file",
                        }
                    )

    # ── tool name suggestions ──
    if intent in {"any", "command"} and not stripped.startswith("/"):
        _known_tools = sorted(
            [
                "read_file", "write_file", "patch_file", "preview_patch",
                "undo_last_patch", "list_directory", "search_in_files",
                "read_multiple_files", "move_file", "copy_path",
                "read_image", "read_pdf", "read_url",
                "run_shell", "start_process", "read_process_output",
                "list_process_sessions", "kill_process", "interact_with_process",
                "analyze_shell_command",
                "index_codebase", "find_relevant_files",
                "run_workflow", "run_agent_loop_step", "run_agent_loop_session",
                "build_context_pack", "narrow_context",
                "suggest_validation_commands",
                "get_config", "set_config_value", "bridge_status",
                "workspace_status", "switch_project_root",
                "compact_user_intent", "tools_overview", "prompt_shortcuts",
                "get_recent_tool_calls", "session_insights",
                "activity_summary", "usage_insights",
                "appeal_decision", "send_feedback", "anomaly_summary",
                "generate_pr_description", "get_trust_score",
                "commit_changes",
                "count_file_tokens", "context_fit", "smart_status",
                "project_insights", "todo_scan", "recent_files",
                "language_distribution", "git_insights", "git_diff_insights",
                "duplicate_code_scan", "dependency_insights",
                "bridge_save_note", "bridge_read_notes", "bridge_doodle",
                "create_plan", "execute_step", "get_plan_status",
                "explore_approaches", "execute_approach", "compare_approaches",
                "self_critique",
                "create_checkpoint", "restore_checkpoint", "list_checkpoints",
            ]
        )
        lookup = stripped.lower()
        for tool in _known_tools:
            if lookup and lookup not in tool.lower():
                continue
            if tool in seen:
                continue
            seen.add(tool)
            suggestions.append(
                {
                    "text": tool,
                    "type": "tool",
                    "intent": "tool",
                }
            )

    # ── shell command suggestions ──
    if intent in {"any", "command"}:
        lookup = stripped.lower()
        for cmd in _COMMON_SHELL_COMMANDS:
            if lookup and lookup not in cmd.lower():
                continue
            if cmd in seen:
                continue
            seen.add(cmd)
            suggestions.append(
                {
                    "text": cmd,
                    "type": "command",
                    "intent": "command",
                }
            )

    # Deduplicate by text, prioritize by intent match
    deduped: dict[str, dict[str, Any]] = {}
    for s in suggestions:
        key = s["text"]
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = s
        elif _intent_score(s["intent"]) > _intent_score(existing["intent"]):
            deduped[key] = s

    ranked = sorted(
        deduped.values(),
        key=lambda s: (-_intent_score(s["intent"]), s["type"] != "directory", s["text"]),
    )[:10]

    return {
        "partial_input": partial_input,
        "detected_intent": intent,
        "suggestions": ranked,
    }


def _intent_score(intent_name: str) -> int:
    order = {"file": 3, "tool": 2, "command": 2, "unknown": 0, "any": 1}
    return order.get(intent_name, 0)


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
    # Feedback
    send_feedback_impl: Callable[..., dict[str, Any]],
    get_trust_score_impl: Callable[..., dict[str, Any]],
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
        limit: int = 20,
        tool_name: str | None = None,
        ok: bool | None = None,
        decision_action: str | None = None,
        decision_source: str | None = None,
        decision_risk_level: str | None = None,
        since: str | None = None,
    ) -> str:
        started_at = time.perf_counter()
        safe_limit = max(1, min(limit, 100))
        audit_params: dict[str, Any] = {"limit": safe_limit}
        if tool_name is not None:
            audit_params["tool_name"] = tool_name
        if ok is not None:
            audit_params["ok"] = ok
        if decision_action is not None:
            audit_params["decision_action"] = decision_action
        if decision_source is not None:
            audit_params["decision_source"] = decision_source
        if decision_risk_level is not None:
            audit_params["decision_risk_level"] = decision_risk_level
        if since is not None:
            audit_params["since"] = since
        result = json_response(
            True,
            "Recent tool calls loaded",
            details=get_recent_tool_calls_impl(
                limit=safe_limit,
                tool_name=tool_name,
                ok=ok,
                decision_action=decision_action,
                decision_source=decision_source,
                decision_risk_level=decision_risk_level,
                since=since,
            ),
        )
        return audit_tool_call(
            "get_recent_tool_calls",
            audit_params,
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
            "Show a user-facing activity summary for the current or latest audit "
            "session: touched paths, shell commands, writes, patches, approval "
            "rejections, risky actions, and a compact timeline. Use this when the "
            "user asks what Claude Bridge did recently.",
            read_only=True,
        )
    )
    async def activity_summary(limit: int = 50) -> str:
        started_at = time.perf_counter()
        safe_limit = max(1, min(limit, 200))
        summary = summarize_session_impl(limit=safe_limit)
        activity = summary.get("activity", {})
        result = json_response(
            True,
            "Activity summary loaded",
            details={
                "session_id": summary["session_id"],
                "total_records": summary["total_records"],
                "returned_records": summary["returned_records"],
                "failure_count": summary["failure_count"],
                "activity": activity,
                "suggested_response_topics": [
                    "Summarize touched files or directories.",
                    "Call out shell commands and whether they succeeded.",
                    "Mention writes, patches, approval rejections, or risky actions.",
                    "Offer validation if files were changed but no validation ran.",
                ],
            },
        )
        return audit_tool_call(
            "activity_summary",
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
            tool_estimated_tokens = telemetry.get("tool_estimated_tokens", {})
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
        profile_name = str(config_snapshot.get("context_budget_profile", "balanced"))
        profile = budget_profiles.get(profile_name, {})
        result = json_response(
            True,
            "Bridge status loaded",
            details={
                "active_project_dir": str(config_snapshot["project_dir"]),
                "allowed_roots": [str(root) for root in config_snapshot["allowed_roots"]],
                "approval_preset": config_snapshot["approval_preset"],
                "auto_approve": config_snapshot["auto_approve"],
                "client_managed_approval": config_snapshot["client_managed_approval"],
                "context_budget_profile": profile_name,
                "context_budget_tokens": profile.get("context_budget_tokens"),
                "budget_profile_description": profile.get("description"),
                "intent_compaction_enabled": config_snapshot["intent_compaction_enabled"],
                "smart_features": smart_avail,
                "session_telemetry": session_summary.get("telemetry", {}),
            },
        )
        return audit_tool_call("bridge_status", {}, result, started_at=started_at)

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
        return audit_tool_call("tools_overview", {}, result, started_at=started_at)

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
                "allowed_roots": [str(root) for root in snapshot["allowed_roots"]],
                "approval_presets": approval_presets,
                "budget_profiles": budget_profiles,
                "guard_policy": load_guard_policy(),
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
        return audit_tool_call("get_config", {}, result, started_at=started_at)

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
                "allowed_roots": [str(root) for root in updated["allowed_roots"]],
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
        enabled = bool(current_config().get("intent_compaction_enabled", False))
        details = smart_compact_intent(text, preserve_language=preserve_language)
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
                "allowed_roots": [str(root) for root in allowed_roots()],
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
            decision=default_allow_decision("Workspace status is read-only metadata"),
            decision_in_details=True,
        )
        return audit_tool_call("workspace_status", {}, result, started_at=started_at)

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
        return audit_tool_call("prompt_shortcuts", {}, result, started_at=started_at)

    @mcp.tool(
        **tool_options(
            "Appeal a policy decision by record id with a justification. "
            "Returns allow, deny, or ask and chains the result to the audit log.",
            destructive=True,
        )
    )
    async def appeal_decision(record_id: str, justification: str) -> str:
        started_at = time.perf_counter()
        try:
            result = process_appeal(record_id, justification)
        except ValueError as exc:
            result_obj = json_response(
                False,
                str(exc),
                code="appeal_failed",
                details={"record_id": record_id},
            )
            return audit_tool_call(
                "appeal_decision",
                {"record_id": record_id, "justification": justification},
                result_obj,
                started_at=started_at,
            )
        result_obj = json_response(
            True,
            "Appeal processed",
            details=result,
        )
        return audit_tool_call(
            "appeal_decision",
            {"record_id": record_id, "justification": justification},
            result_obj,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Send user feedback with a rating (1-5) and optional comment. "
            "Saves to .claude-bridge/feedback/ and optionally links "
            "to the current audit session.",
            destructive=True,
        )
    )
    async def send_feedback(
        rating: int,
        comment: str,
        include_session: bool = True,
    ) -> str:
        started_at = time.perf_counter()
        impl_result = send_feedback_impl(
            rating=rating,
            comment=comment,
            include_session=include_session,
        )
        if not impl_result["ok"]:
            result = json_response(
                False,
                impl_result["message"],
                details=impl_result.get("details", {}),
            )
            return audit_tool_call(
                "send_feedback",
                {
                    "rating": rating,
                    "comment_length": len(comment),
                    "include_session": include_session,
                },
                result,
                started_at=started_at,
            )
        result = json_response(
            True,
            impl_result["message"],
            details=impl_result["details"],
        )
        return audit_tool_call(
            "send_feedback",
            {
                "rating": rating,
                "comment_length": len(comment),
                "include_session": include_session,
            },
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Run anomaly detection on recent audit records. Returns per-record "
            "anomaly scores, overall severity level, and policy decision metadata "
            "for critical anomalies. Use this to identify suspicious sessions.",
            read_only=True,
        )
    )
    async def anomaly_summary(limit: int = 50) -> str:
        started_at = time.perf_counter()
        safe_limit = max(1, min(limit, 500))
        recent = get_recent_tool_calls_impl(limit=safe_limit)
        records = recent.get("records", [])
        session_id = recent.get("session_id", "")
        summary = build_anomaly_summary(
            records=records,
            session_id=session_id,
            limit=safe_limit,
        )
        result = json_response(
            True,
            "Anomaly scan complete",
            details=summary,
        )
        return audit_tool_call(
            "anomaly_summary",
            {"limit": safe_limit},
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Generate a structural PR description from a raw git diff. "
            "Parses changed files, additions, deletions, affected file "
            "extensions, and a short diff summary. Returns structured JSON.",
            read_only=True,
        )
    )
    async def generate_pr_description_tool(diff_text: str) -> str:
        started_at = time.perf_counter()
        parsed = generate_pr_description(diff_text)
        result = json_response(
            True,
            "PR description generated",
            details=parsed,
        )
        return audit_tool_call(
            "generate_pr_description",
            {"diff_text_length": len(diff_text)},
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Calculate a trust score based on recent audit records. "
            "Returns deny rate, anomaly frequency, approval rejection trend, "
            "and overall score (0-100). Higher is better.",
            read_only=True,
        )
    )
    async def get_trust_score(days: int = 7) -> str:
        started_at = time.perf_counter()
        score_result = get_trust_score_impl(days=days)
        result = json_response(
            score_result.get("ok", True),
            score_result.get("message", "Trust score calculated"),
            details=score_result.get("details", score_result),
        )
        return audit_tool_call(
            "get_trust_score",
            {"days": days},
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Autocomplete partial input with file, tool, and shell command "
            "suggestions. Use this to help users complete paths, tool names, "
            "or commands while typing.",
            read_only=True,
        )
    )
    async def autocomplete(partial_input: str, context: str = "") -> str:
        started_at = time.perf_counter()
        suggestions = _autocomplete_suggestions(
            partial_input,
            project_dir=project_dir,
            context=context,
        )
        result = json_response(
            True,
            f"Autocomplete suggestions for: {partial_input}",
            details=suggestions,
        )
        return audit_tool_call(
            "autocomplete",
            {"partial_input": partial_input, "context": context},
            result,
            started_at=started_at,
        )

    return {
        "get_recent_tool_calls": get_recent_tool_calls,
        "session_insights": session_insights,
        "activity_summary": activity_summary,
        "usage_insights": usage_insights,
        "bridge_status": bridge_status,
        "tools_overview": tools_overview,
        "get_config": get_config,
        "set_config_value": set_config_value,
        "compact_user_intent": compact_user_intent,
        "workspace_status": workspace_status,
        "switch_project_root": switch_project_root,
        "prompt_shortcuts": prompt_shortcuts,
        "appeal_decision": appeal_decision,
        "send_feedback": send_feedback,
        "anomaly_summary": anomaly_summary,
        "generate_pr_description": generate_pr_description_tool,
        "get_trust_score": get_trust_score,
        "autocomplete": autocomplete,
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

            def _make_custom_fn(_name: str, _builder: Any, _second_default: str) -> Any:
                def _fn(target: str = ".", **kwargs: Any) -> Message:
                    second_arg_name: str = prompt_arguments[_name][1]["name"]
                    second_value = kwargs.get(second_arg_name, _second_default)
                    return Message(
                        _builder(target, second_value, language=kwargs.get("language", "Turkish")),
                        role="user",
                    )

                return _fn

            fn = _make_custom_fn(name, builder, second_default)

        # ── standard workflow-template prompts ──
        else:
            focus_arg_name: str = prompt_focus_arg[name]
            focus_default: str = workflow_default_focus[name]

            def _make_workflow_fn(_name: str, _focus_arg_name: str, _focus_default: str) -> Any:
                def _fn(target: str = ".", **kwargs: Any) -> Message:
                    focus_value = kwargs.get(_focus_arg_name, _focus_default)
                    language = kwargs.get("language", "Turkish")
                    return Message(
                        workflow_prompt(_name, target, focus_value, language),
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
