"""MCP server implementation for Claude Bridge."""

from __future__ import annotations

import json as _json
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts.base import Message, Prompt, PromptArgument

try:
    from mcp.types import ToolAnnotations
except ImportError:  # pragma: no cover - fallback for older MCP installs
    ToolAnnotations = None  # type: ignore[assignment,misc]

from claude_bridge.audit import (
    get_recent_tool_calls as _get_recent_tool_calls_impl,
    log_tool_call as _log_tool_call,
    reset_audit_session,
    summarize_session as _summarize_session_impl,
)
from claude_bridge.config import (
    APPROVAL_PRESETS,
    BUDGET_PROFILES,
    apply_config,
    configure_from_env_state,
    current_config,
    update_runtime_config,
)
from claude_bridge.onboarding import apply_onboarding as _apply_onboarding
from claude_bridge.onboarding import reset_onboarding_state
from claude_bridge.file_tools import (
    clear_last_bridge_change as _clear_last_bridge_change,
)
from claude_bridge.file_tools import (
    list_directory as _file_list_directory,
)
from claude_bridge.file_tools import (
    patch_file as _file_patch_file,
)
from claude_bridge.file_tools import (
    preview_patch as _file_preview_patch,
)
from claude_bridge.file_tools import (
    read_file as _file_read_file,
)
from claude_bridge.file_tools import (
    read_multiple_files as _file_read_multiple_files,
)
from claude_bridge.file_tools import (
    search_in_files as _file_search_in_files,
)
from claude_bridge.file_tools import (
    undo_last_patch as _file_undo_last_patch,
)
from claude_bridge.file_tools import (
    write_file as _file_write_file,
)
from claude_bridge.file_tool_server import register_file_tools
from claude_bridge.git_ops import git_commit, git_status_snapshot
from claude_bridge.indexing import (
    build_index as _index_build_index,
)
from claude_bridge.indexing import (
    clear_index_cache,
)
from claude_bridge.indexing import (
    iter_searchable_files as _index_iter_searchable_files,
)
from claude_bridge.indexing import (
    iter_source_files as _index_iter_source_files,
)
from claude_bridge.indexing import (
    public_index_payload as _public_index_payload,
)
from claude_bridge.shell_tools import (
    analyze_shell_command as _analyze_shell_command_impl,
)
from claude_bridge.shell_tools import (
    kill_process as _kill_process_impl,
)
from claude_bridge.shell_tools import (
    list_process_sessions as _list_process_sessions_impl,
)
from claude_bridge.shell_tools import (
    read_process_output as _read_process_output_impl,
)
from claude_bridge.relevance import (
    query_terms as _query_terms,
)
from claude_bridge.relevance import (
    rank_indexed_files as _rank_indexed_files,
)
from claude_bridge.shell_tools import (
    reset_process_sessions,
)
from claude_bridge.shell_tools import (
    run_shell as _run_shell_impl,
)
from claude_bridge.shell_tools import (
    start_process as _start_process_impl,
)
from claude_bridge.shell_tools import (
    interact_with_process as _interact_with_process_impl,
)
from claude_bridge.tool_utils import (
    current_allowed_roots as _allowed_roots,
)
from claude_bridge.tool_utils import (
    is_binary_bytes as _is_binary_bytes,
)
from claude_bridge.tool_utils import (
    current_project_dir as _project_dir,
)
from claude_bridge.tool_utils import (
    current_shell_timeout as _shell_timeout,
)
from claude_bridge.tool_utils import (
    infer_project_root as _infer_project_root,
)
from claude_bridge.tool_utils import (
    is_within_root as _is_within_root,
)
from claude_bridge.tool_utils import (
    json_response as _json_response,
)
from claude_bridge.tool_utils import (
    path_from_active_root as _path_from_active_root,
)
from claude_bridge.tool_utils import (
    path_outside_project_details as _path_outside_project_details,
)
from claude_bridge.tool_utils import (
    request_approval as _request_approval,
)
from claude_bridge.tool_utils import (
    resolve_path as _resolve_path,
)
from claude_bridge.smart import (
    DEFAULT_CONTEXT_BUDGET_TOKENS as _DEFAULT_CONTEXT_BUDGET_TOKENS,
    budget_metadata as _smart_budget_metadata,
    compact_intent as _smart_compact_intent,
    context_fit_check as _smart_context_fit_check,
    count_tokens_for_path as _smart_count_tokens_for_path,
    estimate_token_count as _smart_estimate_token_count,
    smart_available as _smart_available,
)
from claude_bridge.insights import (
    project_stats as _insights_project_stats,
    todo_scan as _insights_todo_scan,
    recent_files as _insights_recent_files,
    language_distribution as _insights_language_distribution,
    git_log_summary as _insights_git_log_summary,
    git_diff_summary as _insights_git_diff_summary,
    dependency_map as _insights_dependency_map,
    duplicate_code_scan as _insights_duplicate_code_scan,
    save_note as _insights_save_note,
    read_notes as _insights_read_notes,
)
from claude_bridge.insights_tool_registration import register_insights_tools
from claude_bridge.fun_content import generate_doodle as _generate_doodle
from claude_bridge.smart_tool_registration import register_smart_tools
from claude_bridge.tool_utils import (
    set_active_project_dir as _set_active_project_dir,
)
from claude_bridge.workflow_presets import (
    prompt_shortcut_catalog as _prompt_shortcut_catalog,
    workflow_prompt as _workflow_prompt,
)
from claude_bridge.shell_tool_server import register_shell_tools
from claude_bridge.workflow_tool_server import register_workflow_tools
from claude_bridge.workflow_tools import (
    build_context_pack as _build_context_pack_impl,
)
from claude_bridge.workflow_tools import (
    build_validation_suggestions as _build_validation_suggestions_impl,
)
from claude_bridge.workflow_tools import (
    run_agent_loop_session as _run_agent_loop_session_impl,
)
from claude_bridge.workflow_tools import (
    run_agent_loop_step as _run_agent_loop_step_impl,
)
from claude_bridge.workflow_tools import (
    run_workflow as _run_workflow_impl,
)

mcp = FastMCP("Claude Bridge")

def _effective_budget_tokens() -> int:
    profile_name = current_config().get("context_budget_profile", "balanced")
    profile = BUDGET_PROFILES.get(profile_name, {})
    return int(profile.get("context_budget_tokens", _DEFAULT_CONTEXT_BUDGET_TOKENS))

def _tool_options(
    description: str,
    *,
    read_only: bool = False,
    destructive: bool = False,
    open_world: bool = False,
) -> dict[str, Any]:
    options: dict[str, Any] = {"description": description}
    if ToolAnnotations is not None:
        options["annotations"] = ToolAnnotations(
            readOnlyHint=read_only,
            destructiveHint=destructive,
            openWorldHint=open_world,
        )
    return options

def set_config(
    project_dir: Path,
    allowed_roots: list[Path] | None = None,
    auto_approve: bool = False,
    client_managed_approval: bool = False,
    shell_timeout: int = 30,
    approval_preset: str | None = None,
) -> None:
    """Set runtime configuration for the MCP tools and reset cached per-session state."""
    reset_audit_session()
    reset_onboarding_state()
    reset_process_sessions()
    apply_config(
        project_dir=project_dir,
        allowed_roots=allowed_roots,
        auto_approve=auto_approve,
        client_managed_approval=client_managed_approval,
        shell_timeout=shell_timeout,
        approval_preset=approval_preset,
    )
    clear_index_cache()
    _clear_last_bridge_change()

def configure_from_env(*, force_auto_approve: bool | None = None) -> None:
    """Load runtime configuration from environment variables."""
    reset_audit_session()
    reset_onboarding_state()
    reset_process_sessions()
    configure_from_env_state(force_auto_approve=force_auto_approve)
    clear_index_cache()
    _clear_last_bridge_change()

def _build_index(path: str) -> dict[str, Any]:
    return _index_build_index(
        path,
        resolve_path=_resolve_path,
        infer_project_root=_infer_project_root,
        is_within_root=_is_within_root,
    )

def _iter_source_files(root: Path, project_root: Path) -> list[Path]:
    return _index_iter_source_files(root, project_root, is_within_root=_is_within_root)

def _iter_searchable_files(
    root: Path, project_root: Path, include_glob: str | None = None
) -> list[Path]:
    return _index_iter_searchable_files(
        root,
        project_root,
        is_within_root=_is_within_root,
        is_binary_bytes=_is_binary_bytes,
        include_glob=include_glob,
    )

def _git_commit(
    file_path: str,
    project_dir: Path | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    return git_commit(
        file_path,
        project_dir=(project_dir or _project_dir()),
        message=message,
    )

def _git_status_snapshot(project_dir: Path | None = None) -> dict[str, Any]:
    return git_status_snapshot(project_dir or _project_dir())

def _audit_tool_call(
    tool_name: str, params: dict[str, Any], result: str, *, started_at: float
) -> str:
    enriched_result = _apply_onboarding(
        tool_name,
        result,
        enabled=bool(current_config().get("onboarding_enabled", True)),
    )
    _log_tool_call(
        tool_name,
        params,
        enriched_result,
        duration_ms=(time.perf_counter() - started_at) * 1000,
    )
    return enriched_result

def _safe_json_object_load(raw: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    try:
        payload = _json.loads(raw)
    except _json.JSONDecodeError as exc:
        return None, {
            "ok": False,
            "message": "Tool returned invalid JSON",
            "code": "invalid_tool_payload",
            "details": {"error": str(exc)},
        }
    if not isinstance(payload, dict):
        return None, {
            "ok": False,
            "message": "Tool returned a non-object payload",
            "code": "invalid_tool_payload",
            "details": {"payload_type": type(payload).__name__},
        }
    return payload, None

_FILE_TOOLS = register_file_tools(
    mcp=mcp,
    tool_options=_tool_options,
    audit_tool_call=_audit_tool_call,
    resolve_path=_resolve_path,
    json_response=_json_response,
    effective_budget_tokens=_effective_budget_tokens,
    read_file_impl=_file_read_file,
    read_multiple_files_impl=_file_read_multiple_files,
    list_directory_impl=_file_list_directory,
    write_file_impl=_file_write_file,
    search_in_files_impl=_file_search_in_files,
    patch_file_impl=_file_patch_file,
    preview_patch_impl=_file_preview_patch,
    undo_last_patch_impl=_file_undo_last_patch,
    git_commit_fn=lambda *a, **kw: _git_commit(*a, **kw),
    request_approval_fn=lambda *a, **kw: _request_approval(*a, **kw),
)
read_file = _FILE_TOOLS["read_file"]
read_multiple_files = _FILE_TOOLS["read_multiple_files"]
list_directory = _FILE_TOOLS["list_directory"]
write_file = _FILE_TOOLS["write_file"]
search_in_files = _FILE_TOOLS["search_in_files"]
patch_file = _FILE_TOOLS["patch_file"]
preview_patch = _FILE_TOOLS["preview_patch"]
undo_last_patch = _FILE_TOOLS["undo_last_patch"]


_SHELL_TOOLS = register_shell_tools(
    mcp=mcp,
    tool_options=_tool_options,
    audit_tool_call=_audit_tool_call,
    json_response=_json_response,
    analyze_shell_command_impl=_analyze_shell_command_impl,
    run_shell_impl=_run_shell_impl,
    start_process_impl=_start_process_impl,
    read_process_output_impl=_read_process_output_impl,
    list_process_sessions_impl=_list_process_sessions_impl,
    kill_process_impl=_kill_process_impl,
    interact_with_process_impl=_interact_with_process_impl,
    request_approval=_request_approval,
    project_dir=_project_dir,
    shell_timeout=_shell_timeout,
)
analyze_shell_command = _SHELL_TOOLS["analyze_shell_command"]
run_shell = _SHELL_TOOLS["run_shell"]
start_process = _SHELL_TOOLS["start_process"]
read_process_output = _SHELL_TOOLS["read_process_output"]
list_process_sessions = _SHELL_TOOLS["list_process_sessions"]
kill_process = _SHELL_TOOLS["kill_process"]
interact_with_process = _SHELL_TOOLS["interact_with_process"]
_is_interactive_command = _SHELL_TOOLS["_is_interactive_command"]
_normalize_command_for_safety = _SHELL_TOOLS["_normalize_command_for_safety"]
_blocked_command_reason = _SHELL_TOOLS["_blocked_command_reason"]

@mcp.tool(
    **_tool_options(
        "Create a lightweight symbol index for a codebase. Use this before relevance or architectural questions instead of reading many files blindly.",
        read_only=True,
    )
)
async def index_codebase(path: str = ".") -> str:
    started_at = time.perf_counter()
    try:
        payload = _build_index(path)
    except PermissionError as exc:
        result = _json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=_path_outside_project_details(path),
        )
        return _audit_tool_call("index_codebase", {"path": path}, result, started_at=started_at)
    except FileNotFoundError:
        result = _json_response(
            False,
            f"Directory not found: {path}",
            code="directory_not_found",
            details={"path": path},
        )
        return _audit_tool_call("index_codebase", {"path": path}, result, started_at=started_at)
    except NotADirectoryError:
        result = _json_response(
            False,
            f"Not a directory: {path}",
            code="not_a_directory",
            details={"path": path},
        )
        return _audit_tool_call("index_codebase", {"path": path}, result, started_at=started_at)

        if not isinstance(payload, dict) or "files" not in payload:
            result = _json_response(
                False,
                "Index build returned unexpected payload",
                code="invalid_index_payload",
                details={"path": path},
            )
            return _audit_tool_call("index_codebase", {"path": path}, result, started_at=started_at)

    result = _json_response(
        True,
        f"Indexed codebase: {path}",
        details=_public_index_payload(payload),
    )
    return _audit_tool_call("index_codebase", {"path": path}, result, started_at=started_at)

@mcp.tool(
    **_tool_options(
        "Find the most relevant files for a natural-language query using indexed scoring. Use this before reading files, and prefer specific queries over broad ones.",
        read_only=True,
    )
)
async def find_relevant_files(
    query: str,
    path: str = ".",
    limit: int = 5,
    budget_tokens: int | None = None,
) -> str:
    bt = budget_tokens if budget_tokens is not None else _effective_budget_tokens()
    started_at = time.perf_counter()
    audit_params = {"query": query, "path": path, "limit": limit, "budget_tokens": bt}
    stripped = query.strip()
    if not stripped:
        result = _json_response(
            False,
            "Query cannot be empty",
            code="empty_query",
            details={"query": query},
        )
        return _audit_tool_call("find_relevant_files", audit_params, result, started_at=started_at)
    if limit < 1:
        result = _json_response(
            False,
            "Limit must be at least 1",
            code="invalid_limit",
            details={"limit": limit},
        )
        return _audit_tool_call("find_relevant_files", audit_params, result, started_at=started_at)

    try:
        index_payload = _build_index(path)
    except PermissionError as exc:
        result = _json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=_path_outside_project_details(path),
        )
        return _audit_tool_call("find_relevant_files", audit_params, result, started_at=started_at)
    except FileNotFoundError:
        result = _json_response(
            False,
            f"Directory not found: {path}",
            code="directory_not_found",
            details={"path": path},
        )
        return _audit_tool_call("find_relevant_files", audit_params, result, started_at=started_at)
    except NotADirectoryError:
        result = _json_response(
            False,
            f"Not a directory: {path}",
            code="not_a_directory",
            details={"path": path},
        )
        return _audit_tool_call("find_relevant_files", audit_params, result, started_at=started_at)
    ranked = _rank_indexed_files(index_payload, query=stripped, limit=limit)
    result = _json_response(
        True,
        f"Relevant files found for query: {query}",
        details={
            "query": query,
            "terms": _query_terms(stripped),
            "results": ranked["results"],
            "total_results": ranked["total_results"],
            "cached": ranked.get("cached", False),
            "strategy": ranked.get("strategy", "token_scoring"),
            **_smart_budget_metadata(
                estimated_tokens=_smart_estimate_token_count(
                    "\n".join(item["path"] for item in ranked["results"])
                ),
                budget_tokens=bt,
                recommended_next_step="Call read_file on the strongest result or use narrow_context for a tighter budget-aware pack.",
            ),
        },
    )
    return _audit_tool_call("find_relevant_files", audit_params, result, started_at=started_at)
_WORKFLOW_TOOLS = register_workflow_tools(
    mcp=mcp,
    tool_options=_tool_options,
    audit_tool_call=_audit_tool_call,
    json_response=_json_response,
    run_agent_loop_step_impl=_run_agent_loop_step_impl,
    build_context_pack_impl=_build_context_pack_impl,
    build_validation_suggestions_impl=_build_validation_suggestions_impl,
    run_agent_loop_session_impl=_run_agent_loop_session_impl,
    run_workflow_impl=_run_workflow_impl,
    patch_file_getter=lambda: patch_file,
    run_shell_getter=lambda: run_shell,
    read_file_getter=lambda: read_file,
    list_directory_getter=lambda: list_directory,
    find_relevant_files_getter=lambda: find_relevant_files,
    resolve_path=_resolve_path,
    path_from_active_root=_path_from_active_root,
    project_dir=_project_dir,
    infer_project_root=_infer_project_root,
    iter_searchable_files=_iter_searchable_files,
    git_status_snapshot=_git_status_snapshot,
    effective_budget_tokens=_effective_budget_tokens,
    safe_json_object_load=_safe_json_object_load,
    smart_budget_metadata=_smart_budget_metadata,
)
run_agent_loop_step = _WORKFLOW_TOOLS["run_agent_loop_step"]
build_context_pack = _WORKFLOW_TOOLS["build_context_pack"]
narrow_context = _WORKFLOW_TOOLS["narrow_context"]
suggest_validation_commands = _WORKFLOW_TOOLS["suggest_validation_commands"]
run_agent_loop_session = _WORKFLOW_TOOLS["run_agent_loop_session"]
run_workflow = _WORKFLOW_TOOLS["run_workflow"]



@mcp.tool(
    **_tool_options(
        "Show recent Claude Bridge tool calls from the current or latest audit session. Use this to explain what the bridge did recently.",
        read_only=True,
    )
)
async def get_recent_tool_calls(limit: int = 20, tool_name: str | None = None) -> str:
    started_at = time.perf_counter()
    safe_limit = max(1, min(limit, 100))
    result = _json_response(
        True,
        "Recent tool calls loaded",
        details=_get_recent_tool_calls_impl(limit=safe_limit, tool_name=tool_name),
    )
    return _audit_tool_call(
        "get_recent_tool_calls",
        {"limit": safe_limit, "tool_name": tool_name},
        result,
        started_at=started_at,
    )

@mcp.tool(
    **_tool_options(
        "Show session-level telemetry such as approximate token usage, input/output sizes, truncation count, and tool-level cost hotspots.",
        read_only=True,
    )
)
async def session_insights(limit: int = 50) -> str:
    started_at = time.perf_counter()
    safe_limit = max(1, min(limit, 200))
    summary = _summarize_session_impl(limit=safe_limit)
    result = _json_response(
        True,
        "Session insights loaded",
        details=summary,
    )
    return _audit_tool_call(
        "session_insights",
        {"limit": safe_limit},
        result,
        started_at=started_at,
    )

@mcp.tool(
    **_tool_options(
        "Show usage-focused telemetry with token hotspots and truncation signals. Use this when you want to reduce cost or identify noisy tools.",
        read_only=True,
    )
)
async def usage_insights(limit: int = 50) -> str:
    started_at = time.perf_counter()
    safe_limit = max(1, min(limit, 200))
    summary = _summarize_session_impl(limit=safe_limit)
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
    result = _json_response(
        True,
        "Usage insights loaded",
        details={
            "session_id": summary["session_id"],
            "telemetry": telemetry,
            "top_cost_tools": top_tools,
            "recommended_next_step": (
                "Use narrow_context, compact, or a lower context budget profile if one tool is dominating token usage."
            ),
        },
    )
    return _audit_tool_call(
        "usage_insights",
        {"limit": safe_limit},
        result,
        started_at=started_at,
    )

@mcp.tool(
    **_tool_options(
        "Show the most useful current runtime status in one place: workspace, budget profile, approvals, smart features, and recent telemetry.",
        read_only=True,
    )
)
async def bridge_status() -> str:
    started_at = time.perf_counter()
    config_snapshot = current_config()
    session_summary = _summarize_session_impl(limit=20)
    smart_available = _smart_available()
    profile_name = str(config_snapshot.get("context_budget_profile", "balanced"))
    profile = BUDGET_PROFILES.get(profile_name, {})
    result = _json_response(
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
            "smart_features": smart_available,
            "session_telemetry": session_summary.get("telemetry", {}),
        },
    )
    return _audit_tool_call("bridge_status", {}, result, started_at=started_at)

@mcp.tool(
    **_tool_options(
        "List the most useful Claude Bridge tools, grouped by purpose, with a note about lower-token entrypoints.",
        read_only=True,
    )
)
async def tools_overview() -> str:
    started_at = time.perf_counter()
    result = _json_response(
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
                "analysis": ["run_workflow", "prompt_shortcuts", "project_insights", "todo_scan"],
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
    return _audit_tool_call("tools_overview", {}, result, started_at=started_at)

@mcp.tool(
    **_tool_options(
        "Show the current Claude Bridge runtime configuration, including approval mode and active preset. Use this before changing config values.",
        read_only=True,
    )
)
async def get_config() -> str:
    started_at = time.perf_counter()
    snapshot = current_config()
    result = _json_response(
        True,
        "Runtime configuration loaded",
        details={
            **snapshot,
            "project_dir": str(snapshot["project_dir"]),
            "allowed_roots": [str(root) for root in snapshot["allowed_roots"]],
            "approval_presets": APPROVAL_PRESETS,
            "budget_profiles": BUDGET_PROFILES,
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
    return _audit_tool_call("get_config", {}, result, started_at=started_at)

@mcp.tool(
    **_tool_options(
        "Update a single Claude Bridge runtime configuration value. Supported keys: approval_preset, auto_approve, client_managed_approval, shell_timeout, onboarding_enabled, context_budget_profile, intent_compaction_enabled.",
        destructive=True,
    )
)
async def set_config_value(key: str, value: Any) -> str:
    started_at = time.perf_counter()
    try:
        updated = update_runtime_config(key, value)
    except ValueError as exc:
        result = _json_response(
            False,
            str(exc),
            code="invalid_config_value",
            details={"key": key, "value": value},
        )
        return _audit_tool_call(
            "set_config_value", {"key": key, "value": value}, result, started_at=started_at
        )

    result = _json_response(
        True,
        f"Updated runtime config: {key}",
        details={
            **updated,
            "project_dir": str(updated["project_dir"]),
            "allowed_roots": [str(root) for root in updated["allowed_roots"]],
        },
    )
    return _audit_tool_call(
        "set_config_value", {"key": key, "value": value}, result, started_at=started_at
    )

@mcp.tool(
    **_tool_options(
        "Compact a natural-language request into a smaller canonical intent object. Enable this mode when you want cheaper internal routing without automatic translation.",
        read_only=True,
    )
)
async def compact_user_intent(
    text: str,
    preserve_language: bool = True,
) -> str:
    started_at = time.perf_counter()
    enabled = bool(current_config().get("intent_compaction_enabled", False))
    details = _smart_compact_intent(text, preserve_language=preserve_language)
    details["intent_compaction_enabled"] = enabled
    details["mode_behavior"] = (
        "active"
        if enabled
        else "available but inactive until intent_compaction_enabled is turned on"
    )
    details["recommended_next_step"] = (
        "Turn on intent_compaction_enabled if you want clients or future workflows to prefer this compact form by default."
    )
    result = _json_response(
        True,
        "User intent compacted",
        details=details,
    )
    return _audit_tool_call(
        "compact_user_intent",
        {
            "text_length": len(text),
            "preserve_language": preserve_language,
        },
        result,
        started_at=started_at,
    )

@mcp.tool(
    **_tool_options(
        "Show the active project root and the full list of allowed roots. Use this when a path fails or before switching workspaces.",
        read_only=True,
    )
)
async def workspace_status() -> str:
    started_at = time.perf_counter()
    result = _json_response(
        True,
        "Workspace status",
        details={
            "active_project_dir": str(_project_dir()),
            "allowed_roots": [str(root) for root in _allowed_roots()],
            "root_rules": {
                "can_switch_to_subdirectories": True,
                "explanation": (
                    "Any existing subdirectory inside an allowed root can be selected as the active project root."
                ),
                "example": (
                    "If '/Users/me/Desktop' is allowed, you can switch to '/Users/me/Desktop/tertis'."
                ),
            },
        },
    )
    return _audit_tool_call("workspace_status", {}, result, started_at=started_at)

@mcp.tool(
    **_tool_options(
        "Switch the active project root to another allowed directory. Use this only when the current task clearly belongs in a different allowed workspace.",
        destructive=True,
    )
)
async def switch_project_root(path: str) -> str:
    started_at = time.perf_counter()
    candidate = Path(path)
    target = (
        candidate.resolve() if candidate.is_absolute() else (_project_dir() / candidate).resolve()
    )
    if not target.exists():
        result = _json_response(
            False,
            f"Directory not found: {path}",
            code="directory_not_found",
            details={"path": path},
        )
        return _audit_tool_call(
            "switch_project_root", {"path": path}, result, started_at=started_at
        )
    if not target.is_dir():
        result = _json_response(
            False,
            f"Not a directory: {path}",
            code="not_a_directory",
            details={"path": path},
        )
        return _audit_tool_call(
            "switch_project_root", {"path": path}, result, started_at=started_at
        )
    try:
        _infer_project_root(target)
        _set_active_project_dir(target)
    except PermissionError as exc:
        result = _json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=_path_outside_project_details(path),
        )
        return _audit_tool_call(
            "switch_project_root", {"path": path}, result, started_at=started_at
        )

    result = _json_response(
        True,
        f"Active project root switched to: {target}",
        details={
            "active_project_dir": str(_project_dir()),
            "allowed_roots": [str(root) for root in _allowed_roots()],
            "switched_from_subdirectory_rule": True,
        },
    )
    return _audit_tool_call("switch_project_root", {"path": path}, result, started_at=started_at)


@mcp.tool(
    **_tool_options(
        "List Claude Bridge prompt shortcuts and explain which ones can truly avoid a full chat planning turn. "
        "Use this when you want lower-token entrypoints such as MCP prompts or slash-style shortcuts.",
        read_only=True,
    )
)
async def prompt_shortcuts() -> str:
    started_at = time.perf_counter()
    catalog = _prompt_shortcut_catalog()
    details = {
        "shortcuts": catalog["shortcuts"],
        "client_side_only": catalog["client_side_only"],
        "notes": catalog["notes"],
        "recommended_path": "Use an MCP prompt or slash UI when the client exposes it; fall back to run_workflow or a natural-language request only when necessary.",
    }
    result = _json_response(
        True,
        "Prompt shortcuts loaded",
        details=details,
    )
    return _audit_tool_call("prompt_shortcuts", {}, result, started_at=started_at)

_SMART_TOOLS = register_smart_tools(
    mcp=mcp,
    tool_options=_tool_options,
    audit_tool_call=_audit_tool_call,
    resolve_path=_resolve_path,
    json_response=_json_response,
    count_tokens_for_path=_smart_count_tokens_for_path,
    context_fit_check=_smart_context_fit_check,
    smart_available=_smart_available,
)
count_file_tokens = _SMART_TOOLS["count_file_tokens"]
context_fit = _SMART_TOOLS["context_fit"]
smart_status = _SMART_TOOLS["smart_status"]

_INSIGHTS_TOOLS = register_insights_tools(
    mcp=mcp,
    tool_options=_tool_options,
    audit_tool_call=_audit_tool_call,
    resolve_path=_resolve_path,
    json_response=_json_response,
    project_dir=_project_dir,
    project_stats=_insights_project_stats,
    todo_scan=_insights_todo_scan,
    recent_files=_insights_recent_files,
    language_distribution=_insights_language_distribution,
    git_log_summary=_insights_git_log_summary,
    git_diff_summary=_insights_git_diff_summary,
    duplicate_code_scan=_insights_duplicate_code_scan,
    dependency_map=_insights_dependency_map,
    save_note=_insights_save_note,
    read_notes=_insights_read_notes,
    generate_doodle=_generate_doodle,
    doodle_random=__import__("random"),
)
project_insights = _INSIGHTS_TOOLS["project_insights"]
todo_scan = _INSIGHTS_TOOLS["todo_scan"]
recent_files = _INSIGHTS_TOOLS["recent_files"]
language_distribution = _INSIGHTS_TOOLS["language_distribution"]
git_insights = _INSIGHTS_TOOLS["git_insights"]
git_diff_insights = _INSIGHTS_TOOLS["git_diff_insights"]
duplicate_code_scan = _INSIGHTS_TOOLS["duplicate_code_scan"]
dependency_insights = _INSIGHTS_TOOLS["dependency_insights"]
bridge_save_note = _INSIGHTS_TOOLS["bridge_save_note"]
bridge_read_notes = _INSIGHTS_TOOLS["bridge_read_notes"]
bridge_doodle = _INSIGHTS_TOOLS["bridge_doodle"]

def _register_prompts() -> None:
    def _message(text: str) -> Message:
        return Message(text, role="user")

    def review_prompt(target: str = ".", focus: str = "bugs and missing tests") -> Message:
        return _message(_workflow_prompt("review", target, focus, "Turkish"))

    def optimize_prompt(target: str = ".", focus: str = "performance and readability") -> Message:
        return _message(_workflow_prompt("optimize", target, focus, "Turkish"))

    def orchestrate_prompt(
        target: str = ".",
        focus: str = "decompose into independent workstreams with clear ownership",
    ) -> Message:
        return _message(_workflow_prompt("orchestrate", target, focus, "Turkish"))

    def agent_loop_prompt(
        target: str = ".",
        goal: str = "fix the current issue with small validated steps",
    ) -> Message:
        return _message(_workflow_prompt("agent_loop", target, goal, "Turkish"))

    def quality_prompt(
        target: str = ".",
        focus: str = "correctness, regression safety, readability, tests, and verification depth",
    ) -> Message:
        return _message(_workflow_prompt("quality", target, focus, "Turkish"))

    def test_prompt(target: str = ".", test_style: str = "regression tests") -> Message:
        return _message(_workflow_prompt("test", target, test_style, "Turkish"))

    def todo_prompt(target: str = ".", keywords: str = "TODO, FIXME, HACK, XXX") -> Message:
        return _message(_workflow_prompt("todo", target, keywords, "Turkish"))

    def explain_prompt(
        target: str = ".",
        audience: str = "a junior developer",
        language: str = "Turkish",
    ) -> Message:
        return _message(_workflow_prompt("explain", target, audience, language))

    def commit_prompt(
        target: str = ".",
        style: str = "short imperative commit message with a concise summary",
    ) -> Message:
        return _message(_workflow_prompt("commit", target, style, "Turkish"))

    def compact_prompt(
        target: str = ".",
        goal: str = "continue the task with a smaller, cheaper working context",
    ) -> Message:
        return _message(
            "Shrink the active context before doing more work.\n"
            f"Target: {target}\n"
            f"Goal: {goal}\n"
            "Response language: Turkish\n"
            "Prefer the smallest useful set of files, the narrowest read windows, and the cheapest next step.\n"
            "Call out what can be deferred until later if it does not fit the current budget."
        )

    def shadow_prompt(
        target: str = ".",
        focus: str = "challenge prior assumptions, verify from files, and be skeptical of earlier conclusions",
    ) -> Message:
        return _message(
            _workflow_prompt("review", target, focus, "Turkish")
            + "\nTreat earlier assumptions as untrusted until the files confirm them.\n"
            + "Prefer a cold, critical reread over agreement-seeking."
        )

    def benchmark_prompt(
        target: str = ".",
        focus: str = "startup cost, relevance latency, token efficiency, and cache behavior",
    ) -> Message:
        return _message(
            "Prepare a benchmark-first investigation plan.\n"
            f"Target: {target}\n"
            f"Focus: {focus}\n"
            "Response language: Turkish\n"
            "Start with the cheapest signals first.\n"
            "Separate measurement from interpretation.\n"
            "Call out what can be learned without spending a full benchmark run yet."
        )

    def platform_prompt(
        target: str = ".",
        focus: str = "Linux, Windows, WSL, VS Code, and other MCP client compatibility",
    ) -> Message:
        return _message(
            "Audit cross-platform and editor compatibility.\n"
            f"Target: {target}\n"
            f"Focus: {focus}\n"
            "Response language: Turkish\n"
            "List platform assumptions, packaging risks, path issues, shell differences, and client integration gaps.\n"
            "Prefer a matrix of concrete risks and verifications over vague advice."
        )

    prompt_specs = [
        (
            "review",
            "Review code for bugs and missing tests.",
            [
                PromptArgument(
                    name="target", description="File or directory to review", required=False
                ),
                PromptArgument(name="focus", description="Specific review focus", required=False),
            ],
            review_prompt,
        ),
        (
            "optimize",
            "Optimize code for performance and maintainability.",
            [
                PromptArgument(
                    name="target", description="File or directory to optimize", required=False
                ),
                PromptArgument(name="focus", description="Optimization focus", required=False),
            ],
            optimize_prompt,
        ),
        (
            "orchestrate",
            "Turn a larger task into parallel workstreams plus an integration plan.",
            [
                PromptArgument(
                    name="target", description="File or directory to orchestrate", required=False
                ),
                PromptArgument(name="focus", description="How to split the work", required=False),
            ],
            orchestrate_prompt,
        ),
        (
            "agent_loop",
            "Plan a bounded inspect-patch-validate loop for a focused coding task.",
            [
                PromptArgument(
                    name="target", description="File or directory for the loop", required=False
                ),
                PromptArgument(
                    name="goal", description="What the loop should accomplish", required=False
                ),
            ],
            agent_loop_prompt,
        ),
        (
            "quality",
            "Evaluate code quality against a practical shipping standard.",
            [
                PromptArgument(
                    name="target", description="File or directory to evaluate", required=False
                ),
                PromptArgument(name="focus", description="Specific quality focus", required=False),
            ],
            quality_prompt,
        ),
        (
            "test",
            "Plan tests for the selected target.",
            [
                PromptArgument(
                    name="target", description="File or directory to test", required=False
                ),
                PromptArgument(
                    name="test_style", description="Preferred testing style", required=False
                ),
            ],
            test_prompt,
        ),
        (
            "todo",
            "Scan for TODO-style markers and prioritize them.",
            [
                PromptArgument(
                    name="target", description="File or directory to scan", required=False
                ),
                PromptArgument(
                    name="keywords", description="Keywords to search for", required=False
                ),
            ],
            todo_prompt,
        ),
        (
            "explain",
            "Explain how a piece of code works.",
            [
                PromptArgument(
                    name="target", description="File or directory to explain", required=False
                ),
                PromptArgument(name="audience", description="Audience level", required=False),
                PromptArgument(name="language", description="Response language", required=False),
            ],
            explain_prompt,
        ),
        (
            "commit",
            "Summarize changes and suggest a commit message.",
            [
                PromptArgument(
                    name="target", description="File or directory to summarize", required=False
                ),
                PromptArgument(
                    name="style", description="Preferred commit message style", required=False
                ),
            ],
            commit_prompt,
        ),
        (
            "compact",
            "Shrink the active context and continue with a lower-cost plan.",
            [
                PromptArgument(
                    name="target", description="File or directory to narrow", required=False
                ),
                PromptArgument(
                    name="goal", description="What to preserve while compacting", required=False
                ),
            ],
            compact_prompt,
        ),
        (
            "shadow",
            "Re-review a target skeptically and challenge prior assumptions.",
            [
                PromptArgument(
                    name="target", description="File or directory to re-review", required=False
                ),
                PromptArgument(name="focus", description="Critical review focus", required=False),
            ],
            shadow_prompt,
        ),
        (
            "benchmark",
            "Prepare a benchmark-first investigation plan.",
            [
                PromptArgument(
                    name="target", description="File or directory to assess", required=False
                ),
                PromptArgument(name="focus", description="Benchmark focus", required=False),
            ],
            benchmark_prompt,
        ),
        (
            "platform",
            "Audit cross-platform and editor compatibility gaps.",
            [
                PromptArgument(
                    name="target", description="File or directory to assess", required=False
                ),
                PromptArgument(
                    name="focus", description="Platform or client focus", required=False
                ),
            ],
            platform_prompt,
        ),
    ]

    for name, description, arguments, fn in prompt_specs:
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

def run_mcp_server() -> None:
    """Run the Claude Bridge MCP server over stdio."""
    mcp.run(transport="stdio")

_register_prompts()
