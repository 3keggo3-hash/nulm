"""Agent loop execution, validation command checking and session management."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any, Awaitable, Callable

from claude_bridge.workflow_project import (
    detect_project_type,
    suggest_validation_commands,
)

_VALIDATION_OPERATOR_TOKENS = {
    "|",
    "||",
    "&",
    "&&",
    ";",
    ">",
    ">>",
    "<",
    "<<",
    "2>",
    "2>>",
    "1>",
    "1>>",
    "&>",
}
_VALIDATION_ALLOWED_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("pytest",),
    ("python", "-m", "pytest"),
    ("python3", "-m", "pytest"),
    ("ruff", "check"),
    ("black", "--check"),
    ("mypy",),
    ("npm", "test"),
    ("npm", "run", "test"),
    ("pnpm", "test"),
    ("yarn", "test"),
    ("cargo", "test"),
    ("go", "test"),
    ("make", "test"),
    ("git", "diff"),
)


def _validation_command_error(command: str) -> dict[str, Any] | None:
    stripped = command.strip()
    if not stripped:
        return {"code": "missing_validation_command", "reason": "validation command is empty"}
    if "\n" in stripped or "\r" in stripped:
        return {
            "code": "unsafe_validation_command",
            "reason": "validation command contains a newline",
        }
    try:
        argv = shlex.split(stripped)
    except ValueError as exc:
        return {
            "code": "invalid_validation_command",
            "reason": f"validation command could not be parsed: {exc}",
        }
    if not argv:
        return {"code": "missing_validation_command", "reason": "validation command is empty"}
    for token in argv:
        if token in _VALIDATION_OPERATOR_TOKENS or any(ch in token for ch in "|&;<>`"):
            return {
                "code": "unsafe_validation_command",
                "reason": "validation command contains shell injection operators",
                "argv": argv,
            }
        if "$(" in token or "${" in token:
            return {
                "code": "unsafe_validation_command",
                "reason": "validation command contains shell expansion syntax",
                "argv": argv,
            }
    for prefix in _VALIDATION_ALLOWED_PREFIXES:
        if tuple(argv[: len(prefix)]) == prefix:
            return None
    return {
        "code": "unsupported_validation_command",
        "reason": "validation command is not in the allowlisted validation set",
        "argv": argv,
        "allowed_prefixes": [" ".join(prefix) for prefix in _VALIDATION_ALLOWED_PREFIXES],
    }


def build_agent_loop_execution_plan(
    *,
    target: str,
    resolved: Path,
    max_iterations: int,
    read_targets: list[str],
    project_root: Path,
) -> dict[str, Any]:
    validation_commands = suggest_validation_commands(resolved, project_root)
    focus_target = read_targets[0] if read_targets else target
    return {
        "iteration_budget": max_iterations,
        "current_iteration": 1,
        "project_type": detect_project_type(resolved, project_root),
        "focus_target": focus_target,
        "inspect_targets": read_targets,
        "proposed_patch_strategy": "make the smallest reversible change that tests the current hypothesis",
        "validation_commands": validation_commands,
        "decision_rule": "continue only if validation yields clearer evidence or a narrower fix",
        "stop_if": [
            "the first validation passes",
            "the next patch would broaden scope beyond the current target",
            "the evidence stays ambiguous after the current iteration",
        ],
    }


async def run_agent_loop_step(
    *,
    file: str,
    search: str,
    replace: str,
    validation_command: str,
    iteration: int,
    max_iterations: int,
    patch_file: Callable[..., Awaitable[str]],
    run_shell: Callable[[str], Awaitable[str]],
    json_response: Callable[..., str],
) -> str:
    if iteration < 1:
        return json_response(
            False,
            "iteration must be at least 1",
            code="invalid_iteration",
            details={"iteration": iteration},
        )
    if max_iterations < 1:
        return json_response(
            False,
            "max_iterations must be at least 1",
            code="invalid_max_iterations",
            details={"max_iterations": max_iterations},
        )
    if iteration > max_iterations:
        return json_response(
            False,
            "iteration cannot exceed max_iterations",
            code="invalid_iteration_budget",
            details={"iteration": iteration, "max_iterations": max_iterations},
        )
    validation_error = _validation_command_error(validation_command)
    if validation_error is not None:
        return json_response(
            False,
            validation_error["reason"],
            code=validation_error["code"],
            details={
                "iteration": iteration,
                "max_iterations": max_iterations,
                "validation_command": validation_command,
                "decision": "stop",
                **validation_error,
            },
        )

    try:
        patch_payload = json.loads(await patch_file(file=file, search=search, replace=replace))
    except (json.JSONDecodeError, TypeError):
        return json_response(
            False,
            "Agent loop step failed: patch_file returned invalid JSON",
            code="agent_loop_patch_failed",
            details={"iteration": iteration, "max_iterations": max_iterations, "decision": "stop"},
        )
    if not isinstance(patch_payload, dict) or not patch_payload.get("ok"):
        return json_response(
            False,
            "Agent loop step failed during patch phase",
            code="agent_loop_patch_failed",
            details={
                "iteration": iteration,
                "max_iterations": max_iterations,
                "patch_result": patch_payload,
                "decision": "stop",
            },
        )

    try:
        validation_payload = json.loads(await run_shell(validation_command))
    except (json.JSONDecodeError, TypeError):
        return json_response(
            False,
            "Agent loop step failed: validation command returned invalid JSON",
            code="agent_loop_validation_failed",
            details={
                "iteration": iteration,
                "max_iterations": max_iterations,
                "validation_command": validation_command,
                "decision": "stop",
            },
        )
    validation_ok = bool(validation_payload.get("ok", False))
    decision = (
        "stop_success"
        if validation_ok
        else ("continue" if iteration < max_iterations else "stop_failure")
    )

    return json_response(
        True,
        "Agent loop step executed",
        details={
            "iteration": iteration,
            "max_iterations": max_iterations,
            "patch_result": patch_payload,
            "validation_result": validation_payload,
            "decision": decision,
            "next_action": (
                "stop"
                if decision == "stop_success"
                else "inspect validation output and prepare the next smallest patch"
            ),
        },
    )


def build_agent_loop_session_summary(
    session_results: list[dict[str, Any]],
    *,
    max_iterations: int,
    final_decision: str,
    results_compacted: bool = False,
    compacted_steps: int = 0,
    retained_recent_steps: int = 0,
) -> dict[str, Any]:
    files_touched: list[str] = []
    last_successful_file: str | None = None
    last_validation_command: str | None = None
    last_validation_ok: bool | None = None

    for result in session_results:
        details = result.get("details", {})
        patch_result = details.get("patch_result", {})
        validation_result = details.get("validation_result", {})
        patch_details = patch_result.get("details", {})
        validation_details = validation_result.get("details", {})

        path = patch_details.get("path")
        if isinstance(path, str):
            if path not in files_touched:
                files_touched.append(path)
            if patch_result.get("ok"):
                last_successful_file = path

        command = validation_details.get("command")
        if isinstance(command, str):
            last_validation_command = command

        if isinstance(validation_result.get("ok"), bool):
            last_validation_ok = validation_result["ok"]

    remaining_budget = max(max_iterations - len(session_results), 0)
    if final_decision == "stop_success":
        next_recommended_action = "stop"
    elif final_decision == "stop_failure":
        next_recommended_action = (
            "inspect the last validation failure before planning another session"
        )
    else:
        next_recommended_action = "prepare the next smallest reversible patch"

    validation_label = (
        "passed" if last_validation_ok else ("failed" if last_validation_ok is False else "not run")
    )
    handoff_summary = (
        f"Executed {len(session_results)} step(s); final decision: {final_decision}. "
        f"Files touched: {', '.join(files_touched) if files_touched else 'none'}. "
        f"Last validation {validation_label}"
        f"{f' via {last_validation_command}' if last_validation_command else ''}. "
        f"Next action: {next_recommended_action}."
    )

    return {
        "executed_steps": len(session_results),
        "final_decision": final_decision,
        "files_touched": files_touched,
        "last_successful_file": last_successful_file,
        "last_validation_ok": last_validation_ok,
        "last_validation_command": last_validation_command,
        "remaining_budget": remaining_budget,
        "next_recommended_action": next_recommended_action,
        "results_compacted": results_compacted,
        "compacted_steps": compacted_steps,
        "retained_recent_steps": retained_recent_steps,
        "handoff_summary": handoff_summary,
    }


def compact_agent_loop_result(result: dict[str, Any]) -> dict[str, Any]:
    details = result.get("details", {})
    patch_result = details.get("patch_result", {})
    validation_result = details.get("validation_result", {})
    patch_details = patch_result.get("details", {})
    validation_details = validation_result.get("details", {})
    return {
        "iteration": details.get("iteration"),
        "decision": details.get("decision"),
        "file": patch_details.get("path"),
        "validation_ok": validation_result.get("ok"),
        "validation_command": validation_details.get("command"),
        "message": result.get("message"),
    }


def compact_agent_loop_session_results(
    session_results: list[dict[str, Any]],
    *,
    compact_threshold: int,
    keep_recent_results: int,
) -> tuple[bool, list[dict[str, Any]], list[dict[str, Any]], int]:
    if len(session_results) <= compact_threshold:
        return False, [], session_results, len(session_results)

    if keep_recent_results >= len(session_results):
        return False, [], session_results, len(session_results)

    older_results = session_results[:-keep_recent_results]
    recent_results = session_results[-keep_recent_results:]
    compacted_history = [compact_agent_loop_result(result) for result in older_results]
    return True, compacted_history, recent_results, len(recent_results)


async def run_agent_loop_session(
    *,
    steps_json: str | None,
    steps: list[dict[str, Any]] | None,
    max_iterations: int,
    compact_threshold: int,
    keep_recent_results: int,
    run_agent_loop_step: Callable[..., Awaitable[str]],
    json_response: Callable[..., str],
) -> str:
    if max_iterations < 1:
        return json_response(
            False,
            "max_iterations must be at least 1",
            code="invalid_max_iterations",
            details={"max_iterations": max_iterations},
        )
    if compact_threshold < 1:
        return json_response(
            False,
            "compact_threshold must be at least 1",
            code="invalid_compact_threshold",
            details={"compact_threshold": compact_threshold},
        )
    if keep_recent_results < 1:
        return json_response(
            False,
            "keep_recent_results must be at least 1",
            code="invalid_keep_recent_results",
            details={"keep_recent_results": keep_recent_results},
        )

    planned_input = steps
    if planned_input is None:
        if steps_json is None:
            return json_response(
                False,
                "Either steps or steps_json must be provided",
                code="missing_steps",
                details={},
            )
        try:
            planned_input = json.loads(steps_json)
        except json.JSONDecodeError as exc:
            return json_response(
                False,
                f"Invalid steps_json: {exc}",
                code="invalid_steps_json",
                details={"steps_json": steps_json},
            )

    if not isinstance(planned_input, list) or not planned_input:
        return json_response(
            False,
            "steps must be a non-empty list",
            code="invalid_steps_payload",
            details={"steps_json": steps_json, "steps": planned_input},
        )

    planned_steps = planned_input[:max_iterations]
    session_results: list[dict[str, Any]] = []
    final_decision = "stop_failure"

    for iteration, step in enumerate(planned_steps, start=1):
        if not isinstance(step, dict):
            return json_response(
                False,
                "Each step must be an object",
                code="invalid_step_entry",
                details={"step": step, "iteration": iteration},
            )

        required = {"file", "search", "replace", "validation_command"}
        missing = sorted(required - set(step))
        if missing:
            return json_response(
                False,
                "Step is missing required fields",
                code="invalid_step_fields",
                details={"iteration": iteration, "missing_fields": missing},
            )

        try:
            step_result = json.loads(
                await run_agent_loop_step(
                    file=step["file"],
                    search=step["search"],
                    replace=step["replace"],
                    validation_command=step["validation_command"],
                    iteration=iteration,
                    max_iterations=max_iterations,
                )
            )
        except (json.JSONDecodeError, TypeError) as exc:
            return json_response(
                False,
                f"Agent loop step {iteration} returned invalid JSON: {exc}",
                code="agent_loop_step_invalid_payload",
                details={
                    "iteration": iteration,
                    "max_iterations": max_iterations,
                    "decision": "stop",
                },
            )
        session_results.append(step_result)

        if not step_result["ok"]:
            final_decision = "stop_failure"
            break

        final_decision = step_result["details"]["decision"]
        if final_decision in {"stop_success", "stop_failure"}:
            break

    results_compacted, compacted_history, visible_results, retained_recent_steps = (
        compact_agent_loop_session_results(
            session_results,
            compact_threshold=compact_threshold,
            keep_recent_results=keep_recent_results,
        )
    )
    session_summary = build_agent_loop_session_summary(
        session_results,
        max_iterations=max_iterations,
        final_decision=final_decision,
        results_compacted=results_compacted,
        compacted_steps=len(compacted_history),
        retained_recent_steps=retained_recent_steps,
    )

    return json_response(
        True,
        "Agent loop session executed",
        details={
            "max_iterations": max_iterations,
            "compact_threshold": compact_threshold,
            "keep_recent_results": keep_recent_results,
            "executed_steps": len(session_results),
            "final_decision": final_decision,
            "results_compacted": results_compacted,
            "compacted_steps": len(compacted_history),
            "compacted_history": compacted_history,
            "session_summary": session_summary,
            "results": visible_results,
        },
    )
