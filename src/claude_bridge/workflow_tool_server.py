"""Registration helpers for workflow and agent-loop MCP tools."""

from __future__ import annotations

import json as _json
import time
from typing import Any, Callable


def register_workflow_tools(
    *,
    mcp: Any,
    tool_options: Callable[..., dict[str, Any]],
    audit_tool_call: Callable[..., str],
    json_response: Callable[..., str],
    # Workflow implementations (from workflow_tools.py)
    run_agent_loop_step_impl: Any,
    build_context_pack_impl: Any,
    build_validation_suggestions_impl: Any,
    run_agent_loop_session_impl: Any,
    run_workflow_impl: Any,
    # Cross-tool references (wrapped MCP tools from other registrations).
    # These are passed as zero-argument getter callables so that tests can
    # monkeypatch the module-level names at runtime.
    patch_file_getter: Callable[[], Any],
    run_shell_getter: Callable[[], Any],
    read_file_getter: Callable[[], Any],
    list_directory_getter: Callable[[], Any],
    find_relevant_files_getter: Callable[[], Any],
    # Utility helpers
    resolve_path: Any,
    path_from_active_root: Any,
    project_dir: Any,
    infer_project_root: Any,
    iter_searchable_files: Any,
    git_status_snapshot: Any,
    effective_budget_tokens: Any,
    safe_json_object_load: Any,
    smart_budget_metadata: Any,
) -> dict[str, Any]:
    """Register all workflow/agent-loop MCP tools and return a dict of callables."""

    @mcp.tool(
        **tool_options(
            "Run one bounded agent-loop step: patch once, validate once, then decide. "
            "Use this for small corrective loops, not broad refactors.",
            destructive=True,
        )
    )
    async def _run_agent_loop_step(
        file: str,
        search: str,
        replace: str,
        validation_command: str,
        iteration: int = 1,
        max_iterations: int = 3,
    ) -> str:
        started_at = time.perf_counter()
        result = await run_agent_loop_step_impl(
            file=file,
            search=search,
            replace=replace,
            validation_command=validation_command,
            iteration=iteration,
            max_iterations=max_iterations,
            patch_file=patch_file_getter(),
            run_shell=run_shell_getter(),
            json_response=json_response,
        )
        return audit_tool_call(
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
        **tool_options(
            "Build a framework-aware context pack for a target and goal. "
            "Use this before deep analysis to gather focused files, tests, and docs.",
            read_only=True,
        )
    )
    async def _build_context_pack(
        target: str = ".",
        goal: str = "understand the current task",
        max_files: int = 8,
        include_tests: bool = True,
        include_git_diff: bool = True,
        include_docs: bool = True,
        budget_tokens: int | None = None,
    ) -> str:
        bt = budget_tokens if budget_tokens is not None else effective_budget_tokens()
        started_at = time.perf_counter()
        result = await build_context_pack_impl(
            target=target,
            goal=goal,
            max_files=max_files,
            include_tests=include_tests,
            include_git_diff=include_git_diff,
            include_docs=include_docs,
            budget_tokens=bt,
            resolve_path=resolve_path,
            find_relevant_files=find_relevant_files_getter(),
            path_from_active_root=path_from_active_root,
            project_dir=project_dir,
            infer_project_root=infer_project_root,
            iter_searchable_files=iter_searchable_files,
            git_status_snapshot=git_status_snapshot,
            json_response=json_response,
        )
        return audit_tool_call(
            "build_context_pack",
            {
                "target": target,
                "goal": goal,
                "max_files": max_files,
                "include_tests": include_tests,
                "include_git_diff": include_git_diff,
                "include_docs": include_docs,
                "budget_tokens": bt,
            },
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Build a budget-aware narrow context plan for a goal. "
            "Use this when you want the smallest useful set of files "
            "before deeper reading.",
            read_only=True,
        )
    )
    async def _narrow_context(
        goal: str,
        target: str = ".",
        budget_tokens: int | None = None,
        max_files: int = 8,
        include_tests: bool = True,
        include_docs: bool = True,
    ) -> str:
        bt = budget_tokens if budget_tokens is not None else effective_budget_tokens()
        started_at = time.perf_counter()
        if bt < 1:
            result = json_response(
                False,
                "budget_tokens must be at least 1",
                code="invalid_budget_tokens",
                details={"budget_tokens": bt},
            )
            return audit_tool_call(
                "narrow_context",
                {
                    "goal": goal,
                    "target": target,
                    "budget_tokens": bt,
                    "max_files": max_files,
                    "include_tests": include_tests,
                    "include_docs": include_docs,
                },
                result,
                started_at=started_at,
            )

        audit_params = {
            "goal": goal,
            "target": target,
            "budget_tokens": bt,
            "max_files": max_files,
            "include_tests": include_tests,
            "include_docs": include_docs,
        }

        context_pack = await build_context_pack_impl(
            target=target,
            goal=goal,
            max_files=max_files,
            include_tests=include_tests,
            include_git_diff=False,
            include_docs=include_docs,
            budget_tokens=bt,
            resolve_path=resolve_path,
            find_relevant_files=find_relevant_files_getter(),
            path_from_active_root=path_from_active_root,
            project_dir=project_dir,
            infer_project_root=infer_project_root,
            iter_searchable_files=iter_searchable_files,
            git_status_snapshot=git_status_snapshot,
            json_response=json_response,
        )
        payload, parse_error = safe_json_object_load(context_pack)
        if parse_error is not None:
            result = json_response(
                False,
                parse_error["message"],
                code=parse_error["code"],
                details=parse_error["details"],
            )
            return audit_tool_call("narrow_context", audit_params, result, started_at=started_at)
        if payload is None:
            result = json_response(
                False,
                "Context pack returned no payload",
                code="invalid_context_pack",
                details={"target": target},
            )
            return audit_tool_call("narrow_context", audit_params, result, started_at=started_at)
        if not payload.get("ok", False):
            return audit_tool_call(
                "narrow_context",
                audit_params,
                context_pack,
                started_at=started_at,
            )

        details = payload.get("details", {}) if isinstance(payload, dict) else {}
        file_estimates = (
            list(details.get("file_estimates", [])) if isinstance(details, dict) else []
        )
        chosen: list[dict[str, Any]] = []
        omitted: list[dict[str, Any]] = []
        running_total = 0
        for item in file_estimates:
            estimated_tokens = int(item.get("estimated_tokens", 0))
            if running_total + estimated_tokens > bt:
                omitted.append(item)
                continue
            chosen.append(item)
            running_total += estimated_tokens

        result = json_response(
            True,
            f"Narrow context prepared for {target}",
            details={
                "target": target,
                "goal": goal,
                "selected_files": [item["path"] for item in chosen],
                "selected_file_estimates": chosen,
                "omitted_files": [item["path"] for item in omitted],
                "omitted_file_estimates": omitted,
                "source_context_pack_files": details.get("selected_files", []),
                "project_type": details.get("project_type"),
                "next_recommended_tools": [
                    "read_file",
                    "read_multiple_files",
                    "build_context_pack",
                ],
                **smart_budget_metadata(
                    estimated_tokens=running_total,
                    budget_tokens=bt,
                    recommended_next_step=(
                        "Read the selected files first; if they are insufficient, "
                        "raise budget_tokens or ask for a narrower goal."
                    ),
                ),
            },
        )
        return audit_tool_call("narrow_context", audit_params, result, started_at=started_at)

    @mcp.tool(
        **tool_options(
            "Suggest framework-aware validation commands for a target. "
            "Use this before or after edits when you need likely tests, lint, "
            "or build commands.",
            read_only=True,
        )
    )
    async def _suggest_validation_commands(target: str = ".") -> str:
        started_at = time.perf_counter()
        result = await build_validation_suggestions_impl(
            target=target,
            resolve_path=resolve_path,
            infer_project_root=infer_project_root,
            json_response=json_response,
        )
        return audit_tool_call(
            "suggest_validation_commands",
            {"target": target},
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Run a bounded multi-step agent-loop session from a planned JSON "
            "step list. Prefer short, reviewable sequences with clear "
            "validation steps.",
            destructive=True,
        )
    )
    async def _run_agent_loop_session(
        steps_json: str | None = None,
        steps: list[dict[str, Any]] | None = None,
        max_iterations: int = 3,
        compact_threshold: int = 4,
        keep_recent_results: int = 2,
    ) -> str:
        started_at = time.perf_counter()
        result = await run_agent_loop_session_impl(
            steps_json=steps_json,
            steps=steps,
            max_iterations=max_iterations,
            compact_threshold=compact_threshold,
            keep_recent_results=keep_recent_results,
            run_agent_loop_step=_run_agent_loop_step,
            json_response=json_response,
        )
        return audit_tool_call(
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
        **tool_options(
            "Generate a workflow prompt and optional safe first step. "
            "Use this to structure review, optimize, test, or explain tasks "
            "before making changes.",
            read_only=True,
        )
    )
    async def _run_workflow(
        mode: str,
        target: str = ".",
        option: str | None = None,
        language: str = "Turkish",
        execute: bool = False,
        max_iterations: int = 3,
    ) -> str:
        started_at = time.perf_counter()
        result = await run_workflow_impl(
            mode=mode,
            target=target,
            option=option,
            language=language,
            execute=execute,
            max_iterations=max_iterations,
            resolve_path=resolve_path,
            read_file=read_file_getter(),
            list_directory=list_directory_getter(),
            find_relevant_files=find_relevant_files_getter(),
            path_from_active_root=path_from_active_root,
            project_dir=project_dir,
            infer_project_root=infer_project_root,
            json_response=json_response,
        )
        try:
            payload = _json.loads(result)
        except _json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and payload.get("ok") is True:
            details = payload.get("details")
            if isinstance(details, dict):
                details["prompt_entrypoint"] = mode
                details["low_token_hint"] = (
                    "Prefer the matching MCP prompt/slash entrypoint "
                    "when the client exposes prompts directly."
                )
                result = _json.dumps(payload, ensure_ascii=False)
        return audit_tool_call(
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

    return {
        "run_agent_loop_step": _run_agent_loop_step,
        "build_context_pack": _build_context_pack,
        "narrow_context": _narrow_context,
        "suggest_validation_commands": _suggest_validation_commands,
        "run_agent_loop_session": _run_agent_loop_session,
        "run_workflow": _run_workflow,
    }
