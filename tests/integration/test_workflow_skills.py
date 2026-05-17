"""Integration tests for workflow engine and skill builder."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


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
        assert plan

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
        assert plan
        success = engine.rollback()
        assert success.get("ok") is False or plan


class TestSkillBuilderIntegration:
    """Integration tests for skill builder."""

    @pytest.fixture(autouse=True)
    def setup_server(self, integration_config):
        from claude_bridge import server as mcp_server

        mcp_server.set_config(**integration_config)

    def test_skill_proposal_from_workflow(self, sample_project_structure):
        from claude_bridge.skill_builder import extract_skill

        result = {
            "task": "Add logging",
            "steps": [
                {"tool": "read_file", "params": {"path": "src/main.py"}},
                {"tool": "write_file", "params": {"path": "src/main.py", "content": "logged"}},
                {"tool": "run_shell", "params": {"command": "pytest"}},
            ],
            "outcome": "success",
            "artifacts": {},
        }
        skill_json, skill_code = extract_skill(result)
        assert skill_json is not None
        assert skill_code is not None

    def test_skill_extraction(self, sample_project_structure):
        from claude_bridge.skill_builder import extract_skill

        result = {
            "task": "Create test file",
            "steps": [
                {
                    "tool": "write_file",
                    "params": {"path": "tests/test_sample.py", "content": "def test(): pass"},
                },
                {"tool": "run_shell", "params": {"command": "pytest tests/test_sample.py"}},
                {"tool": "read_file", "params": {"path": "tests/test_sample.py"}},
            ],
            "outcome": "success",
            "artifacts": {},
        }
        skill_json, skill_code = extract_skill(result)
        assert skill_json is not None
        assert skill_code is not None


class TestAgentOrchestrationIntegration:
    """Integration tests for multi-agent orchestration."""

    @pytest.fixture(autouse=True)
    def setup_server(self, integration_config):
        from claude_bridge import server as mcp_server

        mcp_server.set_config(**integration_config)

    @pytest.mark.asyncio
    async def test_orchestrator_decomposition(self, sample_project_structure):
        from claude_bridge.agents.orchestrator import OrchestratorAgent

        orchestrator = OrchestratorAgent()
        task = "Refactor the main module and add tests"
        subtasks = await orchestrator.decompose(task)
        assert len(subtasks) >= 1

    @pytest.mark.asyncio
    async def test_orchestrator_execution(self, sample_project_structure):
        from claude_bridge.agents.orchestrator import OrchestratorAgent
        from claude_bridge.agents.sub.research_agent import ResearchAgent

        orchestrator = OrchestratorAgent()
        task = "Add docstring to main function"
        result = await orchestrator.orchestrate(task, [ResearchAgent()])
        assert result is not None
