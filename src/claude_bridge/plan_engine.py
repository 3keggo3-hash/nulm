"""CRUD for JSON plan files under .claude-bridge/plans/."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict, cast

from claude_bridge.config import project_dir


class PlanValidationResult(TypedDict):
    valid: bool
    errors: list[str]
    warnings: list[str]


class PlanCritiqueResult(TypedDict):
    plan_id: str
    score: int
    issues: list[str]
    suggestions: list[str]
    overall_assessment: str


def _plans_dir() -> Path:
    return project_dir() / ".claude-bridge" / "plans"


def _plan_path(plan_id: str) -> Path:
    return _plans_dir() / f"{plan_id}.json"


def _valid_plan_id(plan_id: str) -> bool:
    return re.fullmatch(r"[0-9a-f]{32}", plan_id) is not None


def _read_plan(plan_id: str) -> dict[str, Any] | None:
    if not _valid_plan_id(plan_id):
        return None
    file_path = _plan_path(plan_id)
    if not file_path.is_file():
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            return cast(dict[str, Any], json.load(fh))
    except json.JSONDecodeError:
        return None
    except OSError:
        return None


def _write_plan(plan_id: str, data: dict[str, Any]) -> bool:
    if not _valid_plan_id(plan_id):
        return False
    file_path = _plan_path(plan_id)
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        return True
    except OSError:
        return False


def create_plan(
    goal: str, steps_json: str, success_criteria_json: str | None = None
) -> dict[str, Any]:
    try:
        steps_raw: list[str] = json.loads(steps_json)
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "error": "Invalid steps_json: not valid JSON",
            "details": str(exc),
        }

    if not isinstance(steps_raw, list) or not all(isinstance(s, str) for s in steps_raw):
        return {
            "ok": False,
            "error": "steps_json must be a JSON array of strings",
        }

    if not steps_raw:
        return {
            "ok": False,
            "error": "steps_json must contain at least one step",
        }

    success_criteria: list[str] = []
    if success_criteria_json:
        try:
            success_criteria = json.loads(success_criteria_json)
        except json.JSONDecodeError as exc:
            return {
                "ok": False,
                "error": "Invalid success_criteria_json: not valid JSON",
                "details": str(exc),
            }
        if not isinstance(success_criteria, list) or not all(
            isinstance(c, str) for c in success_criteria
        ):
            return {
                "ok": False,
                "error": "success_criteria_json must be a JSON array of strings",
            }

    plan_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()

    plan: dict[str, Any] = {
        "plan_id": plan_id,
        "goal": goal,
        "created_at": now,
        "status": "active",
        "steps": [
            {
                "step_id": i,
                "description": desc,
                "status": "pending",
                "result": None,
                "completed_at": None,
            }
            for i, desc in enumerate(steps_raw)
        ],
        "completed_steps": 0,
        "total_steps": len(steps_raw),
        "success_criteria": success_criteria,
    }

    if not _write_plan(plan_id, plan):
        return {"ok": False, "error": "Failed to write plan file"}
    return {"ok": True, "plan": plan}


def execute_step(plan_id: str, step_id: int) -> dict[str, Any]:
    if not _valid_plan_id(plan_id):
        return {"ok": False, "error": "Invalid plan_id"}
    plan = _read_plan(plan_id)
    if plan is None:
        return {"ok": False, "error": f"Plan not found: {plan_id}"}

    steps: list[dict[str, Any]] = plan.get("steps", [])
    if step_id < 0 or step_id >= len(steps):
        return {
            "ok": False,
            "error": f"Step {step_id} not found in plan {plan_id}",
        }

    step = steps[step_id]
    if step.get("status") == "completed":
        return {
            "ok": False,
            "error": f"Step {step_id} is already completed in plan {plan_id}",
        }

    now = datetime.now(timezone.utc).isoformat()
    step["status"] = "completed"
    step["completed_at"] = now

    plan["completed_steps"] = sum(1 for s in steps if s.get("status") == "completed")
    if plan["completed_steps"] >= plan["total_steps"]:
        plan["status"] = "completed"

    if not _write_plan(plan_id, plan):
        return {"ok": False, "error": "Failed to write plan file"}
    return {"ok": True, "step": step}


def get_plan_status(plan_id: str) -> dict[str, Any]:
    if not _valid_plan_id(plan_id):
        return {"ok": False, "error": "Invalid plan_id"}
    plan = _read_plan(plan_id)
    if plan is None:
        return {"ok": False, "error": f"Plan not found: {plan_id}"}
    return {"ok": True, "plan": plan}


def validate_plan(plan_id: str) -> PlanValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    plan = _read_plan(plan_id)
    if plan is None:
        return PlanValidationResult(valid=False, errors=[f"Plan not found: {plan_id}"], warnings=[])

    goal = plan.get("goal", "")
    if not goal or len(goal.strip()) < 10:
        errors.append("Goal must be at least 10 characters")
    if len(goal) > 500:
        warnings.append("Goal is very long; consider simplifying")

    steps: list[dict[str, Any]] = plan.get("steps", [])
    if not steps:
        errors.append("Plan has no steps")
        return PlanValidationResult(valid=False, errors=errors, warnings=warnings)

    step_descriptions = [s.get("description", "") for s in steps]
    if len(set(step_descriptions)) == 1:
        warnings.append("All steps have identical descriptions")

    for i, step in enumerate(steps):
        desc = step.get("description", "")
        if not desc:
            errors.append(f"Step {i} has empty description")
        elif len(desc) < 5:
            errors.append(f"Step {i} description too short (< 5 chars)")
        if step.get("status") not in ("pending", "completed"):
            errors.append(f"Step {i} has invalid status: {step.get('status')}")

    success_criteria: list[str] = plan.get("success_criteria", [])
    if not success_criteria:
        warnings.append("Plan has no success criteria")
    else:
        if len(success_criteria) < 2:
            warnings.append("Consider adding at least 2 success criteria for better validation")
        for criterion in success_criteria:
            if not isinstance(criterion, str) or len(criterion.strip()) < 5:
                errors.append(f"Invalid success criterion: {criterion}")

    return PlanValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


def critique_plan(plan_id: str) -> PlanCritiqueResult:
    plan = _read_plan(plan_id)
    if plan is None:
        return PlanCritiqueResult(
            plan_id=plan_id,
            score=0,
            issues=[f"Plan not found: {plan_id}"],
            suggestions=[],
            overall_assessment="Plan not found",
        )

    issues: list[str] = []
    suggestions: list[str] = []
    score = 100

    goal = plan.get("goal", "")
    if not goal:
        issues.append("Missing goal")
        score -= 30

    steps: list[dict[str, Any]] = plan.get("steps", [])
    if len(steps) == 0:
        issues.append("No steps defined")
        score -= 40
    elif len(steps) == 1:
        issues.append("Single-step plan; consider breaking into clearer phases")
        score -= 10
    elif len(steps) > 15:
        issues.append("Very long plan; consider splitting into sub-plans")
        score -= 10

    completed = plan.get("completed_steps", 0)
    total = plan.get("total_steps", 0)
    if total > 0 and completed == 0:
        suggestions.append("No progress yet; prioritize first step execution")
    elif completed < total:
        suggestions.append(f"Plan is {completed}/{total} complete; continue execution")

    success_criteria: list[str] = plan.get("success_criteria", [])
    if not success_criteria:
        issues.append("No success criteria defined")
        score -= 20
        suggestions.append("Add success criteria to validate plan completion")
    else:
        if len(success_criteria) == 1:
            suggestions.append("Consider adding more specific success criteria")

    step_descriptions = [s.get("description", "").lower() for s in steps]
    if any("verify" not in d and "test" not in d for d in step_descriptions):
        suggestions.append("Consider adding verification or test steps")

    status = plan.get("status", "unknown")
    if status == "completed":
        suggestions.append("Plan is already completed")
    elif status not in ("active", "completed"):
        issues.append(f"Plan has unexpected status: {status}")
        score -= 10

    score = max(0, score)
    if score >= 80:
        assessment = "Plan is well-structured"
    elif score >= 50:
        assessment = "Plan needs improvements"
    else:
        assessment = "Plan requires significant revision"

    return PlanCritiqueResult(
        plan_id=plan_id,
        score=score,
        issues=issues,
        suggestions=suggestions,
        overall_assessment=assessment,
    )
