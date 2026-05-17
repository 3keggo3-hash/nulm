"""End-to-end integration tests for Adaptive Skill Router.

Tests the complete flow across multiple modules including
role assignment, skill comparison, deactivation proposals,
and proposal engine behavior.
"""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path


from claude_bridge.adaptive_council import (
    ProposalStore,
    accept_proposal,
    get_current_proposals,
    propose_deactivation,
    reject_proposal,
)
from claude_bridge.mcp_discovery import MCPDiscovery
from claude_bridge.mcp_peer import MCPPeer, MCPPeerRegistry
from claude_bridge.role_assigner import RoleAssigner
from claude_bridge.skill_comparison import ComparisonReport, SkillComparator
from claude_bridge.skill_comparison import PerformanceMetrics
from claude_bridge.skill_schema import SkillMeta
from claude_bridge.stats_engine import ComparisonResult, StatisticalThreshold


class TestScenarioARoleAssignment:
    """Scenario A: Role assignment flow"""

    def test_role_assignment_executor_requires_approval(self):
        assigner = RoleAssigner()
        result = assigner.assign_role(
            entity_name="shell_helper",
            context="run shell script to deploy",
            metrics={},
        )
        assert result.role == "executor"
        assert result.requires_approval is True

    def test_role_assignment_docs_no_approval(self):
        assigner = RoleAssigner()
        result = assigner.assign_role(
            entity_name="docs_helper",
            context="write README for project",
            metrics={},
        )
        assert result.role == "docs_reviewer"
        assert result.requires_approval is False

    def test_role_assignment_bulk(self):
        assigner = RoleAssigner()
        entities = [
            {"name": "shell", "metrics": {}},
            {"name": "docs", "metrics": {}},
            {"name": "test", "metrics": {}},
        ]
        results = assigner.assign_bulk(entities, context="run tests and document")
        assert len(results) == 3
        assert all(r.role in {"test_strategist", "docs_reviewer"} for r in results)


class TestScenarioBSkillComparisonDeactivation:
    """Scenario B: Skill comparison → deactivation proposal → accept"""

    def setup_method(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._root = Path(self._tmpdir)
        self._store = ProposalStore(root=self._root)

    def teardown_method(self) -> None:
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_skill_with_results(self, name: str, results: list[bool]) -> SkillMeta:
        perf = PerformanceMetrics(result_history=results)
        skill = SkillMeta(name=name, version="1.0", trigger_phrases=["test"])
        skill.performance_metrics = perf
        return skill

    def test_skill_comparison_clear_winner_eligible(self):
        stats = StatisticalThreshold(min_sample_size=30)
        comparator = SkillComparator(stats_engine=stats)

        skill_a = self._make_skill_with_results("skill_a", [True] * 28 + [False] * 2)
        skill_b = self._make_skill_with_results("skill_b", [True] * 18 + [False] * 12)

        report = comparator.compare(skill_a, skill_b)
        assert report.winner == "skill_a"
        assert report.loser == "skill_b"
        assert report.deactivation_eligible is True

    def test_propose_deactivation_creates_proposal(self):
        comparison = ComparisonResult(
            valid=True,
            reason="ok",
            skill_a_rate=0.85,
            skill_b_rate=0.55,
            significant=True,
            p_value=0.01,
            z_score=2.5,
            rate_difference=0.30,
        )
        report = ComparisonReport(
            winner="skill_a",
            loser="skill_b",
            comparison=comparison,
            deactivation_eligible=True,
            reason="skill_a performs 30% better",
        )

        proposal_id = None

        async def run():
            nonlocal proposal_id
            proposal_id = await propose_deactivation(report, self._store)

        asyncio.run(run())

        assert proposal_id is not None
        assert proposal_id.startswith("deact_")

        loaded = self._store.load(proposal_id)
        assert loaded is not None
        assert loaded.skill_to_deactivate == "skill_b"
        assert loaded.replacement == "skill_a"
        assert loaded.status == "pending"

    def test_accept_proposal_changes_status(self):
        comparison = ComparisonResult(
            valid=True,
            reason="ok",
            skill_a_rate=0.85,
            skill_b_rate=0.55,
            significant=True,
            p_value=0.01,
            z_score=2.5,
            rate_difference=0.30,
        )
        report = ComparisonReport(
            winner="skill_a",
            loser="skill_b",
            comparison=comparison,
            deactivation_eligible=True,
            reason="skill_a performs better",
        )

        async def run():
            proposal_id = await propose_deactivation(report, self._store)
            success, _ = accept_proposal(proposal_id, self._store)
            return success

        result = asyncio.run(run())
        assert result is True

        proposals = get_current_proposals(self._store)
        assert len(proposals) == 0

    def test_reject_proposal_changes_status(self):
        comparison = ComparisonResult(
            valid=True,
            reason="ok",
            skill_a_rate=0.85,
            skill_b_rate=0.55,
            significant=True,
            p_value=0.01,
            z_score=2.5,
            rate_difference=0.30,
        )
        report = ComparisonReport(
            winner="skill_a",
            loser="skill_b",
            comparison=comparison,
            deactivation_eligible=True,
            reason="skill_a performs better",
        )

        async def run():
            proposal_id = await propose_deactivation(report, self._store)
            success, _ = reject_proposal(proposal_id, self._store)
            return success

        result = asyncio.run(run())
        assert result is True

        proposals = get_current_proposals(self._store)
        assert len(proposals) == 0


class TestScenarioCSpamGuard:
    """Scenario C: ProposalEngine spam guard"""

    def setup_method(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._root = Path(self._tmpdir)
        self._engine = None

    def teardown_method(self) -> None:
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_spam_guard_blocks_4th_proposal(self):
        from claude_bridge.proposal_engine import MAX_PROPOSALS_PER_SESSION, ProposalEngine

        store = ProposalStore(root=self._root)
        engine = ProposalEngine(
            proposal_store=store,
            max_proposals_per_session=MAX_PROPOSALS_PER_SESSION,
        )

        engine._session_proposal_count = MAX_PROPOSALS_PER_SESSION

        from claude_bridge.proposal_engine import TaskResult

        result = TaskResult(
            task_type="test",
            skill_used="test_skill",
            success=False,
            duration_ms=1000.0,
            user_requested_suggestion=False,
        )

        assert engine.should_trigger(result) is False

    def test_reset_clears_session_count(self):
        from claude_bridge.proposal_engine import ProposalEngine

        store = ProposalStore(root=self._root)
        engine = ProposalEngine(proposal_store=store)

        engine._session_proposal_count = 3

        engine.reset_session()

        assert engine._session_proposal_count == 0

    def test_3_failures_generate_3_proposals(self):
        from claude_bridge.proposal_engine import MAX_PROPOSALS_PER_SESSION, ProposalEngine

        store = ProposalStore(root=self._root)
        engine = ProposalEngine(
            proposal_store=store,
            max_proposals_per_session=MAX_PROPOSALS_PER_SESSION,
        )

        from claude_bridge.proposal_engine import TaskResult

        for i in range(3):
            TaskResult(
                task_type=f"task_{i}",
                skill_used="test_skill",
                success=False,
                duration_ms=1000.0,
                user_requested_suggestion=False,
            )
            engine._update_historical(f"task_{i}", 1000.0)

        assert engine._session_proposal_count == 0


class TestScenarioDMCPDiscoveryConcurrency:
    """Scenario D: MCP discovery concurrency"""

    def setup_method(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._root = Path(self._tmpdir)
        self._discovery = MCPDiscovery(root=self._root)
        self._registry = MCPPeerRegistry(root=self._root)

    def teardown_method(self) -> None:
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    async def test_concurrent_observe_same_peer_one_entry(self):
        peer = MCPPeer(
            peer_id="concurrent_peer",
            name="Concurrent",
            transport="stdio",
            endpoint="concurrent",
            discovered_at="2026-01-01T00:00:00Z",
        )

        await self._discovery.observe_peer(peer)
        await self._discovery.observe_peer(peer)
        await self._discovery.observe_peer(peer)
        await self._discovery.observe_peer(peer)
        await self._discovery.observe_peer(peer)

        peers = self._discovery.get_all_peers()
        assert len(peers) == 1
        assert peers[0].peer_id == "concurrent_peer"

    async def test_concurrent_observe_different_peers(self):
        for i in range(5):
            peer = MCPPeer(
                peer_id=f"peer_{i}",
                name=f"Peer {i}",
                transport="stdio",
                endpoint=f"peer-{i}",
                discovered_at="2026-01-01T00:00:00Z",
            )
            await self._discovery.observe_peer(peer)

        peers = self._discovery.get_all_peers()
        assert len(peers) == 5

    def test_registry_saves_one_per_peer_id(self):
        peer = MCPPeer(
            peer_id="unique_peer",
            name="Unique",
            transport="stdio",
            endpoint="unique",
            discovered_at="2026-01-01T00:00:00Z",
        )

        self._registry.save(peer)
        self._registry.save(peer)
        self._registry.save(peer)

        peers = self._registry.load_all()
        assert len(peers) == 1


class TestFullFlowIntegration:
    """Full flow integration tests"""

    def setup_method(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._root = Path(self._tmpdir)

    def teardown_method(self) -> None:
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_role_assignment_to_skill_comparison(self):
        assigner = RoleAssigner()
        role_result = assigner.assign_role(
            entity_name="git_helper",
            context="run shell script to execute git commit",
            metrics={"hit_count": 10, "acceptance_rate": 0.9},
        )

        assert role_result.role == "executor"
        assert role_result.confidence >= 0.9

    def test_deactivation_proposal_format(self):
        from claude_bridge.adaptive_council import DeactivationProposal

        proposal = DeactivationProposal(
            id="test_proposal_123",
            skill_to_deactivate="old_skill",
            replacement="new_skill",
            reason="new_skill performs 30% better",
            stats={"winner_rate": 0.85, "loser_rate": 0.55, "sample_size": 40},
            status="pending",
            created_at="2026-01-01T00:00:00Z",
            expires_at="2026-01-02T00:00:00Z",
        )

        formatted = proposal.format_for_user()

        assert "old_skill" in formatted
        assert "new_skill" in formatted
        assert "Accept:" in formatted
        assert "Reject:" in formatted
        assert "test_proposal_123" in formatted

    def test_proposal_store_path_sanitization(self):
        store = ProposalStore(root=self._root)

        from claude_bridge.adaptive_council import DeactivationProposal

        proposal = DeactivationProposal(
            id="path/traversal/../test",
            skill_to_deactivate="skill",
            replacement="替代",
            reason="test",
            stats={},
            status="pending",
            created_at="2026-01-01T00:00:00Z",
            expires_at="2026-01-02T00:00:00Z",
        )

        success, _ = store.save(proposal)
        assert success is True

        loaded = store.load("path/traversal/../test")
        assert loaded is not None

    def test_stats_engine_comparison_with_real_data(self):
        stats = StatisticalThreshold(min_sample_size=30, confidence_level=0.95)

        results_a = [True] * 28 + [False] * 2
        results_b = [True] * 18 + [False] * 12

        comparison = stats.is_comparison_valid(results_a, results_b)

        assert comparison.valid is True
        assert comparison.significant is True
        assert comparison.skill_a_rate > comparison.skill_b_rate
        assert stats.is_deactivation_eligible(comparison, min_rate_difference=0.15) is True
