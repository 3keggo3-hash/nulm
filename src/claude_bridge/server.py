"""MCP server implementation for Claude Bridge."""

from __future__ import annotations

import json as _json
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

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
    copy_path as _file_copy_path,
)
from claude_bridge.file_tools import (
    move_file as _file_move_file,
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
from claude_bridge.meta_tool_server import register_meta_tools, register_prompts
from claude_bridge.multi_format import (
    read_image as _multi_format_read_image,
)
from claude_bridge.multi_format import (
    read_pdf as _multi_format_read_pdf,
)
from claude_bridge.smart_tool_registration import register_smart_tools
from claude_bridge.tool_utils import (
    set_active_project_dir as _set_active_project_dir,
)
from claude_bridge.workflow_presets import (
    PROMPT_ARGUMENTS as _PROMPT_ARGUMENTS,
    PROMPT_SHORTCUTS as _PROMPT_SHORTCUTS,
    WORKFLOW_DEFAULT_FOCUS as _WORKFLOW_DEFAULT_FOCUS,
    _CUSTOM_PROMPT_DEFAULTS,
    _PROMPT_CUSTOM_BUILDERS,
    _PROMPT_FOCUS_ARG,
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
    move_file_impl=_file_move_file,
    copy_path_impl=_file_copy_path,
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
move_file = _FILE_TOOLS["move_file"]
copy_path = _FILE_TOOLS["copy_path"]
search_in_files = _FILE_TOOLS["search_in_files"]
patch_file = _FILE_TOOLS["patch_file"]
preview_patch = _FILE_TOOLS["preview_patch"]
undo_last_patch = _FILE_TOOLS["undo_last_patch"]


@mcp.tool(
    **_tool_options(
        "Read a supported image in the configured workspace. Returns MIME type, "
        "dimensions, byte size, and base64 content. Requires the optional "
        "claude-bridge[multi-format] dependency set.",
        read_only=True,
    )
)
async def read_image(path: str) -> str:
    started_at = time.perf_counter()
    result = await _multi_format_read_image(path)
    return _audit_tool_call("read_image", {"path": path}, result, started_at=started_at)


@mcp.tool(
    **_tool_options(
        "Extract text from a PDF in the configured workspace with page pagination. "
        "Requires the optional claude-bridge[multi-format] dependency set.",
        read_only=True,
    )
)
async def read_pdf(path: str, page_start: int = 1, page_end: int | None = None) -> str:
    started_at = time.perf_counter()
    result = await _multi_format_read_pdf(path, page_start=page_start, page_end=page_end)
    return _audit_tool_call(
        "read_pdf",
        {"path": path, "page_start": page_start, "page_end": page_end},
        result,
        started_at=started_at,
    )


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


_META_TOOLS = register_meta_tools(
    mcp=mcp,
    tool_options=_tool_options,
    audit_tool_call=_audit_tool_call,
    json_response=_json_response,
    get_recent_tool_calls_impl=_get_recent_tool_calls_impl,
    summarize_session_impl=_summarize_session_impl,
    current_config=current_config,
    update_runtime_config=update_runtime_config,
    approval_presets=APPROVAL_PRESETS,
    budget_profiles=BUDGET_PROFILES,
    smart_compact_intent=_smart_compact_intent,
    smart_available=_smart_available,
    project_dir=_project_dir,
    allowed_roots=_allowed_roots,
    infer_project_root=_infer_project_root,
    set_active_project_dir=_set_active_project_dir,
    path_outside_project_details=_path_outside_project_details,
    reset_onboarding_state=reset_onboarding_state,
    prompt_shortcut_catalog=_prompt_shortcut_catalog,
)
get_recent_tool_calls = _META_TOOLS["get_recent_tool_calls"]
session_insights = _META_TOOLS["session_insights"]
activity_summary = _META_TOOLS["activity_summary"]
usage_insights = _META_TOOLS["usage_insights"]
bridge_status = _META_TOOLS["bridge_status"]
tools_overview = _META_TOOLS["tools_overview"]
get_config = _META_TOOLS["get_config"]
set_config_value = _META_TOOLS["set_config_value"]
compact_user_intent = _META_TOOLS["compact_user_intent"]
workspace_status = _META_TOOLS["workspace_status"]
switch_project_root = _META_TOOLS["switch_project_root"]
prompt_shortcuts = _META_TOOLS["prompt_shortcuts"]

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


def run_mcp_server() -> None:
    """Run the Claude Bridge MCP server over stdio."""
    mcp.run(transport="stdio")

register_prompts(
    mcp=mcp,
    prompt_shortcuts=_PROMPT_SHORTCUTS,
    prompt_arguments=_PROMPT_ARGUMENTS,
    prompt_focus_arg=_PROMPT_FOCUS_ARG,
    workflow_default_focus=_WORKFLOW_DEFAULT_FOCUS,
    prompt_custom_builders=_PROMPT_CUSTOM_BUILDERS,
    custom_prompt_defaults=_CUSTOM_PROMPT_DEFAULTS,
    workflow_prompt=_workflow_prompt,
)
