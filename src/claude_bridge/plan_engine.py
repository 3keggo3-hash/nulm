"""CRUD for JSON plan files under .claude-bridge/plans/."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from claude_bridge.config import project_dir


def _plans_dir() -> Path:
    return project_dir() / ".claude-bridge" / "plans"


def _plan_path(plan_id: str) -> Path:
    return _plans_dir() / f"{plan_id}.json"


def _read_plan(plan_id: str) -> dict[str, Any] | None:
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
    file_path = _plan_path(plan_id)
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        return True
    except OSError:
        return False


def create_plan(goal: str, steps_json: str) -> dict[str, Any]:
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
    }

    if not _write_plan(plan_id, plan):
        return {"ok": False, "error": "Failed to write plan file"}
    return {"ok": True, "plan": plan}


def execute_step(plan_id: str, step_id: int) -> dict[str, Any]:
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

    plan["completed_steps"] = sum(
        1 for s in steps if s.get("status") == "completed"
    )
    if plan["completed_steps"] >= plan["total_steps"]:
        plan["status"] = "completed"

    if not _write_plan(plan_id, plan):
        return {"ok": False, "error": "Failed to write plan file"}
    return {"ok": True, "step": step}


def get_plan_status(plan_id: str) -> dict[str, Any]:
    plan = _read_plan(plan_id)
    if plan is None:
        return {"ok": False, "error": f"Plan not found: {plan_id}"}
    return {"ok": True, "plan": plan}
