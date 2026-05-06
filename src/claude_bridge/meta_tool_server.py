"""Registration helpers for meta/configuration MCP tools and prompt catalogue."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable, Sequence

from mcp.server.fastmcp.prompts.base import Message, Prompt, PromptArgument

from claude_bridge.anomaly import build_anomaly_summary
from claude_bridge.audit import get_pending_escalations, process_appeal
from claude_bridge.git_ops import generate_pr_description
from claude_bridge.guard_policy import default_allow_decision, load_guard_policy

_COMMON_SHELL_COMMANDS = sorted(
    {
        "git",
        "pytest",
        "ruff",
        "black",
        "mypy",
        "pip",
        "pip3",
        "npm",
        "pnpm",
        "yarn",
        "python",
        "python3",
        "node",
        "cargo",
        "go",
        "make",
        "cmake",
        "docker",
        "ls",
        "cat",
        "echo",
        "mkdir",
        "cp",
        "mv",
        "rm",
        "find",
        "grep",
        "sed",
        "awk",
        "sort",
        "uniq",
        "wc",
        "head",
        "tail",
        "diff",
        "ssh",
        "scp",
        "rsync",
        "curl",
        "wget",
    }
)


def _autocomplete_suggestions(
    partial_input: str,
    *,
    project_dir: Callable[[], Path],
    context: str = "",
) -> dict[str, Any]:
    stripped = partial_input.strip()
    intent = "unknown"
    if stripped.startswith("/") or stripped.startswith("./") or stripped.startswith("~"):
        intent = "file"
    elif " " in stripped:
        intent = "command"
    elif "." in stripped:
        intent = "file"
    else:
        intent = "any"

    suggestions: list[dict[str, Any]] = []
    seen: set[str] = set()

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

    if intent in {"any", "command"} and not stripped.startswith("/"):
        _known_tools = sorted(
            [
                "read_file",
                "write_file",
                "patch_file",
                "preview_patch",
                "undo_last_patch",
                "list_directory",
                "search_in_files",
                "read_multiple_files",
                "move_file",
                "copy_path",
                "read_image",
                "read_pdf",
                "read_url",
                "run_shell",
                "start_process",
                "read_process_output",
                "list_process_sessions",
                "kill_process",
                "interact_with_process",
                "analyze_shell_command",
                "index_codebase",
                "find_relevant_files",
                "run_workflow",
                "run_agent_loop_step",
                "run_agent_loop_session",
                "build_context_pack",
                "narrow_context",
                "suggest_validation_commands",
                "get_config",
                "set_config_value",
                "bridge_status",
                "workspace_status",
                "switch_project_root",
                "compact_user_intent",
                "tools_overview",
                "prompt_shortcuts",
                "get_recent_tool_calls",
                "session_insights",
                "activity_summary",
                "usage_insights",
                "appeal_decision",
                "send_feedback",
                "anomaly_summary",
                "generate_pr_description",
                "get_trust_score",
                "commit_changes",
                "count_file_tokens",
                "context_fit",
                "smart_status",
                "project_insights",
                "todo_scan",
                "recent_files",
                "language_distribution",
                "git_insights",
                "git_diff_insights",
                "duplicate_code_scan",
                "dependency_insights",
                "bridge_save_note",
                "bridge_read_notes",
                "bridge_doodle",
                "create_plan",
                "execute_step",
                "get_plan_status",
                "explore_approaches",
                "execute_approach",
                "compare_approaches",
                "self_critique",
                "create_checkpoint",
                "restore_checkpoint",
                "list_checkpoints",
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
    get_recent_tool_calls_impl: Any,
    summarize_session_impl: Any,
    current_config: Callable[[], dict[str, Any]],
    update_runtime_config: Callable[..., dict[str, Any]],
    approval_presets: dict[str, Any],
    budget_profiles: dict[str, Any],
    send_feedback_impl: Callable[..., dict[str, Any]],
    get_trust_score_impl: Callable[..., dict[str, Any]],
    smart_compact_intent: Any,
    smart_available: Any,
    project_dir: Callable[[], Path],
    allowed_roots: Callable[[], Sequence[Path]],
    infer_project_root: Callable[..., Any],
    set_active_project_dir: Callable[..., Any],
    path_outside_project_details: Callable[..., dict[str, Any]],
    reset_onboarding_state: Callable[[], None],
    prompt_shortcut_catalog: Callable[[], dict[str, Any]],
    enabled_names: set[str] | None = None,
) -> dict[str, Any]:
    _enabled = enabled_names
    results: dict[str, Any] = {}

    if _enabled is None or "get_recent_tool_calls" in _enabled:

        @mcp.tool(
            **tool_options("Show recent tool calls from the current session.", read_only=True)
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
                "get_recent_tool_calls", audit_params, result, started_at=started_at
            )

        results["get_recent_tool_calls"] = get_recent_tool_calls

    if _enabled is None or "session_insights" in _enabled:

        @mcp.tool(**tool_options("Show session-level telemetry and token usage.", read_only=True))
        async def session_insights(limit: int = 50) -> str:
            started_at = time.perf_counter()
            safe_limit = max(1, min(limit, 200))
            summary = summarize_session_impl(limit=safe_limit)
            result = json_response(True, "Session insights loaded", details=summary)
            return audit_tool_call(
                "session_insights", {"limit": safe_limit}, result, started_at=started_at
            )

        results["session_insights"] = session_insights

    if _enabled is None or "activity_summary" in _enabled:

        @mcp.tool(
            **tool_options(
                "Show user-facing activity summary for the current session.", read_only=True
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
                    ],
                },
            )
            return audit_tool_call(
                "activity_summary", {"limit": safe_limit}, result, started_at=started_at
            )

        results["activity_summary"] = activity_summary

    if _enabled is None or "usage_insights" in _enabled:

        @mcp.tool(**tool_options("Show token hotspots and truncation signals.", read_only=True))
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
                        {"tool_name": str(tool_name), "estimated_tokens": int(tokens)}
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
                    "recommended_next_step": "Use narrow_context or a lower context budget profile if one tool dominates token usage.",
                },
            )
            return audit_tool_call(
                "usage_insights", {"limit": safe_limit}, result, started_at=started_at
            )

        results["usage_insights"] = usage_insights

    if _enabled is None or "bridge_status" in _enabled:

        @mcp.tool(**tool_options("Show current runtime status in one place.", read_only=True))
        async def bridge_status() -> str:
            started_at = time.perf_counter()
            config_snapshot = current_config()
            session_summary = summarize_session_impl(limit=20)
            pending_escalations = get_pending_escalations(limit=5)
            smart_avail = smart_available()
            from claude_bridge.ai_evaluator import ai_latency_summary

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
                    "tool_profile": config_snapshot.get("tool_profile", "standard"),
                    "intent_compaction_enabled": config_snapshot.get(
                        "intent_compaction_enabled", False
                    ),
                    "ai_evaluator": {
                        "enabled": config_snapshot.get("ai_evaluator_enabled", False),
                        "provider": config_snapshot.get("ai_evaluator_provider", "local"),
                        "timeout": config_snapshot.get("ai_evaluator_timeout", 5),
                        "latency": ai_latency_summary(),
                    },
                    "smart_features": smart_avail,
                    "session_telemetry": session_summary.get("telemetry", {}),
                    "escalations": {
                        "pending_count": pending_escalations["total_pending"],
                        "recent_pending": pending_escalations["records"],
                    },
                },
            )
            return audit_tool_call("bridge_status", {}, result, started_at=started_at)

        results["bridge_status"] = bridge_status

    if _enabled is None or "tools_overview" in _enabled:

        @mcp.tool(**tool_options("List Claude Bridge tools grouped by purpose.", read_only=True))
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
                        ],
                        "execution": [
                            "run_shell",
                            "start_process",
                            "patch_file",
                            "run_agent_loop_step",
                        ],
                        "telemetry": ["session_insights", "usage_insights", "smart_status"],
                    },
                    "notes": [
                        "Low-cost context tools (compact_user_intent, narrow_context) reduce token usage for routine queries.",
                        "Execution tools require approval unless auto_approve is set.",
                        "Telemetry tools are read-only and never modify your project.",
                    ],
                },
            )
            return audit_tool_call("tools_overview", {}, result, started_at=started_at)

        results["tools_overview"] = tools_overview

    if _enabled is None or "get_config" in _enabled:

        @mcp.tool(**tool_options("Show current runtime configuration.", read_only=True))
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
                        "tool_profile",
                        "intent_compaction_enabled",
                        "ai_evaluator_enabled",
                        "ai_evaluator_provider",
                        "ai_evaluator_api_key",
                        "ai_evaluator_model",
                        "ai_evaluator_timeout",
                        "ai_evaluator_fallback_action",
                        "role",
                        "user",
                    ],
                },
            )
            return audit_tool_call("get_config", {}, result, started_at=started_at)

        results["get_config"] = get_config

    if _enabled is None or "set_config_value" in _enabled:

        @mcp.tool(**tool_options("Update a single runtime configuration value.", destructive=True))
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
                    "set_config_value", {"key": key, "value": value}, result, started_at=started_at
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
                "set_config_value", {"key": key, "value": value}, result, started_at=started_at
            )

        results["set_config_value"] = set_config_value

    if _enabled is None or "compact_user_intent" in _enabled:

        @mcp.tool(
            **tool_options(
                "Compact a request into a smaller canonical intent object.", read_only=True
            )
        )
        async def compact_user_intent(text: str, preserve_language: bool = True) -> str:
            started_at = time.perf_counter()
            enabled = bool(current_config().get("intent_compaction_enabled", False))
            details = smart_compact_intent(text, preserve_language=preserve_language)
            details["intent_compaction_enabled"] = enabled
            details["mode_behavior"] = (
                "active"
                if enabled
                else "available but inactive until intent_compaction_enabled is turned on"
            )
            result = json_response(True, "User intent compacted", details=details)
            return audit_tool_call(
                "compact_user_intent",
                {"text_length": len(text), "preserve_language": preserve_language},
                result,
                started_at=started_at,
            )

        results["compact_user_intent"] = compact_user_intent

    if _enabled is None or "workspace_status" in _enabled:

        @mcp.tool(**tool_options("Show the active project root and allowed roots.", read_only=True))
        async def workspace_status() -> str:
            started_at = time.perf_counter()
            result = json_response(
                True,
                "Workspace status",
                details={
                    "active_project_dir": str(project_dir()),
                    "allowed_roots": [str(root) for root in allowed_roots()],
                    "root_rules": {"can_switch_to_subdirectories": True},
                },
                decision=default_allow_decision("Workspace status is read-only metadata"),
                decision_in_details=True,
            )
            return audit_tool_call("workspace_status", {}, result, started_at=started_at)

        results["workspace_status"] = workspace_status

    if _enabled is None or "switch_project_root" in _enabled:

        @mcp.tool(
            **tool_options(
                "Switch the active project root to another allowed directory.", destructive=True
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
                    "switch_project_root", {"path": path}, result, started_at=started_at
                )
            if not target.is_dir():
                result = json_response(
                    False,
                    f"Not a directory: {path}",
                    code="not_a_directory",
                    details={"path": path},
                )
                return audit_tool_call(
                    "switch_project_root", {"path": path}, result, started_at=started_at
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
                    "switch_project_root", {"path": path}, result, started_at=started_at
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
                "switch_project_root", {"path": path}, result, started_at=started_at
            )

        results["switch_project_root"] = switch_project_root

    if _enabled is None or "prompt_shortcuts" in _enabled:

        @mcp.tool(
            **tool_options("List prompt shortcuts and lower-token entrypoints.", read_only=True)
        )
        async def prompt_shortcuts() -> str:
            started_at = time.perf_counter()
            catalog = prompt_shortcut_catalog()
            result = json_response(
                True,
                "Prompt shortcuts loaded",
                details={
                    "shortcuts": catalog["shortcuts"],
                    "client_side_only": catalog["client_side_only"],
                    "notes": catalog["notes"],
                },
            )
            return audit_tool_call("prompt_shortcuts", {}, result, started_at=started_at)

        results["prompt_shortcuts"] = prompt_shortcuts

    if _enabled is None or "appeal_decision" in _enabled:

        @mcp.tool(**tool_options("Appeal a policy decision by record id.", destructive=True))
        async def appeal_decision(
            record_id: str,
            justification: str,
            escalate: bool = False,
            escalation_target: str = "team_lead",
        ) -> str:
            started_at = time.perf_counter()
            try:
                result = process_appeal(
                    record_id,
                    justification,
                    escalate=escalate,
                    escalation_target=escalation_target,
                )
            except ValueError as exc:
                result_obj = json_response(
                    False, str(exc), code="appeal_failed", details={"record_id": record_id}
                )
                return audit_tool_call(
                    "appeal_decision",
                    {
                        "record_id": record_id,
                        "justification": justification,
                        "escalate": escalate,
                        "escalation_target": escalation_target,
                    },
                    result_obj,
                    started_at=started_at,
                )
            result_obj = json_response(True, "Appeal processed", details=result)
            return audit_tool_call(
                "appeal_decision",
                {
                    "record_id": record_id,
                    "justification": justification,
                    "escalate": escalate,
                    "escalation_target": escalation_target,
                },
                result_obj,
                started_at=started_at,
            )

        results["appeal_decision"] = appeal_decision

    if _enabled is None or "send_feedback" in _enabled:

        @mcp.tool(**tool_options("Send user feedback with a rating (1-5).", destructive=True))
        async def send_feedback(rating: int, comment: str, include_session: bool = True) -> str:
            started_at = time.perf_counter()
            impl_result = send_feedback_impl(
                rating=rating, comment=comment, include_session=include_session
            )
            if not impl_result["ok"]:
                result = json_response(
                    False, impl_result["message"], details=impl_result.get("details", {})
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
            result = json_response(True, impl_result["message"], details=impl_result["details"])
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

        results["send_feedback"] = send_feedback

    if _enabled is None or "anomaly_summary" in _enabled:

        @mcp.tool(**tool_options("Run anomaly detection on recent audit records.", read_only=True))
        async def anomaly_summary(limit: int = 50) -> str:
            started_at = time.perf_counter()
            safe_limit = max(1, min(limit, 500))
            recent = get_recent_tool_calls_impl(limit=safe_limit)
            records = recent.get("records", [])
            session_id = recent.get("session_id", "")
            from claude_bridge.baseline import load_baseline

            baseline_path = project_dir() / ".claude-bridge" / "baseline.json"
            baseline = load_baseline(baseline_path)
            summary = build_anomaly_summary(
                records=records,
                session_id=session_id,
                limit=safe_limit,
                baseline=baseline,
            )
            summary["baseline"]["path"] = str(baseline_path)
            result = json_response(True, "Anomaly scan complete", details=summary)
            return audit_tool_call(
                "anomaly_summary", {"limit": safe_limit}, result, started_at=started_at
            )

        results["anomaly_summary"] = anomaly_summary

    if _enabled is None or "generate_pr_description" in _enabled:

        @mcp.tool(**tool_options("Generate a PR description from a git diff.", read_only=True))
        async def generate_pr_description_tool(diff_text: str) -> str:
            started_at = time.perf_counter()
            parsed = generate_pr_description(diff_text)
            result = json_response(True, "PR description generated", details=parsed)
            return audit_tool_call(
                "generate_pr_description",
                {"diff_text_length": len(diff_text)},
                result,
                started_at=started_at,
            )

        results["generate_pr_description"] = generate_pr_description_tool

    if _enabled is None or "get_trust_score" in _enabled:

        @mcp.tool(
            **tool_options("Calculate a trust score from recent audit records.", read_only=True)
        )
        async def get_trust_score(days: int = 7) -> str:
            started_at = time.perf_counter()
            score_result = get_trust_score_impl(days=days)
            result = json_response(
                score_result.get("ok", True),
                score_result.get("message", "Trust score calculated"),
                details=score_result.get("details", score_result),
            )
            return audit_tool_call("get_trust_score", {"days": days}, result, started_at=started_at)

        results["get_trust_score"] = get_trust_score

    if _enabled is None or "autocomplete" in _enabled:

        @mcp.tool(
            **tool_options(
                "Autocomplete partial input with file, tool, and command suggestions.",
                read_only=True,
            )
        )
        async def autocomplete(partial_input: str, context: str = "") -> str:
            started_at = time.perf_counter()
            suggestions = _autocomplete_suggestions(
                partial_input, project_dir=project_dir, context=context
            )
            result = json_response(
                True, f"Autocomplete suggestions for: {partial_input}", details=suggestions
            )
            return audit_tool_call(
                "autocomplete",
                {"partial_input": partial_input, "context": context},
                result,
                started_at=started_at,
            )

        results["autocomplete"] = autocomplete

    return results


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
