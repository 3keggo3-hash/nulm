"""Main workflow orchestration and prompt catalog."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from claude_bridge.agent_advisor import (
    AgentAdviceRequest,
    AgentAdviceResponse,
    ImprovedRequestResponse,
    PlanQualityReviewRequest,
    PlanQualityReviewResponse,
    ResultQualityReviewRequest,
    ResultQualityReviewResponse,
    advise_next_step,
    improve_request,
    plan_quality_review,
    review_result_quality,
)
from claude_bridge.tool_utils import path_outside_project_details
from claude_bridge.workflow_agent_loop import build_agent_loop_execution_plan
from claude_bridge.workflow_cache import (
    _WORKFLOW_CACHE_LOCK,
    _WORKFLOW_PLAN_CACHE,
    _load_disk_cached_response,
    _safe_cached_json_payload,
    _store_cache_entry,
    _touch_cache_entry,
    _write_disk_cached_response,
)
from claude_bridge.workflow_presets import (
    prompt_shortcut_catalog,
    SUPPORTED_WORKFLOW_MODES,
    WORKFLOW_DISCOVERY_TERMS,
    WORKFLOW_EXAMPLES,
    WORKFLOW_ORCHESTRATION_RULES,
    WORKFLOW_QUALITY_BAR,
    WORKFLOW_STEPS,
    WORKFLOW_WARNINGS,
    build_agent_loop_policy,
    workflow_prompt,
)
from claude_bridge.workflow_project import (
    _display_path,
    _safe_json_response_load,
    _workflow_state_signature,
    detect_project_type,
    supplemental_review_targets,
)


def _workflow_recipe(
    *,
    mode: str,
    project_type: str,
    execute: bool,
    max_iterations: int,
) -> dict[str, Any]:
    recipe = {
        "mode": mode,
        "project_type": project_type,
        "shape": ["discover", "read", "analyze"],
        "execute_first_step": execute,
    }
    if mode == "agent_loop":
        recipe["shape"] = ["discover", "inspect", "patch", "validate", "decide"]
        recipe["iteration_budget"] = max_iterations
    elif mode == "orchestrate":
        recipe["shape"] = ["discover", "split_workstreams", "define_validation", "integrate"]
    elif mode == "test":
        recipe["shape"] = ["discover", "inspect_existing_tests", "design_regressions"]
    elif mode == "commit":
        recipe["shape"] = ["discover", "read_changes", "summarize_impact"]
    return recipe


def _workflow_goal(*, mode: str, target: str, option: str | None) -> str:
    focus = option or WORKFLOW_DISCOVERY_TERMS[mode]
    return f"{mode} workflow for {target}: {focus}"


def _workflow_plan_text(
    *,
    mode: str,
    target: str,
    steps: list[str],
    recommended_tools: list[str],
    execute: bool,
) -> str:
    return (
        f"Run {mode} workflow for {target}. "
        f"Steps: {'; '.join(steps)}. "
        f"Recommended tools: {', '.join(recommended_tools)}. "
        f"execute={execute}."
    )


def _workflow_quality_gate_plan(*, mode: str, execute: bool) -> str:
    if execute:
        return (
            "After the workflow result is produced, summarize changed files, validation, docs "
            "impact, security/config impact, and call review_result_quality."
        )
    return (
        "Before executing edits, keep this workflow as a quality gate plan: collect changed files, "
        "run focused validation, note docs/security impact, then call review_result_quality."
    )


def _result_quality_gate_checklist() -> list[str]:
    return [
        "Compare the final result with the clarified goal.",
        "Confirm changed files stayed inside the intended scope.",
        "Run or name focused validation for touched behavior.",
        "Check docs or roadmap drift when user-facing behavior changes.",
        "Verify no shell, path, approval, config, or secret-handling risk changed.",
        "Record any token/context waste and how to avoid it next time.",
        "Name the next smallest fix instead of opening a broad follow-up.",
    ]


def _workflow_agent_quality(
    *,
    mode: str,
    target: str,
    option: str | None,
    steps: list[str],
    recommended_tools: list[str],
    execute: bool,
) -> dict[str, Any]:
    goal = _workflow_goal(mode=mode, target=target, option=option)
    plan = _workflow_plan_text(
        mode=mode,
        target=target,
        steps=steps,
        recommended_tools=recommended_tools,
        execute=execute,
    )
    recent_context = {
        "workflow_mode": mode,
        "execute": execute,
        "read_only_boundary": not execute,
    }
    advice = advise_next_step(
        AgentAdviceRequest(goal=goal, target=target, recent_context=recent_context)
    )
    improved = improve_request(goal, target=target)
    plan_review = plan_quality_review(PlanQualityReviewRequest(plan=plan, goal=goal, target=target))
    result_review = review_result_quality(
        ResultQualityReviewRequest(
            goal=goal,
            result_summary=_workflow_quality_gate_plan(mode=mode, execute=execute),
            validation={"planned": True, "commands": advice.validation},
            recent_context=recent_context,
            constraints={"read-only": not execute, "advisory": True},
        )
    )
    return {
        "schema_version": "workflow_agent_quality.v1",
        "boundary": {
            "start": "improve_request + advise_next_step + plan_quality_review",
            "finish": "quality gate plan for review_result_quality",
        },
        "especially_visible": mode == "quality",
        "improved_request": improved.to_dict(),
        "clarified_goal": improved.clarified_goal,
        "plan_quality": plan_review.to_dict(),
        "context_strategy": advice.needed_context,
        "token_strategy": advice.token_strategy,
        "suggested_next_prompt": advice.next_prompt,
        "risks": advice.risks + plan_review.concerns + plan_review.scope_warnings,
        "quality_gate_plan": {
            "summary": _workflow_quality_gate_plan(mode=mode, execute=execute),
            "checklist": _result_quality_gate_checklist(),
            "result_review_template": result_review.to_dict(),
        },
        "quality_first": {
            "enabled": mode == "quality",
            "clarified_goal": improved.clarified_goal,
            "improved_request": improved.to_dict(),
            "plan_quality_review": plan_review.to_dict(),
            "context_strategy": advice.needed_context,
            "token_strategy": advice.token_strategy,
            "result_quality_gate_checklist": _result_quality_gate_checklist(),
            "suggested_next_prompt": advice.next_prompt,
        },
        "read_only": True,
    }


def _workflow_agent_quality_optimized(
    *,
    mode: str,
    target: str,
    option: str | None,
    steps: list[str],
    recommended_tools: list[str],
    execute: bool,
) -> dict[str, Any]:
    """Build workflow agent quality with parallel advisor calls.

    Original: 4 sequential synchronous calls
    Optimized: Run all 4 advisor calls concurrently via ThreadPoolExecutor
    """
    from concurrent.futures import ThreadPoolExecutor

    goal = _workflow_goal(mode=mode, target=target, option=option)
    plan = _workflow_plan_text(
        mode=mode,
        target=target,
        steps=steps,
        recommended_tools=recommended_tools,
        execute=execute,
    )
    recent_context = {
        "workflow_mode": mode,
        "execute": execute,
        "read_only_boundary": not execute,
    }
    quality_gate_plan = _workflow_quality_gate_plan(mode=mode, execute=execute)

    def _run_parallel_advisors() -> tuple[
        AgentAdviceResponse,
        ImprovedRequestResponse,
        PlanQualityReviewResponse,
        ResultQualityReviewResponse,
    ]:
        advice_req = AgentAdviceRequest(goal=goal, target=target, recent_context=recent_context)
        plan_req = PlanQualityReviewRequest(plan=plan, goal=goal, target=target)
        result_req = ResultQualityReviewRequest(
            goal=goal,
            result_summary=quality_gate_plan,
            validation={"planned": True, "commands": []},
            recent_context=recent_context,
            constraints={"read-only": not execute, "advisory": True},
        )
        advice = advise_next_step(advice_req)
        improved = improve_request(goal, target=target)
        plan_review = plan_quality_review(plan_req)
        result_review = review_result_quality(result_req)
        return advice, improved, plan_review, result_review

    with ThreadPoolExecutor(max_workers=4) as pool:
        future = pool.submit(_run_parallel_advisors)
        advice, improved, plan_review, result_review = future.result()

    return {
        "schema_version": "workflow_agent_quality.v1",
        "boundary": {
            "start": "improve_request + advise_next_step + plan_quality_review",
            "finish": "quality gate plan for review_result_quality",
        },
        "especially_visible": mode == "quality",
        "improved_request": improved.to_dict(),
        "clarified_goal": improved.clarified_goal,
        "plan_quality": plan_review.to_dict(),
        "context_strategy": advice.needed_context,
        "token_strategy": advice.token_strategy,
        "suggested_next_prompt": advice.next_prompt,
        "risks": advice.risks + plan_review.concerns + plan_review.scope_warnings,
        "quality_gate_plan": {
            "summary": quality_gate_plan,
            "checklist": _result_quality_gate_checklist(),
            "result_review_template": result_review.to_dict(),
        },
        "quality_first": {
            "enabled": mode == "quality",
            "clarified_goal": improved.clarified_goal,
            "improved_request": improved.to_dict(),
            "plan_quality_review": plan_review.to_dict(),
            "context_strategy": advice.needed_context,
            "token_strategy": advice.token_strategy,
            "result_quality_gate_checklist": _result_quality_gate_checklist(),
            "suggested_next_prompt": advice.next_prompt,
        },
        "read_only": True,
    }


def _execution_result_summary(execution: dict[str, Any] | None) -> dict[str, Any]:
    if execution is None:
        return {
            "status": "not_executed",
            "performed_actions": [],
            "changed_files": [],
            "validation_ok": None,
            "result_summary": "Workflow was prepared but not executed.",
            "risks": ["Quality gate still needs real execution evidence."],
            "follow_up": ["Execute the workflow or run the relevant quality gate manually."],
        }

    performed_actions = [
        str(item) for item in execution.get("performed_actions", []) if isinstance(item, str)
    ]
    changed_files: list[str] = []
    validation_ok: bool | None = None
    risks: list[str] = []
    follow_up: list[str] = []
    result_messages: list[str] = []

    results = execution.get("results", [])
    if isinstance(results, list):
        for result in results:
            if not isinstance(result, dict):
                continue
            result_messages.append(str(result.get("message", "")))
            details = result.get("details", {})
            if not isinstance(details, dict):
                continue
            path = details.get("path")
            if isinstance(path, str) and path not in changed_files:
                changed_files.append(path)
            validation_result = details.get("validation_result")
            if isinstance(validation_result, dict) and isinstance(
                validation_result.get("ok"), bool
            ):
                validation_ok = validation_result["ok"]

    if validation_ok is False:
        risks.append("Validation failed during workflow execution.")
        follow_up.append("Inspect validation output before planning another patch.")
    elif validation_ok is True:
        follow_up.append("Run result quality review against changed files and validation.")
    else:
        risks.append("No validation result was produced by this workflow execution.")
        follow_up.append("Name and run focused validation before treating the result as complete.")

    if not changed_files:
        follow_up.append("No changed files were reported; use the execution evidence as context.")

    summary = (
        f"Executed actions: {', '.join(performed_actions) if performed_actions else 'none'}. "
        f"Changed files: {', '.join(changed_files) if changed_files else 'none'}. "
        f"Validation: {_validation_label(validation_ok)}."
    )
    if result_messages:
        summary += f" Last result: {result_messages[-1]}."

    return {
        "status": "succeeded",
        "performed_actions": performed_actions,
        "changed_files": changed_files,
        "validation_ok": validation_ok,
        "result_summary": summary,
        "risks": risks,
        "follow_up": follow_up,
    }


def _validation_label(validation_ok: bool | None) -> str:
    if validation_ok is True:
        return "passed"
    if validation_ok is False:
        return "failed"
    return "not run"


def _execution_failure_summary(
    *,
    execution: dict[str, Any] | None,
    error_payload: dict[str, Any],
) -> dict[str, Any]:
    summary = _execution_result_summary(execution)
    summary["status"] = "failed"
    summary["error_message"] = str(error_payload.get("message", "Execution failed"))
    summary["error_code"] = error_payload.get("code")
    summary["risks"] = [
        "Workflow execution failed before the quality gate could complete.",
        *list(summary.get("risks", [])),
    ]
    summary["follow_up"] = [
        "Inspect the failure output before making another change.",
        "Re-run only the smallest failing discovery or validation step.",
    ]
    summary["result_summary"] = (
        f"Workflow execution failed: {summary['error_message']}. "
        f"Actions before failure: {', '.join(summary['performed_actions']) or 'none'}."
    )
    return summary


def _executed_workflow_next_prompt(
    *,
    goal: str,
    summary: dict[str, Any],
) -> str:
    status = str(summary.get("status", "not_executed"))
    validation_ok = summary.get("validation_ok")
    changed_files = summary.get("changed_files", [])
    result_summary = str(summary.get("result_summary", ""))

    if status == "failed" or validation_ok is False:
        return (
            f"Inspect this workflow failure before editing further: {result_summary} "
            f"Original goal: {goal}. Read the failure/validation output, identify the "
            "smallest next evidence-gathering step, and stop if the cause is ambiguous."
        )

    if validation_ok is True:
        files = ", ".join(changed_files) if changed_files else "the touched files"
        return (
            f"Review the executed workflow result for {files}: {result_summary} "
            "Run review_result_quality with changed files and validation evidence, then propose "
            "the next smallest improvement only if the quality gate passes."
        )

    return (
        f"Turn this executed workflow summary into the next small quality step: {result_summary} "
        f"Original goal: {goal}. First name focused validation, then decide whether result "
        "quality review or a narrower follow-up is needed."
    )


def _add_executed_workflow_quality(
    *,
    agent_quality: dict[str, Any],
    mode: str,
    target: str,
    option: str | None,
    execution_summary: dict[str, Any],
) -> None:
    goal = _workflow_goal(mode=mode, target=target, option=option)
    result_review = review_result_quality(
        ResultQualityReviewRequest(
            goal=goal,
            result_summary=str(execution_summary.get("result_summary", "")),
            changed_files=list(execution_summary.get("changed_files", [])),
            validation={
                "ok": execution_summary.get("validation_ok"),
                "failed": execution_summary.get("validation_ok") is False,
            },
            recent_context={"executed_workflow": True, "mode": mode},
            constraints={"advisory": True, "read-only": True},
        )
    )
    next_prompt = _executed_workflow_next_prompt(goal=goal, summary=execution_summary)
    agent_quality["execution_summary"] = execution_summary
    agent_quality["executed_result_quality"] = result_review.to_dict()
    agent_quality["suggested_next_prompt"] = next_prompt
    quality_first = agent_quality.get("quality_first")
    if isinstance(quality_first, dict):
        quality_first["suggested_next_prompt"] = next_prompt
        quality_first["executed_result_quality"] = result_review.to_dict()


def _ensure_agent_quality_details(details: dict[str, Any]) -> None:
    existing = details.get("agent_quality")
    if isinstance(existing, dict) and "quality_first" in existing:
        return
    mode = str(details.get("mode", "review"))
    target = str(details.get("target", "."))
    option = None
    steps = details.get("steps", [])
    recommended_tools = details.get("recommended_tools", [])
    if not isinstance(steps, list) or not all(isinstance(item, str) for item in steps):
        steps = []
    if not isinstance(recommended_tools, list) or not all(
        isinstance(item, str) for item in recommended_tools
    ):
        recommended_tools = []
    details["agent_quality"] = _workflow_agent_quality(
        mode=mode,
        target=target,
        option=option,
        steps=steps,
        recommended_tools=recommended_tools,
        execute=bool(details.get("execute", False)),
    )


async def _execute_workflow_first_step(
    *,
    mode: str,
    target: str,
    option: str | None,
    max_iterations: int,
    resolved: Path,
    active_project_dir: Path,
    project_root: Path,
    path_from_active_root: Callable[[Path], str],
    read_file: Callable[[str], Awaitable[str]],
    list_directory: Callable[[str], Awaitable[str]],
    find_relevant_files: Callable[..., Awaitable[str]],
    json_response: Callable[..., str],
) -> tuple[dict[str, Any] | None, str | None]:
    read_targets_for_plan: list[str] = []
    if resolved.is_file():
        performed = ["read_file"]
        read_raw = await read_file(target)
        read_payload, parse_error = _safe_json_response_load(
            read_raw,
            json_response=json_response,
            tool_name="read_file",
        )
        if parse_error is not None or read_payload is None:
            return None, parse_error
        results = [read_payload]
        read_targets_for_plan.append(target)
        extra_targets = supplemental_review_targets(resolved, project_root)
        for extra in extra_targets:
            performed.append("read_file")
            extra_target = _display_path(
                extra,
                active_project_dir=active_project_dir,
                project_root=project_root,
                path_from_active_root=path_from_active_root,
            )
            read_targets_for_plan.append(extra_target)
            extra_read_raw = await read_file(extra_target)
            extra_read_payload, parse_error = _safe_json_response_load(
                extra_read_raw,
                json_response=json_response,
                tool_name="read_file",
            )
            if parse_error is not None or extra_read_payload is None:
                return None, parse_error
            results.append(extra_read_payload)
        execution: dict[str, Any] = {"performed_actions": performed, "results": results}
        if mode == "agent_loop":
            execution["loop_plan"] = build_agent_loop_execution_plan(
                target=target,
                resolved=resolved,
                max_iterations=max_iterations,
                read_targets=read_targets_for_plan,
                project_root=project_root,
            )
        return execution, None

    performed = ["list_directory", "find_relevant_files"]
    list_raw = await list_directory(target)
    list_payload, parse_error = _safe_json_response_load(
        list_raw,
        json_response=json_response,
        tool_name="list_directory",
    )
    if parse_error is not None or list_payload is None:
        return None, parse_error
    results = [list_payload]
    relevant_raw = await find_relevant_files(
        query=option or WORKFLOW_DISCOVERY_TERMS[mode],
        path=target,
        limit=max(max_iterations, 3),
    )
    relevant_payload, parse_error = _safe_json_response_load(
        relevant_raw,
        json_response=json_response,
        tool_name="find_relevant_files",
    )
    if parse_error is not None or relevant_payload is None:
        return None, parse_error
    results.append(relevant_payload)
    if not relevant_payload.get("ok", False):
        return {"performed_actions": performed, "results": results}, json_response(
            False,
            relevant_payload["message"],
            code=relevant_payload.get("code"),
            details=relevant_payload.get("details", {}),
        )
    read_targets: list[str] = []
    for item in relevant_payload["details"].get("results", [])[: max(max_iterations, 3)]:
        best_match = item["path"]
        read_target = (
            f"{target.rstrip('/')}/{best_match}" if target not in {".", ""} else best_match
        )
        if read_target not in read_targets:
            read_targets.append(read_target)
    for extra in supplemental_review_targets(resolved, project_root):
        extra_target = _display_path(
            extra,
            active_project_dir=active_project_dir,
            project_root=project_root,
            path_from_active_root=path_from_active_root,
        )
        if extra_target not in read_targets:
            read_targets.append(extra_target)
    if read_targets:
        read_targets_for_plan.extend(read_targets)
        performed.append("read_file")
        results.append(
            {"ok": True, "message": "Planned read targets", "details": {"targets": read_targets}}
        )
        for read_target in read_targets:
            performed.append("read_file")
            read_raw = await read_file(read_target)
            read_payload, parse_error = _safe_json_response_load(
                read_raw,
                json_response=json_response,
                tool_name="read_file",
            )
            if parse_error is not None or read_payload is None:
                return None, parse_error
            results.append(read_payload)
    execution = {"performed_actions": performed, "results": results}
    if mode == "agent_loop":
        execution["loop_plan"] = build_agent_loop_execution_plan(
            target=target,
            resolved=resolved,
            max_iterations=max_iterations,
            read_targets=read_targets_for_plan,
            project_root=project_root,
        )
    return execution, None


async def run_workflow(
    *,
    mode: str,
    target: str,
    option: str | None,
    language: str,
    execute: bool,
    max_iterations: int,
    resolve_path: Callable[[str], Path],
    read_file: Callable[[str], Awaitable[str]],
    list_directory: Callable[[str], Awaitable[str]],
    find_relevant_files: Callable[..., Awaitable[str]],
    path_from_active_root: Callable[[Path], str],
    project_dir: Callable[[], Path],
    infer_project_root: Callable[[Path], Path],
    json_response: Callable[..., str],
) -> str:
    if mode not in SUPPORTED_WORKFLOW_MODES:
        return json_response(
            False,
            f"Unsupported workflow mode: {mode}",
            code="unknown_workflow_mode",
            details={"mode": mode},
        )
    if max_iterations < 1:
        return json_response(
            False,
            "max_iterations must be at least 1",
            code="invalid_max_iterations",
            details={"max_iterations": max_iterations},
        )

    prompt = workflow_prompt(mode, target, option, language)
    try:
        resolved_for_type = resolve_path(target)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(target),
        )
    active_project_dir = project_dir()
    project_root = infer_project_root(resolved_for_type)
    project_type = detect_project_type(resolved_for_type, project_root)
    state_signature = _workflow_state_signature(resolved_for_type, project_root)
    cache_key = (
        mode,
        target,
        option or "",
        language,
        str(max_iterations),
        str(project_root.resolve()),
        str(resolved_for_type.resolve()),
        state_signature,
    )
    if not execute:
        with _WORKFLOW_CACHE_LOCK:
            cached_payload = _touch_cache_entry(_WORKFLOW_PLAN_CACHE, cache_key)
            if cached_payload is None:
                cached_payload = _load_disk_cached_response("workflow-plan", cache_key)
                if cached_payload is not None:
                    _store_cache_entry(_WORKFLOW_PLAN_CACHE, cache_key, cached_payload)
        if cached_payload is not None:
            cached = _safe_cached_json_payload(cached_payload)
            if cached is not None and isinstance(cached.get("details"), dict):
                cached["details"]["cached"] = True
                _ensure_agent_quality_details(cached["details"])
                return json.dumps(cached, ensure_ascii=False)
    recommended_tools = ["list_directory", "read_file"]
    if mode == "todo":
        recommended_tools.append("run_shell")
    steps = WORKFLOW_STEPS[mode]
    examples = WORKFLOW_EXAMPLES[mode]
    warnings = WORKFLOW_WARNINGS
    quality_bar = WORKFLOW_QUALITY_BAR
    orchestration_rules = WORKFLOW_ORCHESTRATION_RULES
    agent_loop_policy = build_agent_loop_policy(max_iterations)
    agent_quality = _workflow_agent_quality(
        mode=mode,
        target=target,
        option=option,
        steps=steps,
        recommended_tools=recommended_tools,
        execute=execute,
    )

    execution: dict[str, Any] | None = None
    if execute:
        execution, execution_error = await _execute_workflow_first_step(
            mode=mode,
            target=target,
            option=option,
            max_iterations=max_iterations,
            resolved=resolved_for_type,
            active_project_dir=active_project_dir,
            project_root=project_root,
            path_from_active_root=path_from_active_root,
            read_file=read_file,
            list_directory=list_directory,
            find_relevant_files=find_relevant_files,
            json_response=json_response,
        )
        if execution_error is not None:
            try:
                error_payload = json.loads(execution_error)
            except (json.JSONDecodeError, TypeError):
                error_payload = {
                    "message": "Execution failed with invalid response",
                    "code": "agent_loop_execution_failed",
                }
            _add_executed_workflow_quality(
                agent_quality=agent_quality,
                mode=mode,
                target=target,
                option=option,
                execution_summary=_execution_failure_summary(
                    execution=execution,
                    error_payload=error_payload,
                ),
            )
            error_details: dict[str, Any] = {
                "mode": mode,
                "target": target,
                "project_type": project_type,
                "prompt": prompt,
                "recommended_tools": recommended_tools,
                "steps": steps,
                "examples": examples,
                "warnings": warnings,
                "quality_bar": quality_bar,
                "orchestration_rules": orchestration_rules,
                "agent_loop_policy": agent_loop_policy,
                "execute": execute,
                "max_iterations": max_iterations,
                "execution": execution,
                "agent_quality": agent_quality,
            }
            return json_response(
                False,
                error_payload["message"],
                code=error_payload.get("code"),
                details=error_details,
            )

    details: dict[str, Any] = {
        "mode": mode,
        "target": target,
        "project_type": project_type,
        "prompt": prompt,
        "recommended_tools": recommended_tools,
        "steps": steps,
        "examples": examples,
        "warnings": warnings,
        "quality_bar": quality_bar,
        "orchestration_rules": orchestration_rules,
        "agent_loop_policy": agent_loop_policy,
        "execute": execute,
        "max_iterations": max_iterations,
        "cached": False,
        "recipe": _workflow_recipe(
            mode=mode,
            project_type=project_type,
            execute=execute,
            max_iterations=max_iterations,
        ),
        "agent_quality": agent_quality,
    }
    if execution is not None:
        details["execution"] = execution
        _add_executed_workflow_quality(
            agent_quality=agent_quality,
            mode=mode,
            target=target,
            option=option,
            execution_summary=_execution_result_summary(execution),
        )

    response = json_response(True, f"Workflow prepared for mode: {mode}", details=details)
    if not execute:
        with _WORKFLOW_CACHE_LOCK:
            _store_cache_entry(_WORKFLOW_PLAN_CACHE, cache_key, response)
            try:
                _write_disk_cached_response("workflow-plan", cache_key, response)
            except OSError:
                pass
    return response


def build_prompt_catalog_payload() -> dict[str, Any]:
    catalog = prompt_shortcut_catalog()
    return {
        "shortcuts": catalog["shortcuts"],
        "client_side_only": catalog["client_side_only"],
        "notes": catalog["notes"],
        "recommended_path": (
            "Use an MCP prompt or slash UI when the client exposes it; fall back to "
            "run_workflow or a natural-language request only when necessary."
        ),
    }
