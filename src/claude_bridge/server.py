"""MCP server implementation for Claude Bridge."""

from __future__ import annotations

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
)
from claude_bridge.config import (
    APPROVAL_PRESETS,
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
from claude_bridge.tool_utils import (
    set_active_project_dir as _set_active_project_dir,
)
from claude_bridge.workflow_tools import (
    build_context_pack as _build_context_pack_impl,
)
from claude_bridge.workflow_tools import (
    build_validation_suggestions as _build_validation_suggestions_impl,
)
from claude_bridge.workflow_tools import (
    register_prompts as _register_prompts_impl,
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


@mcp.tool(
    **_tool_options(
        "Read a file inside the configured workspace. Use this after you know which file matters. "
        "Prefer targeted reads over broad exploration, and expect large files to be truncated for context safety.",
        read_only=True,
    )
)
async def read_file(path: str, offset: int = 0, limit: int = 200) -> str:
    started_at = time.perf_counter()
    result = await _file_read_file(path, offset=offset, limit=limit)
    return _audit_tool_call(
        "read_file",
        {"path": path, "offset": offset, "limit": limit},
        result,
        started_at=started_at,
    )


@mcp.tool(
    **_tool_options(
        "Read multiple files at once. Use this when you need to compare or cross-reference a small set of files more efficiently than repeated read_file calls.",
        read_only=True,
    )
)
async def read_multiple_files(paths: list[str], offset: int = 0, limit: int = 200) -> str:
    started_at = time.perf_counter()
    result = await _file_read_multiple_files(paths, offset=offset, limit=limit)
    return _audit_tool_call(
        "read_multiple_files",
        {"paths": paths, "offset": offset, "limit": limit},
        result,
        started_at=started_at,
    )


@mcp.tool(
    **_tool_options(
        "List a directory inside the configured workspace. Use this first to understand structure before reading or editing files. "
        "Prefer narrow paths over listing the whole repository.",
        read_only=True,
    )
)
async def list_directory(path: str = ".") -> str:
    started_at = time.perf_counter()
    result = await _file_list_directory(path)
    return _audit_tool_call("list_directory", {"path": path}, result, started_at=started_at)


@mcp.tool(
    **_tool_options(
        "Write a new file or overwrite an existing one with approval. Prefer this for creating new files. "
        "For existing files, prefer patch_file so edits stay small, auditable, and easier to validate.",
        destructive=True,
    )
)
async def write_file(
    path: str,
    content: str,
    overwrite: bool = False,
    create_parents: bool = False,
) -> str:
    started_at = time.perf_counter()
    result = await _file_write_file(
        path,
        content,
        overwrite=overwrite,
        create_parents=create_parents,
        git_commit_fn=_git_commit,
    )
    return _audit_tool_call(
        "write_file",
        {
            "path": path,
            "content": content,
            "overwrite": overwrite,
            "create_parents": create_parents,
        },
        result,
        started_at=started_at,
    )


@mcp.tool(
    **_tool_options(
        "Search text across project files without dropping to shell. Use this to narrow the candidate files before reading them. "
        "Prefer this over broad shell grep commands when exploring code. Use offset and limit to page through large result sets.",
        read_only=True,
    )
)
async def search_in_files(
    query: str,
    path: str = ".",
    regex: bool = False,
    case_sensitive: bool = False,
    include_glob: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> str:
    started_at = time.perf_counter()
    result = await _file_search_in_files(
        query,
        path=path,
        regex=regex,
        case_sensitive=case_sensitive,
        include_glob=include_glob,
        offset=offset,
        limit=limit,
    )
    return _audit_tool_call(
        "search_in_files",
        {
            "query": query,
            "path": path,
            "regex": regex,
            "case_sensitive": case_sensitive,
            "include_glob": include_glob,
            "offset": offset,
            "limit": limit,
        },
        result,
        started_at=started_at,
    )


def _is_interactive_command(command: str) -> bool:
    return _analyze_shell_command_impl(command).get("code") == "interactive_command_unsupported"


def _normalize_command_for_safety(command: str) -> str:
    details = _analyze_shell_command_impl(command).get("details", {})
    return str(details.get("normalized_command", command.strip().lower()))


def _blocked_command_reason(stripped: str, tokens: list[str]) -> str | None:
    analysis = _analyze_shell_command_impl(stripped)
    if analysis.get("code") == "blocked_command":
        details = analysis.get("details", {})
        if isinstance(details, dict):
            blocked_pattern = details.get("blocked_pattern")
            return blocked_pattern if isinstance(blocked_pattern, str) else None
    return None


@mcp.tool(
    **_tool_options(
        "Analyze a shell command without executing it. Use this before risky commands or when you need to explain command risk to the user.",
        read_only=True,
    )
)
async def analyze_shell_command(command: str) -> str:
    started_at = time.perf_counter()
    analysis = _analyze_shell_command_impl(command)
    result = _json_response(
        analysis["ok"],
        analysis["message"],
        code=analysis.get("code"),
        details=analysis["details"],
    )
    return _audit_tool_call(
        "analyze_shell_command", {"command": command}, result, started_at=started_at
    )


@mcp.tool(
    **_tool_options(
        "Run a non-interactive shell command with approval. Prefer read-only or validation commands such as pytest, ruff, git status, or ls. "
        "Never use this to bypass file tools, and inspect failures before retrying with a different command.",
        destructive=True,
        open_world=True,
    )
)
async def run_shell(command: str) -> str:
    started_at = time.perf_counter()
    result = await _run_shell_impl(
        command,
        request_approval=_request_approval,
        project_dir=_project_dir,
        shell_timeout=_shell_timeout,
    )
    return _audit_tool_call("run_shell", {"command": command}, result, started_at=started_at)


@mcp.tool(
    **_tool_options(
        "Start a long-running non-interactive process with approval. Use this for watchers, dev servers, or commands that may exceed run_shell timeout.",
        destructive=True,
        open_world=True,
    )
)
async def start_process(command: str) -> str:
    started_at = time.perf_counter()
    result = await _start_process_impl(
        command,
        request_approval=_request_approval,
        project_dir=_project_dir,
    )
    return _audit_tool_call("start_process", {"command": command}, result, started_at=started_at)


@mcp.tool(
    **_tool_options(
        "Read paginated output from a previously started process session. Use offset and limit to fetch the next output window without rerunning the command.",
        read_only=True,
    )
)
async def read_process_output(session_id: str, offset: int = 0, limit: int = 4000) -> str:
    started_at = time.perf_counter()
    result = await _read_process_output_impl(session_id=session_id, offset=offset, limit=limit)
    return _audit_tool_call(
        "read_process_output",
        {"session_id": session_id, "offset": offset, "limit": limit},
        result,
        started_at=started_at,
    )


@mcp.tool(
    **_tool_options(
        "List active and recent process sessions started by Claude Bridge. Use this to find session ids before reading output or terminating a process.",
        read_only=True,
    )
)
async def list_process_sessions() -> str:
    started_at = time.perf_counter()
    result = await _list_process_sessions_impl()
    return _audit_tool_call("list_process_sessions", {}, result, started_at=started_at)


@mcp.tool(
    **_tool_options(
        "Terminate a Claude Bridge managed process session by id. Use this to stop a watcher or server that you started earlier.",
        destructive=True,
    )
)
async def kill_process(session_id: str) -> str:
    started_at = time.perf_counter()
    result = await _kill_process_impl(session_id=session_id, request_approval=_request_approval)
    return _audit_tool_call(
        "kill_process", {"session_id": session_id}, result, started_at=started_at
    )


@mcp.tool(
    **_tool_options(
        "Send input to a running process session. Use this to interact with long-running processes such as REPLs, servers, or piped commands.",
        destructive=True,
        open_world=True,
    )
)
async def interact_with_process(session_id: str, input: str) -> str:
    started_at = time.perf_counter()
    result = await _interact_with_process_impl(
        session_id=session_id,
        input=input,
        request_approval=_request_approval,
    )
    return _audit_tool_call(
        "interact_with_process",
        {"session_id": session_id, "input_length": len(input)},
        result,
        started_at=started_at,
    )


@mcp.tool(
    **_tool_options(
        "Apply a targeted SEARCH/REPLACE patch to an existing file. Prefer this over write_file for edits. "
        "Keep SEARCH text small but unique so the replacement is deterministic and easy to review.",
        destructive=True,
    )
)
async def patch_file(file: str, search: str, replace: str) -> str:
    started_at = time.perf_counter()
    result = await _file_patch_file(file, search, replace, git_commit_fn=_git_commit)
    return _audit_tool_call(
        "patch_file",
        {"file": file, "search": search, "replace": replace},
        result,
        started_at=started_at,
    )


@mcp.tool(
    **_tool_options(
        "Preview a SEARCH/REPLACE patch without changing the file. Use this before applying non-trivial edits or when you need to explain risk.",
        read_only=True,
    )
)
async def preview_patch(file: str, search: str, replace: str) -> str:
    started_at = time.perf_counter()
    result = await _file_preview_patch(file, search, replace)
    return _audit_tool_call(
        "preview_patch",
        {"file": file, "search": search, "replace": replace},
        result,
        started_at=started_at,
    )


@mcp.tool(
    **_tool_options(
        "Undo the last Claude Bridge managed file change using the stored snapshot. Use this only when the last Bridge action should be reverted.",
        destructive=True,
    )
)
async def undo_last_patch(confirm: bool = False) -> str:
    started_at = time.perf_counter()
    result = await _file_undo_last_patch(
        confirm=confirm,
        request_approval_fn=_request_approval,
        git_commit_fn=_git_commit,
    )
    return _audit_tool_call("undo_last_patch", {"confirm": confirm}, result, started_at=started_at)


@mcp.tool(
    **_tool_options(
        "Run one bounded agent-loop step: patch once, validate once, then decide. Use this for small corrective loops, not broad refactors.",
        destructive=True,
    )
)
async def run_agent_loop_step(
    file: str,
    search: str,
    replace: str,
    validation_command: str,
    iteration: int = 1,
    max_iterations: int = 3,
) -> str:
    started_at = time.perf_counter()
    result = await _run_agent_loop_step_impl(
        file=file,
        search=search,
        replace=replace,
        validation_command=validation_command,
        iteration=iteration,
        max_iterations=max_iterations,
        patch_file=patch_file,
        run_shell=run_shell,
        json_response=_json_response,
    )
    return _audit_tool_call(
        "run_agent_loop_step",
        {
            "file": file,
            "search": search,
            "replace": replace,
            "validation_command": validation_command,
            "iteration": iteration,
            "max_iterations": max_iterations,
        },
        result,
        started_at=started_at,
    )


@mcp.tool(
    **_tool_options(
        "Build a framework-aware context pack for a target and goal. Use this before deep analysis to gather focused files, tests, and docs.",
        read_only=True,
    )
)
async def build_context_pack(
    target: str = ".",
    goal: str = "understand the current task",
    max_files: int = 8,
    include_tests: bool = True,
    include_git_diff: bool = True,
    include_docs: bool = True,
) -> str:
    started_at = time.perf_counter()
    result = await _build_context_pack_impl(
        target=target,
        goal=goal,
        max_files=max_files,
        include_tests=include_tests,
        include_git_diff=include_git_diff,
        include_docs=include_docs,
        resolve_path=_resolve_path,
        find_relevant_files=find_relevant_files,
        path_from_active_root=_path_from_active_root,
        project_dir=_project_dir,
        infer_project_root=_infer_project_root,
        iter_searchable_files=_iter_searchable_files,
        git_status_snapshot=_git_status_snapshot,
        json_response=_json_response,
    )
    return _audit_tool_call(
        "build_context_pack",
        {
            "target": target,
            "goal": goal,
            "max_files": max_files,
            "include_tests": include_tests,
            "include_git_diff": include_git_diff,
            "include_docs": include_docs,
        },
        result,
        started_at=started_at,
    )


@mcp.tool(
    **_tool_options(
        "Suggest framework-aware validation commands for a target. Use this before or after edits when you need likely tests, lint, or build commands.",
        read_only=True,
    )
)
async def suggest_validation_commands(target: str = ".") -> str:
    started_at = time.perf_counter()
    result = await _build_validation_suggestions_impl(
        target=target,
        resolve_path=_resolve_path,
        infer_project_root=_infer_project_root,
        json_response=_json_response,
    )
    return _audit_tool_call(
        "suggest_validation_commands", {"target": target}, result, started_at=started_at
    )


@mcp.tool(
    **_tool_options(
        "Run a bounded multi-step agent-loop session from a planned JSON step list. Prefer short, reviewable sequences with clear validation steps.",
        destructive=True,
    )
)
async def run_agent_loop_session(
    steps_json: str | None = None,
    steps: list[dict[str, Any]] | None = None,
    max_iterations: int = 3,
    compact_threshold: int = 4,
    keep_recent_results: int = 2,
) -> str:
    started_at = time.perf_counter()
    result = await _run_agent_loop_session_impl(
        steps_json=steps_json,
        steps=steps,
        max_iterations=max_iterations,
        compact_threshold=compact_threshold,
        keep_recent_results=keep_recent_results,
        run_agent_loop_step=run_agent_loop_step,
        json_response=_json_response,
    )
    return _audit_tool_call(
        "run_agent_loop_session",
        {
            "steps_json": steps_json,
            "steps": steps,
            "max_iterations": max_iterations,
            "compact_threshold": compact_threshold,
            "keep_recent_results": keep_recent_results,
        },
        result,
        started_at=started_at,
    )


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
async def find_relevant_files(query: str, path: str = ".", limit: int = 5) -> str:
    started_at = time.perf_counter()
    audit_params = {"query": query, "path": path, "limit": limit}
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
        },
    )
    return _audit_tool_call("find_relevant_files", audit_params, result, started_at=started_at)


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
            "editable_keys": [
                "approval_preset",
                "auto_approve",
                "client_managed_approval",
                "shell_timeout",
                "onboarding_enabled",
            ],
        },
    )
    return _audit_tool_call("get_config", {}, result, started_at=started_at)


@mcp.tool(
    **_tool_options(
        "Update a limited Claude Bridge runtime configuration value. Supported keys are approval_preset, auto_approve, client_managed_approval, and shell_timeout.",
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
        "Generate a workflow prompt and optional safe first step. Use this to structure review, optimize, test, or explain tasks before making changes.",
        read_only=True,
    )
)
async def run_workflow(
    mode: str,
    target: str = ".",
    option: str | None = None,
    language: str = "Turkish",
    execute: bool = False,
    max_iterations: int = 3,
) -> str:
    started_at = time.perf_counter()
    result = await _run_workflow_impl(
        mode=mode,
        target=target,
        option=option,
        language=language,
        execute=execute,
        max_iterations=max_iterations,
        resolve_path=_resolve_path,
        read_file=read_file,
        list_directory=list_directory,
        find_relevant_files=find_relevant_files,
        path_from_active_root=_path_from_active_root,
        project_dir=_project_dir,
        infer_project_root=_infer_project_root,
        json_response=_json_response,
    )
    return _audit_tool_call(
        "run_workflow",
        {
            "mode": mode,
            "target": target,
            "option": option,
            "language": language,
            "execute": execute,
            "max_iterations": max_iterations,
        },
        result,
        started_at=started_at,
    )


def _register_prompts() -> None:
    _register_prompts_impl(mcp)


def run_mcp_server() -> None:
    """Run the Claude Bridge MCP server over stdio."""
    mcp.run(transport="stdio")


_register_prompts()
