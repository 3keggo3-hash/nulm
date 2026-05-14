"""Tests for parallel workflow execution."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from claude_bridge.workflow_engine import (
    ParallelValidationResult,
    ParallelWorkflowExecutor,
    WorkflowEngine,
    WorkflowStep,
)


@pytest.fixture
def engine() -> WorkflowEngine:
    return WorkflowEngine()


@pytest.fixture
def executor() -> ParallelWorkflowExecutor:
    return ParallelWorkflowExecutor()


class TestParallelWorkflowExecutor:
    def test_init_with_custom_max_workers(self) -> None:
        executor = ParallelWorkflowExecutor(max_workers=8)
        assert executor.max_workers == 8

    def test_init_with_default_max_workers(self) -> None:
        executor = ParallelWorkflowExecutor()
        assert executor.max_workers == 4


class TestExecuteParallelValidation:
    @pytest.mark.asyncio
    async def test_two_async_tasks_succeed_result_ok_is_true(self, executor: ParallelWorkflowExecutor) -> None:
        async def task_lint() -> dict[str, Any]:
            return {"ok": True, "output": "lint passed"}

        async def task_test() -> dict[str, Any]:
            return {"ok": True, "output": "tests passed"}

        tasks = {"lint": task_lint, "test": task_test}
        result = await executor.execute_parallel_validation(tasks)

        assert result.ok is True
        assert result.results["lint"]["ok"] is True
        assert result.results["test"]["ok"] is True
        assert result.errors == {}

    @pytest.mark.asyncio
    async def test_one_task_raises_exception_errors_contains_task_name_ok_is_false(self, executor: ParallelWorkflowExecutor) -> None:
        async def task_lint() -> dict[str, Any]:
            return {"ok": True}

        async def task_test() -> dict[str, Any]:
            raise RuntimeError("test execution failed")

        tasks = {"lint": task_lint, "test": task_test}
        result = await executor.execute_parallel_validation(tasks)

        assert result.ok is False
        assert "test" in result.errors
        assert "test" not in result.results

    @pytest.mark.asyncio
    async def test_one_task_returns_ok_false_ok_is_false(self, executor: ParallelWorkflowExecutor) -> None:
        async def task_lint() -> dict[str, Any]:
            return {"ok": True}

        async def task_test() -> dict[str, Any]:
            return {"ok": False, "error": "failed"}

        tasks = {"lint": task_lint, "test": task_test}
        result = await executor.execute_parallel_validation(tasks)

        assert result.ok is False
        assert result.results["lint"]["ok"] is True
        assert result.results["test"]["ok"] is False
        assert result.results["test"]["error"] == "failed"


class TestParallelValidationResult:
    def test_result_ok_when_all_pass(self) -> None:
        result = ParallelValidationResult(
            ok=True,
            results={"lint": {"ok": True}, "test": {"ok": True}},
            errors={},
        )
        assert result.ok is True

    def test_result_not_ok_when_errors(self) -> None:
        result = ParallelValidationResult(
            ok=False,
            results={"lint": {"ok": True}},
            errors={"test": "failed to run"},
        )
        assert result.ok is False


class TestIdentifyIndependentValidationSteps:
    def test_identifies_lint_step(self, engine: WorkflowEngine) -> None:
        engine.steps = [
            WorkflowStep(action="Run ruff lint", risk_score=10),
            WorkflowStep(action="Implement feature", risk_score=25),
        ]
        independent = engine.identify_independent_validation_steps()
        assert len(independent) == 1
        assert independent[0].action == "Run ruff lint"

    def test_identifies_typecheck_step(self, engine: WorkflowEngine) -> None:
        engine.steps = [
            WorkflowStep(action="Run mypy type check", risk_score=10),
            WorkflowStep(action="Implement feature", risk_score=25),
        ]
        independent = engine.identify_independent_validation_steps()
        assert len(independent) == 1
        assert "type" in independent[0].action.lower()

    def test_identifies_test_step(self, engine: WorkflowEngine) -> None:
        engine.steps = [
            WorkflowStep(action="Run pytest tests", risk_score=10),
            WorkflowStep(action="Implement feature", risk_score=25),
        ]
        independent = engine.identify_independent_validation_steps()
        assert len(independent) == 1
        assert "pytest" in independent[0].action.lower()

    def test_identifies_format_step(self, engine: WorkflowEngine) -> None:
        engine.steps = [
            WorkflowStep(action="Run black format", risk_score=10),
            WorkflowStep(action="Implement feature", risk_score=25),
        ]
        independent = engine.identify_independent_validation_steps()
        assert len(independent) == 1
        assert "format" in independent[0].action.lower()

    def test_identifies_multiple_validation_steps(self, engine: WorkflowEngine) -> None:
        engine.steps = [
            WorkflowStep(action="Run ruff lint", risk_score=10),
            WorkflowStep(action="Run mypy type check", risk_score=10),
            WorkflowStep(action="Run pytest tests", risk_score=10),
        ]
        independent = engine.identify_independent_validation_steps()
        assert len(independent) == 3

    def test_excludes_steps_with_files_affected(self, engine: WorkflowEngine) -> None:
        engine.steps = [
            WorkflowStep(action="Run ruff lint", risk_score=10, files_affected=["file.py"]),
            WorkflowStep(action="Run tests", risk_score=10),
        ]
        independent = engine.identify_independent_validation_steps()
        assert len(independent) == 1
        assert independent[0].action == "Run tests"

    def test_excludes_completed_steps(self, engine: WorkflowEngine) -> None:
        engine.steps = [
            WorkflowStep(action="Run ruff lint", risk_score=10, status="completed"),
            WorkflowStep(action="Run tests", risk_score=10, status="pending"),
        ]
        independent = engine.identify_independent_validation_steps()
        assert len(independent) == 1
        assert independent[0].action == "Run tests"

    def test_returns_empty_when_no_validation_steps(self, engine: WorkflowEngine) -> None:
        engine.steps = [
            WorkflowStep(action="Implement feature", risk_score=25),
            WorkflowStep(action="Read files", risk_score=5),
        ]
        independent = engine.identify_independent_validation_steps()
        assert independent == []


class TestExecuteParallelSteps:
    @pytest.mark.asyncio
    async def test_execute_parallel_steps_all_success(self, engine: WorkflowEngine) -> None:
        steps = [
            WorkflowStep(action="Run lint", risk_score=10),
            WorkflowStep(action="Run typecheck", risk_score=10),
        ]
        mock_fn = AsyncMock(return_value={"ok": True})

        result = await engine.execute_parallel_steps(steps, execute_fn=mock_fn, max_workers=2)

        assert len(result["completed"]) == 2
        assert len(result["failed"]) == 0
        assert result["errors"] == {}

    @pytest.mark.asyncio
    async def test_execute_parallel_steps_some_fail(self, engine: WorkflowEngine) -> None:
        async def mock_fn_fail(step: WorkflowStep) -> dict[str, Any]:
            if "fail" in step.action.lower():
                return {"ok": False, "error": "failed"}
            return {"ok": True}

        steps = [
            WorkflowStep(action="Run lint", risk_score=10),
            WorkflowStep(action="Run fail_test", risk_score=10),
        ]

        result = await engine.execute_parallel_steps(steps, execute_fn=mock_fn_fail, max_workers=2)

        assert len(result["completed"]) == 1
        assert len(result["failed"]) == 1
        assert "failed" in result["errors"]["Run fail_test"]

    @pytest.mark.asyncio
    async def test_execute_parallel_steps_no_execute_fn(self, engine: WorkflowEngine) -> None:
        steps = [
            WorkflowStep(action="Run lint", risk_score=10),
            WorkflowStep(action="Run typecheck", risk_score=10),
        ]

        result = await engine.execute_parallel_steps(steps, max_workers=2)

        assert len(result["completed"]) == 2
        assert len(result["failed"]) == 0

    @pytest.mark.asyncio
    async def test_execute_parallel_steps_respects_max_workers(self, engine: WorkflowEngine) -> None:
        steps = [
            WorkflowStep(action=f"Step {i}", risk_score=10)
            for i in range(8)
        ]
        mock_fn = AsyncMock(return_value={"ok": True})

        result = await engine.execute_parallel_steps(steps, execute_fn=mock_fn, max_workers=4)

        assert len(result["completed"]) == 8
        assert len(result["failed"]) == 0

    @pytest.mark.asyncio
    async def test_execute_parallel_steps_updates_step_status(self, engine: WorkflowEngine) -> None:
        steps = [
            WorkflowStep(action="Run lint", risk_score=10),
            WorkflowStep(action="Run tests", risk_score=10),
        ]
        mock_fn = AsyncMock(return_value={"ok": True})

        await engine.execute_parallel_steps(steps, execute_fn=mock_fn, max_workers=2)

        assert all(s.status == "completed" for s in steps)

    @pytest.mark.asyncio
    async def test_execute_parallel_steps_updates_step_result(self, engine: WorkflowEngine) -> None:
        steps = [
            WorkflowStep(action="Run lint", risk_score=10),
            WorkflowStep(action="Run tests", risk_score=10),
        ]
        mock_result = {"ok": True, "output": "all passed"}
        mock_fn = AsyncMock(return_value=mock_result)

        await engine.execute_parallel_steps(steps, execute_fn=mock_fn, max_workers=2)

        assert all(s.result == mock_result for s in steps)


class TestIntegrationParallelWorkflow:
    @pytest.mark.asyncio
    async def test_parallel_validation_workflow(self, engine: WorkflowEngine) -> None:
        engine.create_plan("validate code")
        engine.steps = [
            WorkflowStep(action="Run ruff lint", risk_score=10),
            WorkflowStep(action="Run mypy type check", risk_score=10),
            WorkflowStep(action="Run pytest tests", risk_score=10),
            WorkflowStep(action="Run black format", risk_score=10),
        ]

        independent = engine.identify_independent_validation_steps()
        assert len(independent) == 4

        mock_fn = AsyncMock(return_value={"ok": True})
        result = await engine.execute_parallel_steps(independent, execute_fn=mock_fn, max_workers=4)

        assert len(result["completed"]) == 4
        assert len(result["failed"]) == 0

    @pytest.mark.asyncio
    async def test_mixed_parallel_and_sequential_steps(self, engine: WorkflowEngine) -> None:
        engine.steps = [
            WorkflowStep(action="Implement feature", risk_score=25, files_affected=["file.py"]),
            WorkflowStep(action="Run ruff lint", risk_score=10),
            WorkflowStep(action="Run mypy type check", risk_score=10),
            WorkflowStep(action="Run tests", risk_score=10),
        ]

        independent = engine.identify_independent_validation_steps()
        assert len(independent) == 3

        mock_fn = AsyncMock(return_value={"ok": True})
        result = await engine.execute_parallel_steps(independent, execute_fn=mock_fn, max_workers=3)

        assert len(result["completed"]) == 3
        step = engine.steps[0]
        assert step.status == "pending"