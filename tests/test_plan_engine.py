"""Tests for JSON plan engine boundaries."""

from __future__ import annotations

import json

from claude_bridge import plan_engine as pe


def test_execute_step_rejects_invalid_plan_id(temp_project) -> None:
    result = pe.execute_step("../outside", 0)

    assert result["ok"] is False
    assert result["error"] == "Invalid plan_id"


def test_get_plan_status_rejects_invalid_plan_id(temp_project) -> None:
    result = pe.get_plan_status("not-a-plan-id")

    assert result["ok"] is False
    assert result["error"] == "Invalid plan_id"


def test_plan_lifecycle_uses_hex_plan_id(temp_project) -> None:
    created = pe.create_plan("ship feature", json.dumps(["inspect", "test"]))
    plan_id = created["plan"]["plan_id"]

    assert created["ok"] is True
    assert len(plan_id) == 32

    executed = pe.execute_step(plan_id, 0)
    status = pe.get_plan_status(plan_id)

    assert executed["ok"] is True
    assert status["ok"] is True
    assert status["plan"]["completed_steps"] == 1
