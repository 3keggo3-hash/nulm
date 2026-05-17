"""MCP server implementation for Claude Bridge."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json as _json
import threading
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
from claude_bridge.feedback import send_feedback_impl
from claude_bridge.trust_score import get_trust_score as get_trust_score_impl
from claude_bridge.config import (
    APPROVAL_PRESETS,
    BUDGET_PROFILES,
    active_tool_names,
    apply_config,
    configure_from_env_state,
    current_config,
    raw_ai_evaluator_config,
    update_runtime_config,
)
from claude_bridge.control_plane_tool_server import register_control_plane_tools
from claude_bridge.onboarding import apply_onboarding as _apply_onboarding
from claude_bridge.onboarding import reset_onboarding_state
from claude_bridge.file_tools import (
    clear_last_bridge_change as _clear_last_bridge_change,
)
from claude_bridge.file_tools import (
    append_to_file as _file_append_to_file,
)
from claude_bridge.file_tools import (
    diff_files as _file_diff_files,
)
from claude_bridge.file_tools import (
    find_files as _file_find_files,
)
from claude_bridge.file_tools import (
    list_directory as _file_list_directory,
)
from claude_bridge.file_tools import (
    copy_path as _file_copy_path,
)
from claude_bridge.file_tools import (
    mkdir as _file_mkdir,
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
    path_exists as _file_path_exists,
)
from claude_bridge.file_tools import (
    stat_file as _file_stat_file,
)
from claude_bridge.file_tools import (
    undo_last_patch as _file_undo_last_patch,
)
from claude_bridge.file_tools import (
    write_file as _file_write_file,
)
from claude_bridge.file_tool_server import register_file_tools
from claude_bridge.git_ops import (
    git_commit,
    git_diff,
    git_log,
    git_status_snapshot,
)
from claude_bridge.git_tool_server import register_git_tools
from claude_bridge.indexing_tool_server import register_indexing_tools
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
from claude_bridge.shell_tools import (
    interactive_shell as _interactive_shell_impl,
)
from claude_bridge.shell_tools import (
    send_to_process as _send_to_process_impl,
)
from claude_bridge.shell_tools import (
    get_process_status as _get_process_status_impl,
)
from claude_bridge.tool_utils import (
    current_allowed_roots as _allowed_roots,
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
from claude_bridge.meta_tool_server import register_meta_tools, register_prompts
from claude_bridge.multi_format_tool_server import register_multi_format_tools
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
from claude_bridge.url_tool_server import register_url_tools
from claude_bridge.notification_tool_server import register_notification_tools

mcp = FastMCP("Claude Bridge")
_DEFAULT_CONTEXT_BUDGET_TOKENS = 4000


def _enabled_tool_names_for_registration() -> set[str] | None:
    configure_from_env_state()
    return active_tool_names()


_ENABLED_TOOL_NAMES = _enabled_tool_names_for_registration()


def _should_register_tool(name: str) -> bool:
    return _ENABLED_TOOL_NAMES is None or name in _ENABLED_TOOL_NAMES


def _register_tool(
    name: str,
    description: str,
    *,
    read_only: bool = False,
    destructive: bool = False,
    open_world: bool = False,
) -> Any:
    def _decorator(fn: Any) -> Any:
        if not _should_register_tool(name):
            return fn
        return mcp.tool(
            **_tool_options(
                description,
                read_only=read_only,
                destructive=destructive,
                open_world=open_world,
            )
        )(fn)

    return _decorator


def _tool_or_disabled(tools: dict[str, Any], name: str) -> Any:
    if name in tools:
        return tools[name]

    async def _disabled_tool(*_args: Any, **_kwargs: Any) -> str:
        return _json_response(
            False,
            f"Tool disabled by active tool profile: {name}",
            code="tool_disabled",
            details={"tool_name": name},
        )

    return _disabled_tool


def _effective_budget_tokens() -> int:
    profile_name = current_config().get("context_budget_profile", "balanced")
    profile = BUDGET_PROFILES.get(profile_name, {})
    return int(profile.get("context_budget_tokens", _DEFAULT_CONTEXT_BUDGET_TOKENS))


def _smart_budget_metadata(
    *, estimated_tokens: int, budget_tokens: int, recommended_next_step: str
) -> dict[str, Any]:
    from claude_bridge.smart import budget_metadata

    return budget_metadata(
        estimated_tokens=estimated_tokens,
        budget_tokens=budget_tokens,
        recommended_next_step=recommended_next_step,
    )


def _smart_estimate_token_count(text: str) -> int:
    from claude_bridge.smart import estimate_token_count

    return estimate_token_count(text)


def _smart_compact_intent(
    text: str,
    *,
    max_keywords: int = 6,
    preserve_language: bool = True,
) -> dict[str, Any]:
    from claude_bridge.smart import compact_intent

    return compact_intent(
        text,
        max_keywords=max_keywords,
        preserve_language=preserve_language,
    )


def _smart_available() -> dict[str, bool]:
    from claude_bridge.smart import smart_available

    return smart_available()


def _smart_count_tokens_for_path(path: Path) -> dict[str, Any]:
    from claude_bridge.smart import count_tokens_for_path

    return count_tokens_for_path(path)


def _smart_context_fit_check(
    text: str, *, model: str = "gpt-4", context_limit: int = 200000
) -> dict[str, Any]:
    from claude_bridge.smart import context_fit_check

    return context_fit_check(text, model=model, context_limit=context_limit)


def _smart_get_tool_recommendation(
    query: str, available_tools: list[str], context_budget: int
) -> dict[str, Any]:
    from claude_bridge.smart import get_tool_recommendation

    return get_tool_recommendation(query, available_tools, context_budget)


def _smart_estimate_context_savings(
    original_tokens: int, compact_tokens: int, overhead_tokens: int
) -> dict[str, Any]:
    from claude_bridge.smart import estimate_context_savings

    return estimate_context_savings(original_tokens, compact_tokens, overhead_tokens)


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
    onboarding_enabled: bool = True,
    ai_evaluator_enabled: bool = False,
    ai_evaluator_provider: str = "local",
    ai_evaluator_timeout: int = 5,
    ai_evaluator_fallback_action: str = "ask",
    auto_approve_patterns: dict[str, list[str]] | None = None,
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
        onboarding_enabled=onboarding_enabled,
        ai_evaluator_enabled=ai_evaluator_enabled,
        ai_evaluator_provider=ai_evaluator_provider,
        ai_evaluator_timeout=ai_evaluator_timeout,
        ai_evaluator_fallback_action=ai_evaluator_fallback_action,
        auto_approve_patterns=auto_approve_patterns,
    )
    from claude_bridge.indexing import clear_index_cache

    clear_index_cache()
    _clear_last_bridge_change()


def configure_from_env(*, force_auto_approve: bool | None = None) -> None:
    """Load runtime configuration from environment variables."""
    reset_audit_session()
    reset_onboarding_state()
    reset_process_sessions()
    configure_from_env_state(force_auto_approve=force_auto_approve)
    from claude_bridge.indexing import clear_index_cache

    clear_index_cache()
    _clear_last_bridge_change()


def _get_ai_provider() -> Any | None:
    cfg = raw_ai_evaluator_config()
    if not cfg["enabled"]:
        return None
    provider_name = cfg["provider"]
    try:
        from claude_bridge.ai_evaluator import create_provider

        return create_provider(
            provider_name,
            api_key=cfg["api_key"],
            model=cfg["model"],
            timeout=int(cfg["timeout"]),
        )
    except (ValueError, ImportError):
        return None


def _get_ai_router() -> Any:
    from claude_bridge.ai_router import AIModelRouter

    return AIModelRouter.from_config(current_config())


def _build_index(path: str) -> dict[str, Any]:
    from claude_bridge.indexing import build_index

    return build_index(
        path,
        resolve_path=_resolve_path,
        infer_project_root=_infer_project_root,
        is_within_root=_is_within_root,
    )


def _iter_source_files(root: Path, project_root: Path) -> list[Path]:
    from claude_bridge.indexing import iter_source_files

    return [p for p, _, _ in iter_source_files(root, project_root, is_within_root=_is_within_root)]


def _iter_searchable_files(
    root: Path, project_root: Path, include_glob: str | None = None
) -> list[Path]:
    from claude_bridge.indexing import iter_searchable_files

    return iter_searchable_files(
        root,
        project_root,
        is_within_root=_is_within_root,
        include_glob=include_glob,
    )


def clear_index_cache() -> None:
    from claude_bridge.indexing import clear_index_cache as _clear_index_cache

    _clear_index_cache()


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
    from claude_bridge.observability import get_metrics_collector
    from claude_bridge.tracing import trace_tool_call

    duration_ms = (time.perf_counter() - started_at) * 1000
    ok = _tool_result_ok(result)
    metrics = get_metrics_collector()
    metrics.increment("claude_bridge_tool_calls_total", labels={"tool": tool_name})
    metrics.increment(
        "claude_bridge_tool_call_results_total",
        labels={"tool": tool_name, "ok": str(ok).lower()},
    )
    metrics.observe("claude_bridge_tool_call_duration_ms", duration_ms, labels={"tool": tool_name})
    with trace_tool_call(tool_name, project_path=str(_project_dir())) as (_span, attrs):
        attrs.tool_result_ok = ok
        attrs.duration_ms = duration_ms
        enriched_result = _apply_onboarding(
            tool_name,
            result,
            enabled=bool(current_config().get("onboarding_enabled", True)),
        )
        _log_tool_call(
            tool_name,
            params,
            enriched_result,
            duration_ms=duration_ms,
        )
    return enriched_result


def _tool_result_ok(result: str) -> bool:
    try:
        payload = _json.loads(result)
    except _json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("ok", False))


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
    path_exists_impl=_file_path_exists,
    stat_file_impl=_file_stat_file,
    mkdir_impl=_file_mkdir,
    find_files_impl=_file_find_files,
    diff_files_impl=_file_diff_files,
    append_to_file_impl=_file_append_to_file,
    git_commit_fn=lambda *a, **kw: _git_commit(*a, **kw),
    request_approval_fn=lambda *a, **kw: _request_approval(*a, **kw),
    ai_provider_getter=_get_ai_provider,
    enabled_names=_ENABLED_TOOL_NAMES,
)
read_file = _tool_or_disabled(_FILE_TOOLS, "read_file")
read_multiple_files = _tool_or_disabled(_FILE_TOOLS, "read_multiple_files")
list_directory = _tool_or_disabled(_FILE_TOOLS, "list_directory")
write_file = _tool_or_disabled(_FILE_TOOLS, "write_file")
move_file = _tool_or_disabled(_FILE_TOOLS, "move_file")
copy_path = _tool_or_disabled(_FILE_TOOLS, "copy_path")
search_in_files = _tool_or_disabled(_FILE_TOOLS, "search_in_files")
patch_file = _tool_or_disabled(_FILE_TOOLS, "patch_file")
preview_patch = _tool_or_disabled(_FILE_TOOLS, "preview_patch")
undo_last_patch = _tool_or_disabled(_FILE_TOOLS, "undo_last_patch")
path_exists = _tool_or_disabled(_FILE_TOOLS, "path_exists")
stat_file = _tool_or_disabled(_FILE_TOOLS, "stat_file")
mkdir = _tool_or_disabled(_FILE_TOOLS, "mkdir")
find_files = _tool_or_disabled(_FILE_TOOLS, "find_files")
diff_files = _tool_or_disabled(_FILE_TOOLS, "diff_files")
append_to_file = _tool_or_disabled(_FILE_TOOLS, "append_to_file")


_MULTI_FORMAT_TOOLS = register_multi_format_tools(
    mcp=mcp,
    tool_options=_tool_options,
    audit_tool_call=_audit_tool_call,
    enabled_names=_ENABLED_TOOL_NAMES,
)
read_image = _tool_or_disabled(_MULTI_FORMAT_TOOLS, "read_image")
read_pdf = _tool_or_disabled(_MULTI_FORMAT_TOOLS, "read_pdf")

_URL_TOOLS = register_url_tools(
    mcp=mcp,
    tool_options=_tool_options,
    audit_tool_call=_audit_tool_call,
    enabled_names=_ENABLED_TOOL_NAMES,
)
read_url = _tool_or_disabled(_URL_TOOLS, "read_url")


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
    interactive_shell_impl=_interactive_shell_impl,
    send_to_process_impl=_send_to_process_impl,
    get_process_status_impl=_get_process_status_impl,
    request_approval=_request_approval,
    project_dir=_project_dir,
    shell_timeout=_shell_timeout,
    ai_provider_getter=_get_ai_provider,
    enabled_names=_ENABLED_TOOL_NAMES,
)
analyze_shell_command = _tool_or_disabled(_SHELL_TOOLS, "analyze_shell_command")
run_shell = _tool_or_disabled(_SHELL_TOOLS, "run_shell")
start_process = _tool_or_disabled(_SHELL_TOOLS, "start_process")
read_process_output = _tool_or_disabled(_SHELL_TOOLS, "read_process_output")
list_process_sessions = _tool_or_disabled(_SHELL_TOOLS, "list_process_sessions")
kill_process = _tool_or_disabled(_SHELL_TOOLS, "kill_process")
interact_with_process = _tool_or_disabled(_SHELL_TOOLS, "interact_with_process")
interactive_shell = _tool_or_disabled(_SHELL_TOOLS, "interactive_shell")
send_to_process = _tool_or_disabled(_SHELL_TOOLS, "send_to_process")
get_process_status = _tool_or_disabled(_SHELL_TOOLS, "get_process_status")
_is_interactive_command = _SHELL_TOOLS["_is_interactive_command"]
_normalize_command_for_safety = _SHELL_TOOLS["_normalize_command_for_safety"]
_blocked_command_reason = _SHELL_TOOLS["_blocked_command_reason"]


_INDEXING_TOOLS = register_indexing_tools(
    mcp=mcp,
    tool_options=_tool_options,
    audit_tool_call=_audit_tool_call,
    json_response=_json_response,
    build_index=lambda path: _build_index(path),
    path_outside_project_details=_path_outside_project_details,
    effective_budget_tokens=_effective_budget_tokens,
    smart_budget_metadata=_smart_budget_metadata,
    smart_estimate_token_count=_smart_estimate_token_count,
    enabled_names=_ENABLED_TOOL_NAMES,
)
index_codebase = _tool_or_disabled(_INDEXING_TOOLS, "index_codebase")
find_relevant_files = _tool_or_disabled(_INDEXING_TOOLS, "find_relevant_files")


if any(
    _should_register_tool(name)
    for name in {
        "run_agent_loop_step",
        "build_context_pack",
        "narrow_context",
        "suggest_validation_commands",
        "run_agent_loop_session",
        "run_workflow",
    }
):
    from claude_bridge.workflow_tool_server import register_workflow_tools
    from claude_bridge.workflow_tools import (
        build_context_pack as _build_context_pack_impl,
        build_validation_suggestions as _build_validation_suggestions_impl,
        run_agent_loop_session as _run_agent_loop_session_impl,
        run_agent_loop_step as _run_agent_loop_step_impl,
        run_workflow as _run_workflow_impl,
    )

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
        enabled_names=_ENABLED_TOOL_NAMES,
    )
else:
    _WORKFLOW_TOOLS = {}
run_agent_loop_step = _tool_or_disabled(_WORKFLOW_TOOLS, "run_agent_loop_step")
build_context_pack = _tool_or_disabled(_WORKFLOW_TOOLS, "build_context_pack")
narrow_context = _tool_or_disabled(_WORKFLOW_TOOLS, "narrow_context")
suggest_validation_commands = _tool_or_disabled(_WORKFLOW_TOOLS, "suggest_validation_commands")
run_agent_loop_session = _tool_or_disabled(_WORKFLOW_TOOLS, "run_agent_loop_session")
run_workflow = _tool_or_disabled(_WORKFLOW_TOOLS, "run_workflow")


if _should_register_tool("run_council_session"):
    from claude_bridge.council import run_council_session as _run_council_session_impl
    from claude_bridge.council_tool_server import register_council_tools

    _COUNCIL_TOOLS = register_council_tools(
        mcp=mcp,
        tool_options=_tool_options,
        audit_tool_call=_audit_tool_call,
        json_response=_json_response,
        run_council_session_impl=_run_council_session_impl,
        router_getter=_get_ai_router,
        enabled_names=_ENABLED_TOOL_NAMES,
    )
else:
    _COUNCIL_TOOLS = {}
run_council_session = _tool_or_disabled(_COUNCIL_TOOLS, "run_council_session")


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
    send_feedback_impl=send_feedback_impl,
    get_trust_score_impl=get_trust_score_impl,
    project_dir=_project_dir,
    allowed_roots=_allowed_roots,
    infer_project_root=_infer_project_root,
    set_active_project_dir=_set_active_project_dir,
    path_outside_project_details=_path_outside_project_details,
    reset_onboarding_state=reset_onboarding_state,
    prompt_shortcut_catalog=_prompt_shortcut_catalog,
    enabled_names=_ENABLED_TOOL_NAMES,
)
get_recent_tool_calls = _tool_or_disabled(_META_TOOLS, "get_recent_tool_calls")
advise_next_step = _tool_or_disabled(_META_TOOLS, "advise_next_step")
improve_request = _tool_or_disabled(_META_TOOLS, "improve_request")
plan_quality_review = _tool_or_disabled(_META_TOOLS, "plan_quality_review")
review_result_quality = _tool_or_disabled(_META_TOOLS, "review_result_quality")
suggest_bridge_config = _tool_or_disabled(_META_TOOLS, "suggest_bridge_config")
apply_bridge_config_change = _tool_or_disabled(_META_TOOLS, "apply_bridge_config_change")
session_insights = _tool_or_disabled(_META_TOOLS, "session_insights")
activity_summary = _tool_or_disabled(_META_TOOLS, "activity_summary")
usage_insights = _tool_or_disabled(_META_TOOLS, "usage_insights")
compress_context = _tool_or_disabled(_META_TOOLS, "compress_context")
bridge_status = _tool_or_disabled(_META_TOOLS, "bridge_status")
tools_overview = _tool_or_disabled(_META_TOOLS, "tools_overview")
get_config = _tool_or_disabled(_META_TOOLS, "get_config")
set_config_value = _tool_or_disabled(_META_TOOLS, "set_config_value")
compact_user_intent = _tool_or_disabled(_META_TOOLS, "compact_user_intent")
workspace_status = _tool_or_disabled(_META_TOOLS, "workspace_status")
switch_project_root = _tool_or_disabled(_META_TOOLS, "switch_project_root")
prompt_shortcuts = _tool_or_disabled(_META_TOOLS, "prompt_shortcuts")
appeal_decision = _tool_or_disabled(_META_TOOLS, "appeal_decision")
send_feedback = _tool_or_disabled(_META_TOOLS, "send_feedback")
anomaly_summary = _tool_or_disabled(_META_TOOLS, "anomaly_summary")
generate_pr_description = _tool_or_disabled(_META_TOOLS, "generate_pr_description")
get_trust_score = _tool_or_disabled(_META_TOOLS, "get_trust_score")


_CONTROL_PLANE_TOOLS = register_control_plane_tools(
    mcp=mcp,
    tool_options=_tool_options,
    audit_tool_call=_audit_tool_call,
    json_response=_json_response,
    enabled_names=_ENABLED_TOOL_NAMES,
)
list_tasks = _tool_or_disabled(_CONTROL_PLANE_TOOLS, "list_tasks")
task_status = _tool_or_disabled(_CONTROL_PLANE_TOOLS, "task_status")
task_summary = _tool_or_disabled(_CONTROL_PLANE_TOOLS, "task_summary")
list_pending_approvals = _tool_or_disabled(_CONTROL_PLANE_TOOLS, "list_pending_approvals")
approve_pending_action = _tool_or_disabled(_CONTROL_PLANE_TOOLS, "approve_pending_action")
reject_pending_action = _tool_or_disabled(_CONTROL_PLANE_TOOLS, "reject_pending_action")
list_user_messages = _tool_or_disabled(_CONTROL_PLANE_TOOLS, "list_user_messages")
ack_user_message = _tool_or_disabled(_CONTROL_PLANE_TOOLS, "ack_user_message")
complete_user_message = _tool_or_disabled(_CONTROL_PLANE_TOOLS, "complete_user_message")
autocomplete = _tool_or_disabled(_META_TOOLS, "autocomplete")

if any(
    _should_register_tool(name)
    for name in {
        "list_skills",
        "inspect_skill",
        "recommend_skills",
        "inspect_skill_package",
        "run_skill",
    }
):
    from claude_bridge.skill_tool_server import register_skill_tools

    _SKILL_TOOLS = register_skill_tools(
        mcp=mcp,
        tool_options=_tool_options,
        audit_tool_call=_audit_tool_call,
        json_response=_json_response,
        resolve_path=_resolve_path,
        project_dir=_project_dir,
        enabled_names=_ENABLED_TOOL_NAMES,
    )
else:
    _SKILL_TOOLS = {}
list_skills = _tool_or_disabled(_SKILL_TOOLS, "list_skills")
inspect_skill = _tool_or_disabled(_SKILL_TOOLS, "inspect_skill")
recommend_skills = _tool_or_disabled(_SKILL_TOOLS, "recommend_skills")
inspect_skill_package = _tool_or_disabled(_SKILL_TOOLS, "inspect_skill_package")
run_skill = _tool_or_disabled(_SKILL_TOOLS, "run_skill")

if any(
    _should_register_tool(name)
    for name in {
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
    }
):
    from claude_bridge.approach_explorer import (
        compare_approaches as _compare_approaches_impl,
        execute_approach as _execute_approach_impl,
        explore_approaches as _explore_approaches_impl,
    )
    from claude_bridge.checkpoint import (
        create_checkpoint as _create_checkpoint_impl,
        list_checkpoints as _list_checkpoints_impl,
        restore_checkpoint as _restore_checkpoint_impl,
    )
    from claude_bridge.meta_agent_server import register_meta_agent_tools
    from claude_bridge.plan_engine import (
        create_plan as _create_plan_impl,
        execute_step as _execute_step_impl,
        get_plan_status as _get_plan_status_impl,
    )
    from claude_bridge.self_critique import self_critique as _self_critique_impl

    _META_AGENT_TOOLS = register_meta_agent_tools(
        mcp=mcp,
        tool_options=_tool_options,
        audit_tool_call=_audit_tool_call,
        json_response=_json_response,
        create_plan_impl=_create_plan_impl,
        execute_step_impl=_execute_step_impl,
        get_plan_status_impl=_get_plan_status_impl,
        explore_approaches_impl=_explore_approaches_impl,
        execute_approach_impl=_execute_approach_impl,
        compare_approaches_impl=_compare_approaches_impl,
        self_critique_impl=_self_critique_impl,
        create_checkpoint_impl=_create_checkpoint_impl,
        restore_checkpoint_impl=_restore_checkpoint_impl,
        list_checkpoints_impl=_list_checkpoints_impl,
        get_recent_tool_calls_impl=_get_recent_tool_calls_impl,
        enabled_names=_ENABLED_TOOL_NAMES,
    )
else:
    _META_AGENT_TOOLS = {}
create_plan = _tool_or_disabled(_META_AGENT_TOOLS, "create_plan")
execute_step = _tool_or_disabled(_META_AGENT_TOOLS, "execute_step")
get_plan_status = _tool_or_disabled(_META_AGENT_TOOLS, "get_plan_status")
explore_approaches = _tool_or_disabled(_META_AGENT_TOOLS, "explore_approaches")
execute_approach = _tool_or_disabled(_META_AGENT_TOOLS, "execute_approach")
compare_approaches = _tool_or_disabled(_META_AGENT_TOOLS, "compare_approaches")
self_critique = _tool_or_disabled(_META_AGENT_TOOLS, "self_critique")
create_checkpoint = _tool_or_disabled(_META_AGENT_TOOLS, "create_checkpoint")
restore_checkpoint = _tool_or_disabled(_META_AGENT_TOOLS, "restore_checkpoint")
list_checkpoints = _tool_or_disabled(_META_AGENT_TOOLS, "list_checkpoints")

if any(
    _should_register_tool(name) for name in {"count_file_tokens", "context_fit", "smart_status"}
):
    from claude_bridge.smart_tool_registration import register_smart_tools

    _SMART_TOOLS = register_smart_tools(
        mcp=mcp,
        tool_options=_tool_options,
        audit_tool_call=_audit_tool_call,
        resolve_path=_resolve_path,
        json_response=_json_response,
        count_tokens_for_path=_smart_count_tokens_for_path,
        context_fit_check=_smart_context_fit_check,
        smart_available=_smart_available,
        get_tool_recommendation=_smart_get_tool_recommendation,
        estimate_context_savings=_smart_estimate_context_savings,
        enabled_names=_ENABLED_TOOL_NAMES,
    )
else:
    _SMART_TOOLS = {}
count_file_tokens = _tool_or_disabled(_SMART_TOOLS, "count_file_tokens")
context_fit = _tool_or_disabled(_SMART_TOOLS, "context_fit")
smart_status = _tool_or_disabled(_SMART_TOOLS, "smart_status")

if any(
    _should_register_tool(name)
    for name in {
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
    }
):
    from claude_bridge.insights import (
        dependency_map as _insights_dependency_map,
        duplicate_code_scan as _insights_duplicate_code_scan,
        git_diff_summary as _insights_git_diff_summary,
        git_log_summary as _insights_git_log_summary,
        language_distribution as _insights_language_distribution,
        project_stats as _insights_project_stats,
        read_notes as _insights_read_notes,
        recent_files as _insights_recent_files,
        save_note as _insights_save_note,
        todo_scan as _insights_todo_scan,
    )
    from claude_bridge.insights_tool_registration import register_insights_tools

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
        enabled_names=_ENABLED_TOOL_NAMES,
    )
else:
    _INSIGHTS_TOOLS = {}
project_insights = _tool_or_disabled(_INSIGHTS_TOOLS, "project_insights")
todo_scan = _tool_or_disabled(_INSIGHTS_TOOLS, "todo_scan")
recent_files = _tool_or_disabled(_INSIGHTS_TOOLS, "recent_files")
language_distribution = _tool_or_disabled(_INSIGHTS_TOOLS, "language_distribution")
git_insights = _tool_or_disabled(_INSIGHTS_TOOLS, "git_insights")
git_diff_insights = _tool_or_disabled(_INSIGHTS_TOOLS, "git_diff_insights")
duplicate_code_scan = _tool_or_disabled(_INSIGHTS_TOOLS, "duplicate_code_scan")
dependency_insights = _tool_or_disabled(_INSIGHTS_TOOLS, "dependency_insights")
bridge_save_note = _tool_or_disabled(_INSIGHTS_TOOLS, "bridge_save_note")
bridge_read_notes = _tool_or_disabled(_INSIGHTS_TOOLS, "bridge_read_notes")


_GIT_TOOLS = register_git_tools(
    mcp=mcp,
    tool_options=_tool_options,
    audit_tool_call=_audit_tool_call,
    json_response=_json_response,
    project_dir=_project_dir,
    git_diff_impl=git_diff,
    git_log_impl=git_log,
    enabled_names=_ENABLED_TOOL_NAMES,
)
commit_changes = _tool_or_disabled(_GIT_TOOLS, "commit_changes")
git_diff = _tool_or_disabled(_GIT_TOOLS, "git_diff")
git_log = _tool_or_disabled(_GIT_TOOLS, "git_log")


_NOTIFICATION_TOOLS = register_notification_tools(
    mcp=mcp,
    tool_options=_tool_options,
    audit_tool_call=_audit_tool_call,
    json_response=_json_response,
    enabled_names=_ENABLED_TOOL_NAMES,
)
stream_subscribe = _tool_or_disabled(_NOTIFICATION_TOOLS, "stream_subscribe")
get_recent_events = _tool_or_disabled(_NOTIFICATION_TOOLS, "get_recent_events")
get_stream_capabilities = _tool_or_disabled(_NOTIFICATION_TOOLS, "get_stream_capabilities")
emit_progress_event = _tool_or_disabled(_NOTIFICATION_TOOLS, "emit_progress_event")


def run_mcp_server() -> None:
    """Run the Claude Bridge MCP server over stdio."""
    _register_prompts_once()
    mcp.run(transport="stdio")


_prompts_registered = False
_PROMPTS_REGISTERED_LOCK = threading.Lock()


def _register_prompts_once() -> None:
    global _prompts_registered
    with _PROMPTS_REGISTERED_LOCK:
        if _prompts_registered:
            return
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
        _prompts_registered = True
