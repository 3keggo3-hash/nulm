"""Main workflow orchestration and prompt catalog."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Awaitable, Callable

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
            }
            try:
                error_payload = json.loads(execution_error)
            except (json.JSONDecodeError, TypeError):
                error_payload = {
                    "message": "Execution failed with invalid response",
                    "code": "agent_loop_execution_failed",
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
    }
    if execution is not None:
        details["execution"] = execution

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
        "recommended_path": "Use an MCP prompt or slash UI when the client exposes it; fall back to run_workflow or a natural-language request only when necessary.",
    }
