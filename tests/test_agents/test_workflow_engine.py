"""Tests for workflow engine orchestrator executor."""

import pytest

from claude_bridge.workflow_engine import OrchestratorExecutor, WorkflowEngine
from claude_bridge.agents.orchestrator import OrchestratorAgent
from claude_bridge.agents.sub import ResearchAgent


@pytest.mark.asyncio
async def test_orchestrator_executor_init():
    orchestrator = OrchestratorAgent()
    executor = OrchestratorExecutor(orchestrator)

    assert executor.orchestrator.name == "orchestrator"


@pytest.mark.asyncio
async def test_orchestrator_executor_execute():
    orchestrator = OrchestratorAgent()
    executor = OrchestratorExecutor(orchestrator)

    result = await executor.execute_workflow_task(
        "analyze the codebase",
        [ResearchAgent()],
    )

    assert result["status"] == "success"
    assert result["agent_name"] == "orchestrator"


def test_workflow_engine_init():
    engine = WorkflowEngine()
    assert engine.state.value == "idle"


def test_workflow_engine_create_plan():
    engine = WorkflowEngine()
    steps = engine.create_plan("fix bug in code")

    assert len(steps) > 0
    assert engine.state.value == "planning"


def test_workflow_engine_decompose_fix():
    engine = WorkflowEngine()
    steps = engine._decompose_task("fix the error")

    assert len(steps) == 4
    assert any("Identify" in s.action for s in steps)


def test_workflow_engine_decompose_create():
    engine = WorkflowEngine()
    steps = engine._decompose_task("create new feature")

    assert len(steps) == 4
    assert any("Implement" in s.action for s in steps)


def test_workflow_engine_decompose_refactor():
    engine = WorkflowEngine()
    steps = engine._decompose_task("refactor the code")

    assert len(steps) == 4
    assert any("checkpoint" in s.action.lower() for s in steps)


def test_workflow_engine_reset():
    engine = WorkflowEngine()
    engine.create_plan("test task")
    engine.reset()

    assert engine.state.value == "idle"
    assert len(engine.steps) == 0


def test_workflow_engine_get_status():
    engine = WorkflowEngine()
    engine.create_plan("test task")

    status = engine.get_status()

    assert status["state"] == "planning"
    assert status["task"] == "test task"
    assert status["total_steps"] > 0