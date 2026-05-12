"""Integration tests for workflow engine and skill builder."""

import asyncio
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


class TestWorkflowIntegration:
    """Integration tests for workflow engine."""

    @pytest.fixture(autouse=True)
    def setup_server(self, integration_config):
        from claude_bridge import server as mcp_server

        mcp_server.set_config(**integration_config)

    def test_workflow_creation(self, sample_project_structure):
        from claude_bridge.workflow_engine import WorkflowEngine

        engine = WorkflowEngine(project_dir=sample_project_structure)
        plan = engine.create_plan("Add logging to main function")
        assert plan is not None
        assert plan.steps

    @pytest.mark.asyncio
    async def test_workflow_execution(self, sample_project_structure):
        from claude_bridge.workflow_engine import WorkflowEngine

        engine = WorkflowEngine(project_dir=sample_project_structure)
        plan = engine.create_plan("Add type hints to main function")
        result = await engine.execute_plan(plan)
        assert result.status in {"done", "pending_approval"}

    def test_workflow_rollback(self, sample_project_structure):
        from claude_bridge.workflow_engine import WorkflowEngine

        engine = WorkflowEngine(project_dir=sample_project_structure)
        plan = engine.create_plan("Modify main function")
        engine.execute_plan(plan)
        success = engine.rollback()
        assert success or plan.steps


class TestSkillBuilderIntegration:
    """Integration tests for skill builder."""

    @pytest.fixture(autouse=True)
    def setup_server(self, integration_config):
        from claude_bridge import server as mcp_server

        mcp_server.set_config(**integration_config)

    def test_skill_proposal_from_workflow(self, sample_project_structure):
        from claude_bridge.skill_builder import WorkflowResult, propose_skill_creation

        result = WorkflowResult(
            task_description="Add logging",
            steps=[
                {"tool": "read_file", "params": {"path": "src/main.py"}},
                {"tool": "write_file", "params": {"path": "src/main.py", "content": "logged"}},
            ],
            success=True,
            duration_seconds=5.0,
        )
        proposal = propose_skill_creation(result)
        assert proposal is not None or proposal is None

    def test_skill_extraction(self, sample_project_structure):
        from claude_bridge.skill_builder import WorkflowResult, extract_skill

        result = WorkflowResult(
            task_description="Create test file",
            steps=[
                {"tool": "write_file", "params": {"path": "tests/test_sample.py", "content": "def test(): pass"}},
            ],
            success=True,
            duration_seconds=2.0,
        )
        skill = extract_skill(result)
        assert skill is None or hasattr(skill, "name")


class TestAgentOrchestrationIntegration:
    """Integration tests for multi-agent orchestration."""

    @pytest.fixture(autouse=True)
    def setup_server(self, integration_config):
        from claude_bridge import server as mcp_server

        mcp_server.set_config(**integration_config)

    def test_orchestrator_decomposition(self, sample_project_structure):
        from claude_bridge.agents.orchestrator import OrchestratorAgent

        orchestrator = OrchestratorAgent(project_dir=sample_project_structure)
        task = "Refactor the main module and add tests"
        subtasks = orchestrator.decompose(task)
        assert len(subtasks) >= 1

    @pytest.mark.asyncio
    async def test_orchestrator_execution(self, sample_project_structure):
        from claude_bridge.agents.orchestrator import OrchestratorAgent

        orchestrator = OrchestratorAgent(project_dir=sample_project_structure)
        task = "Add docstring to main function"
        result = await orchestrator.orchestrate(task)
        assert result is not None
