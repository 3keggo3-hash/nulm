"""Tests for workflow_engine.py."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from claude_bridge.agents.result import AgentResult
from claude_bridge.workflow_engine import (
    OrchestratorExecutor,
    WorkflowEngine,
    WorkflowState,
    WorkflowStep,
)


@pytest.fixture
def engine() -> WorkflowEngine:
    return WorkflowEngine()


@pytest.fixture
def mock_orchestrator() -> Any:
    orchestrator = AsyncMock()
    orchestrator.orchestrate = AsyncMock(return_value={"ok": True, "result": "done"})
    return orchestrator


class TestWorkflowState:
    def test_initial_state_is_idle(self, engine: WorkflowEngine) -> None:
        assert engine.state == WorkflowState.IDLE

    def test_state_transition_valid(self, engine: WorkflowEngine) -> None:
        engine.transition_to(WorkflowState.PLANNING)
        assert engine.state == WorkflowState.PLANNING

    def test_state_transition_invalid_raises(self, engine: WorkflowEngine) -> None:
        with pytest.raises(ValueError, match="Invalid transition"):
            engine.transition_to(WorkflowState.REPORTING)

    def test_state_transition_idle_to_planning(self, engine: WorkflowEngine) -> None:
        engine.transition_to(WorkflowState.PLANNING)
        assert engine.state == WorkflowState.PLANNING


class TestWorkflowStep:
    def test_workflow_step_to_dict(self) -> None:
        step = WorkflowStep(
            action="test action",
            files_affected=["file1.py"],
            risk_score=25,
            rollback_plan="revert",
            status="completed",
            result={"ok": True},
        )
        d = step.to_dict()
        assert d["action"] == "test action"
        assert d["files_affected"] == ["file1.py"]
        assert d["risk_score"] == 25
        assert d["rollback_plan"] == "revert"
        assert d["status"] == "completed"
        assert d["result"] == {"ok": True}


class TestWorkflowEngine:
    def test_create_plan_sets_task_and_state(self, engine: WorkflowEngine) -> None:
        engine.create_plan("fix bug in auth")
        assert engine.task == "fix bug in auth"
        assert engine.state == WorkflowState.PLANNING
        assert len(engine.steps) > 0

    def test_create_plan_for_create_task(self, engine: WorkflowEngine) -> None:
        steps = engine.create_plan("create new feature")
        assert len(steps) == 4
        assert all(s.risk_score > 0 for s in steps)

    def test_create_plan_for_fix_task(self, engine: WorkflowEngine) -> None:
        steps = engine.create_plan("fix bug in login")
        assert len(steps) == 4

    def test_create_plan_for_refactor_task(self, engine: WorkflowEngine) -> None:
        steps = engine.create_plan("refactor auth module")
        assert len(steps) == 4
        assert any("checkpoint" in s.action.lower() for s in steps)

    def test_reset_clears_state(self, engine: WorkflowEngine) -> None:
        engine.create_plan("some task")
        engine.reset()
        assert engine.state == WorkflowState.IDLE
        assert engine.steps == []
        assert engine.task == ""

    def test_get_status_returns_dict(self, engine: WorkflowEngine) -> None:
        engine.create_plan("test task")
        status = engine.get_status()
        assert "state" in status
        assert "task" in status
        assert "steps" in status
        assert status["state"] == "planning"


class TestTransitionToReporting:
    @pytest.mark.asyncio
    async def test_transition_to_reporting_from_testing(self, engine: WorkflowEngine) -> None:
        engine.state = WorkflowState.TESTING
        with patch.object(engine, "_run_self_review", new_callable=AsyncMock) as mock_review:
            mock_review.return_value = {
                "status": "pass",
                "verdict": "ok",
                "summary": "good",
                "warnings": [],
                "errors": [],
            }
            result = await engine.transition_to_reporting()
        assert result.get("ok") is True
        assert engine.state == WorkflowState.REPORTING

    @pytest.mark.asyncio
    async def test_transition_to_reporting_fails_self_review(self, engine: WorkflowEngine) -> None:
        engine.state = WorkflowState.TESTING
        with patch.object(engine, "_run_self_review", new_callable=AsyncMock) as mock_review:
            mock_review.return_value = {
                "status": "fail",
                "verdict": "needs_followup",
                "summary": "issues found",
                "warnings": [],
                "errors": ["issues found"],
            }
            result = await engine.transition_to_reporting()
        assert result.get("ok") is False
        assert result.get("review", {}).get("status") == "fail"

    @pytest.mark.asyncio
    async def test_transition_to_reporting_raises_if_not_testing(
        self, engine: WorkflowEngine
    ) -> None:
        engine.state = WorkflowState.PLANNING
        with pytest.raises(ValueError, match="Cannot transition from"):
            await engine.transition_to_reporting()

    @pytest.mark.asyncio
    async def test_transition_to_reporting_with_warnings(self, engine: WorkflowEngine) -> None:
        engine.state = WorkflowState.TESTING
        with patch.object(engine, "_run_self_review", new_callable=AsyncMock) as mock_review:
            mock_review.return_value = {
                "status": "pass",
                "verdict": "approved",
                "summary": "ok",
                "warnings": ["minor note"],
                "errors": [],
            }
            result = await engine.transition_to_reporting()
        assert result.get("ok") is True
        assert result.get("review", {}).get("status") == "pass"


class TestRollback:
    def test_rollback_returns_error_when_no_checkpoint(self, engine: WorkflowEngine) -> None:
        result = engine.rollback()
        assert result.get("ok") is False
        assert "No checkpoint" in result.get("error", "")

    def test_rollback_with_checkpoint(self, engine: WorkflowEngine) -> None:
        engine.checkpoint_name = "nonexistent_checkpoint"
        with patch(
            "claude_bridge.workflow_engine.restore_checkpoint",
            return_value={"ok": False, "error": "not found"},
        ):
            result = engine.rollback()
        assert result.get("ok") is False

    @pytest.mark.asyncio
    async def test_execute_plan_reaches_done(self, engine: WorkflowEngine) -> None:
        plan = engine.create_plan("Fix bug in shell workflow")
        result = await engine.execute_plan(plan, request_approval_fn=AsyncMock(return_value=True))

        assert result.status == "done"
        assert engine.state == WorkflowState.DONE
        assert all(step.status == "completed" for step in engine.steps)


class TestOrchestratorExecutor:
    @pytest.mark.asyncio
    async def test_execute_workflow_task_with_agent_result(self, mock_orchestrator: Any) -> None:
        executor = OrchestratorExecutor(mock_orchestrator)
        mock_orchestrator.orchestrate = AsyncMock(
            return_value=AgentResult.success(findings=["done"])
        )
        result = await executor.execute_workflow_task("test task", [])
        assert result.get("ok") is True

    @pytest.mark.asyncio
    async def test_execute_workflow_task_with_dict_result(self, mock_orchestrator: Any) -> None:
        executor = OrchestratorExecutor(mock_orchestrator)
        mock_orchestrator.orchestrate = AsyncMock(return_value={"ok": True, "data": 123})
        result = await executor.execute_workflow_task("test task", [])
        assert result.get("ok") is True
        assert result.get("data") == 123

    @pytest.mark.asyncio
    async def test_execute_workflow_task_fallback_to_string(self, mock_orchestrator: Any) -> None:
        executor = OrchestratorExecutor(mock_orchestrator)
        mock_orchestrator.orchestrate = AsyncMock(return_value="simple result")
        result = await executor.execute_workflow_task("test task", [])
        assert result.get("ok") is True
        assert "result" in result


class TestRequestApproval:
    @pytest.mark.asyncio
    async def test_request_approval_accepted(self, engine: WorkflowEngine) -> None:
        engine.create_plan("test task")
        mock_fn = AsyncMock(return_value=True)
        result = await engine.request_approval_for_plan(mock_fn)
        assert result is True
        assert engine.state == WorkflowState.APPLYING

    @pytest.mark.asyncio
    async def test_request_approval_rejected(self, engine: WorkflowEngine) -> None:
        engine.create_plan("test task")
        mock_fn = AsyncMock(return_value=False)
        result = await engine.request_approval_for_plan(mock_fn)
        assert result is False
        assert engine.state == WorkflowState.REJECTED


class TestExecuteStep:
    @pytest.mark.asyncio
    async def test_execute_step_with_high_risk_creates_checkpoint(
        self, engine: WorkflowEngine
    ) -> None:
        step = WorkflowStep(action="risky action", risk_score=65)
        mock_fn = AsyncMock(return_value={"ok": True})
        with patch(
            "claude_bridge.workflow_engine.create_checkpoint", return_value={"ok": True}
        ) as mock_cp:
            await engine.execute_step(step, mock_fn)
            mock_cp.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_step_low_risk_no_checkpoint(self, engine: WorkflowEngine) -> None:
        step = WorkflowStep(action="safe action", risk_score=30)
        mock_fn = AsyncMock(return_value={"ok": True})
        with patch("claude_bridge.workflow_engine.create_checkpoint") as mock_cp:
            await engine.execute_step(step, mock_fn)
            mock_cp.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_step_failure(self, engine: WorkflowEngine) -> None:
        step = WorkflowStep(action="failing action", risk_score=20)
        mock_fn = AsyncMock(return_value={"ok": False, "error": "failed"})
        result = await engine.execute_step(step, mock_fn)
        assert result is False
        assert step.status == "failed"
