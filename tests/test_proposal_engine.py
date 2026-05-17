"""Tests for proposal_engine.py - ProposalEngine and task-based proposals."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock


from claude_bridge.proposal_engine import (
    Alternative,
    MAX_PROPOSALS_PER_SESSION,
    OutcomeAnalysis,
    ProposalEngine,
    TaskResult,
    create_proposal_engine,
)


class TestTaskResult:
    def test_to_dict(self):
        result = TaskResult(
            task_type="git_commit",
            skill_used="git_helper",
            success=True,
            duration_ms=1500.0,
            error_type=None,
            user_requested_suggestion=False,
        )
        d = result.to_dict()
        assert d["task_type"] == "git_commit"
        assert d["skill_used"] == "git_helper"
        assert d["success"] is True
        assert d["duration_ms"] == 1500.0


class TestOutcomeAnalysis:
    def test_from_task_result(self):
        result = TaskResult(
            task_type="shell_exec",
            skill_used="shell_helper",
            success=False,
            duration_ms=2000.0,
            error_type="timeout",
        )
        analysis = OutcomeAnalysis(
            task_type=result.task_type,
            skill_used=result.skill_used,
            success=result.success,
            duration_ms=result.duration_ms,
            error_type=result.error_type,
        )
        assert analysis.task_type == "shell_exec"
        assert analysis.success is False
        assert analysis.error_type == "timeout"


class TestAlternative:
    def test_to_dict(self):
        alt = Alternative(
            name="better_shell",
            source="mcp_peer",
            acceptance_rate=0.85,
            role="executor",
        )
        d = alt.to_dict()
        assert d["name"] == "better_shell"
        assert d["source"] == "mcp_peer"
        assert d["acceptance_rate"] == 0.85
        assert d["role"] == "executor"

    def test_default_role(self):
        alt = Alternative(name="test", source="memory", acceptance_rate=0.7)
        assert alt.role is None


class TestProposalEngine:
    def setup_method(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._root = Path(self._tmpdir)
        self._engine = create_proposal_engine(root=self._root)

    def teardown_method(self) -> None:
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_should_trigger_failure(self):
        result = TaskResult(
            task_type="git_commit",
            skill_used="git_helper",
            success=False,
            duration_ms=1000.0,
        )
        assert self._engine.should_trigger(result) is True

    def test_should_trigger_success_no_suggestion(self):
        result = TaskResult(
            task_type="git_commit",
            skill_used="git_helper",
            success=True,
            duration_ms=1000.0,
            user_requested_suggestion=False,
        )
        assert self._engine.should_trigger(result) is False

    def test_should_trigger_user_requested(self):
        result = TaskResult(
            task_type="git_commit",
            skill_used="git_helper",
            success=True,
            duration_ms=1000.0,
            user_requested_suggestion=True,
        )
        assert self._engine.should_trigger(result) is True

    def test_should_trigger_slow_task(self):
        self._engine._historical_averages["shell"] = [500.0]
        result = TaskResult(
            task_type="shell",
            skill_used="shell_helper",
            success=True,
            duration_ms=1500.0,
        )
        assert self._engine.should_trigger(result) is True

    def test_should_not_trigger_fast_task(self):
        self._engine._historical_averages["git"] = [1000.0]
        result = TaskResult(
            task_type="git",
            skill_used="git_helper",
            success=True,
            duration_ms=1200.0,
        )
        assert self._engine.should_trigger(result) is False

    def test_spam_guard_blocks_after_max(self):
        self._engine._session_proposal_count = MAX_PROPOSALS_PER_SESSION
        result = TaskResult(
            task_type="git",
            skill_used="git_helper",
            success=False,
            duration_ms=1000.0,
        )
        assert self._engine.should_trigger(result) is False

    def test_analyze_outcome(self):
        result = TaskResult(
            task_type="shell_exec",
            skill_used="shell_helper",
            success=False,
            duration_ms=2000.0,
            error_type="timeout",
        )
        analysis = self._engine.analyze_outcome(result)
        assert analysis.task_type == "shell_exec"
        assert analysis.skill_used == "shell_helper"
        assert analysis.success is False
        assert analysis.duration_ms == 2000.0
        assert analysis.error_type == "timeout"

    def test_find_best_alternative_from_memory(self):
        mock_memory = MagicMock()
        mock_memory.search_lessons.return_value = [
            MagicMock(pattern="git_commit", hits=50, solution="git_helper_v2"),
            MagicMock(pattern="git_push", hits=30, solution="git_push_v2"),
        ]

        engine = ProposalEngine(memory_store=mock_memory)

        analysis = OutcomeAnalysis(
            task_type="git_commit",
            skill_used="git_helper",
            success=False,
            duration_ms=1000.0,
            error_type=None,
        )

        alt = engine.find_best_alternative(analysis)
        assert alt is not None
        assert alt.source == "memory"

    def test_find_best_alternative_none(self):
        mock_memory = MagicMock()
        mock_memory.search_lessons.return_value = []

        mock_discovery = MagicMock()
        mock_discovery.get_observed_tools.return_value = []

        engine = ProposalEngine(
            memory_store=mock_memory,
            mcp_discovery=mock_discovery,
        )

        analysis = OutcomeAnalysis(
            task_type="unknown_task",
            skill_used=None,
            success=False,
            duration_ms=1000.0,
            error_type=None,
        )

        alt = engine.find_best_alternative(analysis)
        assert alt is None

    def test_find_best_alternative_from_discovery(self):
        mock_memory = MagicMock()
        mock_memory.search_lessons.return_value = []

        mock_discovery = MagicMock()
        mock_tool = MagicMock()
        mock_tool.name = "better_shell_tool"
        mock_tool.risk_level = "low"
        mock_discovery.get_observed_tools.return_value = [mock_tool]

        engine = ProposalEngine(
            memory_store=mock_memory,
            mcp_discovery=mock_discovery,
        )

        analysis = OutcomeAnalysis(
            task_type="shell_exec",
            skill_used="shell_helper",
            success=False,
            duration_ms=1000.0,
            error_type=None,
        )

        alt = engine.find_best_alternative(analysis)
        assert alt is not None
        assert alt.source == "mcp_peer"
        assert alt.name == "better_shell_tool"

    def test_reset_session(self):
        self._engine._session_proposal_count = 5
        self._engine.reset_session()
        assert self._engine._session_proposal_count == 0

    def test_update_historical(self):
        self._engine._update_historical("test_task", 1000.0)
        assert "test_task" in self._engine._historical_averages
        assert 1000.0 in self._engine._historical_averages["test_task"]

    def test_update_historical_trims_to_10(self):
        for i in range(15):
            self._engine._update_historical("task", float(i * 100))

        assert len(self._engine._historical_averages["task"]) == 10
        assert self._engine._historical_averages["task"][-1] == 1400.0

    async def test_record_and_propose_no_trigger(self):
        mock_mcp = MagicMock()
        mock_mcp.get_observed_tools.return_value = []

        engine = ProposalEngine(
            mcp_discovery=mock_mcp,
            proposal_store=MagicMock(),
        )

        result = TaskResult(
            task_type="git",
            skill_used="git_helper",
            success=True,
            duration_ms=1000.0,
            user_requested_suggestion=False,
        )

        await engine.record_and_propose(result)

        assert engine._session_proposal_count == 0

    async def test_record_and_propose_user_request_no_alternative(self):

        mock_memory = MagicMock()
        mock_memory.search_lessons.return_value = []
        mock_memory.add_lesson = MagicMock()

        mock_mcp = MagicMock()
        mock_mcp.get_observed_tools.return_value = []

        mock_proposals = MagicMock()
        mock_proposals.save = MagicMock(return_value=(True, ""))

        engine = ProposalEngine(
            memory_store=mock_memory,
            mcp_discovery=mock_mcp,
            proposal_store=mock_proposals,
        )

        result = TaskResult(
            task_type="git",
            skill_used="git_helper",
            success=True,
            duration_ms=1000.0,
            user_requested_suggestion=True,
        )

        await engine.record_and_propose(result)

        assert engine._session_proposal_count == 0

    async def test_record_and_propose_does_not_fabricate_statistical_proposal(self):
        mock_memory = MagicMock()
        mock_memory.search_lessons.return_value = [
            MagicMock(pattern="git_helper_v2", hits=90, solution="try git_helper_v2")
        ]
        mock_memory.add_lesson = MagicMock()

        mock_proposals = MagicMock()
        mock_proposals.save = MagicMock(return_value=(True, ""))

        engine = ProposalEngine(
            memory_store=mock_memory,
            proposal_store=mock_proposals,
        )

        result = TaskResult(
            task_type="git",
            skill_used="git_helper",
            success=False,
            duration_ms=1000.0,
        )

        await engine.record_and_propose(result)

        assert engine._session_proposal_count == 0
        mock_proposals.save.assert_not_called()

    def test_create_proposal_engine(self):
        engine = create_proposal_engine(root=self._root)
        assert engine is not None
        assert engine._memory is not None
        assert engine._proposals is not None

    def test_matches_task_type(self):
        assert self._engine._matches_task_type("git_commit", "shell") is True
        assert self._engine._matches_task_type("file_read", "search") is True
        assert self._engine._matches_task_type("unknown", "xyz") is False
