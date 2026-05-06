"""Registration helpers for workflow and agent-loop MCP tools."""

from __future__ import annotations

from typing import Any, Callable

from claude_bridge.tool_registration import ToolRegistrationContext


def register_workflow_tools(
    *,
    mcp: Any,
    tool_options: Callable[..., dict[str, Any]],
    audit_tool_call: Callable[..., str],
    json_response: Callable[..., str],
    run_agent_loop_step_impl: Any,
    build_context_pack_impl: Any,
    build_validation_suggestions_impl: Any,
    run_agent_loop_session_impl: Any,
    run_workflow_impl: Any,
    patch_file_getter: Callable[[], Any],
    run_shell_getter: Callable[[], Any],
    read_file_getter: Callable[[], Any],
    list_directory_getter: Callable[[], Any],
    find_relevant_files_getter: Callable[[], Any],
    resolve_path: Any,
    path_from_active_root: Any,
    project_dir: Any,
    infer_project_root: Any,
    iter_searchable_files: Any,
    git_status_snapshot: Any,
    effective_budget_tokens: Any,
    safe_json_object_load: Any,
    smart_budget_metadata: Any,
    enabled_names: set[str] | None = None,
) -> dict[str, Any]:
    ctx = ToolRegistrationContext(
        mcp=mcp,
        tool_options=tool_options,
        audit_tool_call=audit_tool_call,
        enabled_names=enabled_names,
    )

    if ctx.should_register("run_agent_loop_step"):

        async def _run_agent_loop_step(
            file: str,
            search: str,
            replace: str,
            validation_command: str,
            iteration: int = 1,
            max_iterations: int = 3,
        ) -> str:
            started_at = ctx.now_ms()
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

        ctx.register(
            "run_agent_loop_step",
            "Run one bounded agent-loop step: patch once, validate once.",
            _run_agent_loop_step,
            destructive=True,
        )

    if ctx.should_register("build_context_pack"):

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
            started_at = ctx.now_ms()
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
                {"target": target, "goal": goal, "max_files": max_files, "budget_tokens": bt},
                result,
                started_at=started_at,
            )

        ctx.register(
            "build_context_pack",
            "Build a context pack for a target and goal.",
            _build_context_pack,
            read_only=True,
        )

    if ctx.should_register("narrow_context"):

        async def _narrow_context(
            goal: str,
            target: str = ".",
            budget_tokens: int | None = None,
            max_files: int = 8,
            include_tests: bool = True,
            include_docs: bool = True,
        ) -> str:
            bt = budget_tokens if budget_tokens is not None else effective_budget_tokens()
            started_at = ctx.now_ms()
            if bt < 1:
                result = json_response(
                    False,
                    "budget_tokens must be at least 1",
                    code="invalid_budget_tokens",
                    details={"budget_tokens": bt},
                )
                return audit_tool_call(
                    "narrow_context",
                    {"goal": goal, "target": target, "budget_tokens": bt},
                    result,
                    started_at=started_at,
                )
            audit_params = {
                "goal": goal,
                "target": target,
                "budget_tokens": bt,
                "max_files": max_files,
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
                return audit_tool_call(
                    "narrow_context", audit_params, result, started_at=started_at
                )
            if payload is None or not payload.get("ok", False):
                return audit_tool_call(
                    "narrow_context", audit_params, context_pack, started_at=started_at
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
                    "context_budget_tokens": bt,
                    "budget_spent": running_total,
                    "selected_files": [item["path"] for item in chosen],
                    "omitted_files": [item["path"] for item in omitted],
                    "source_context_pack_files": details.get("selected_files", []),
                },
            )
            return audit_tool_call("narrow_context", audit_params, result, started_at=started_at)

        ctx.register(
            "narrow_context",
            "Build a budget-aware narrow context plan for a goal.",
            _narrow_context,
            read_only=True,
        )

    if ctx.should_register("suggest_validation_commands"):

        async def _suggest_validation_commands(target: str = ".") -> str:
            started_at = ctx.now_ms()
            result = await build_validation_suggestions_impl(
                target=target,
                resolve_path=resolve_path,
                infer_project_root=infer_project_root,
                json_response=json_response,
            )
            return audit_tool_call(
                "suggest_validation_commands", {"target": target}, result, started_at=started_at
            )

        ctx.register(
            "suggest_validation_commands",
            "Suggest validation commands for a target.",
            _suggest_validation_commands,
            read_only=True,
        )

    if ctx.should_register("run_agent_loop_session"):

        async def _run_agent_loop_session(
            steps_json: str | None = None,
            steps: list[dict[str, Any]] | None = None,
            max_iterations: int = 3,
            compact_threshold: int = 4,
            keep_recent_results: int = 2,
        ) -> str:
            started_at = ctx.now_ms()
            step_fn = ctx.results.get("run_agent_loop_step")
            result = await run_agent_loop_session_impl(
                steps_json=steps_json,
                steps=steps,
                max_iterations=max_iterations,
                compact_threshold=compact_threshold,
                keep_recent_results=keep_recent_results,
                run_agent_loop_step=step_fn,
                json_response=json_response,
            )
            return audit_tool_call(
                "run_agent_loop_session",
                {"max_iterations": max_iterations},
                result,
                started_at=started_at,
            )

        ctx.register(
            "run_agent_loop_session",
            "Run a bounded multi-step agent-loop session.",
            _run_agent_loop_session,
            destructive=True,
        )

    if ctx.should_register("run_workflow"):

        async def _run_workflow(
            mode: str,
            target: str = ".",
            option: str | None = None,
            language: str = "Turkish",
            execute: bool = False,
            max_iterations: int = 3,
        ) -> str:
            started_at = ctx.now_ms()
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
            return audit_tool_call(
                "run_workflow",
                {
                    "mode": mode,
                    "target": target,
                    "option": option,
                    "language": language,
                    "execute": execute,
                },
                result,
                started_at=started_at,
            )

        ctx.register(
            "run_workflow",
            "Generate a workflow prompt and optional first step.",
            _run_workflow,
            read_only=True,
        )

    return ctx.results
