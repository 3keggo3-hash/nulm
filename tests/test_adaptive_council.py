"""Tests for adaptive_council.py - Deactivation proposals and proposal management."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import tempfile
from pathlib import Path


from claude_bridge.adaptive_council import (
    DeactivationProposal,
    ProposalStore,
    accept_proposal,
    get_current_proposals,
    propose_deactivation,
    reject_proposal,
)
from claude_bridge.skill_comparison import ComparisonReport
from claude_bridge.stats_engine import ComparisonResult


class TestDeactivationProposal:
    def setup_method(self) -> None:
        self._proposal = DeactivationProposal(
            id="test_proposal_123",
            skill_to_deactivate="skill_a",
            replacement="skill_b",
            reason="skill_b performs 30% better",
            stats={"winner_rate": 0.85, "loser_rate": 0.55, "sample_size": 40},
            status="pending",
            created_at="2026-01-01T00:00:00Z",
            expires_at="2026-01-02T00:00:00Z",
        )

    def test_to_dict(self):
        d = self._proposal.to_dict()
        assert d["id"] == "test_proposal_123"
        assert d["skill_to_deactivate"] == "skill_a"
        assert d["replacement"] == "skill_b"
        assert d["status"] == "pending"

    def test_from_dict(self):
        data = {
            "id": "proposal_456",
            "skill_to_deactivate": "skill_x",
            "replacement": "skill_y",
            "reason": "better performance",
            "stats": {"winner_rate": 0.9, "loser_rate": 0.4},
            "status": "accepted",
            "created_at": "2026-01-01T00:00:00Z",
            "expires_at": "2026-01-02T00:00:00Z",
        }
        proposal = DeactivationProposal.from_dict(data)
        assert proposal.id == "proposal_456"
        assert proposal.skill_to_deactivate == "skill_x"
        assert proposal.status == "accepted"

    def test_is_expired_future(self):
        from datetime import datetime, timezone, timedelta

        future = datetime.now(timezone.utc) + timedelta(hours=48)
        proposal = DeactivationProposal(
            id="test",
            skill_to_deactivate="a",
            replacement="b",
            reason="test",
            stats={},
            status="pending",
            created_at="2026-01-01T00:00:00Z",
            expires_at=future.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        assert proposal.is_expired() is False

    def test_is_expired_past(self):
        proposal = DeactivationProposal(
            id="test",
            skill_to_deactivate="a",
            replacement="b",
            reason="test",
            stats={},
            status="pending",
            created_at="2025-01-01T00:00:00Z",
            expires_at="2025-01-02T00:00:00Z",
        )
        assert proposal.is_expired() is True

    def test_format_for_user(self):
        formatted = self._proposal.format_for_user()
        assert "skill_a" in formatted
        assert "skill_b" in formatted
        assert "Accept:" in formatted
        assert "Reject:" in formatted
        assert "test_proposal_123" in formatted


class TestProposalStore:
    def setup_method(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._root = Path(self._tmpdir)
        self._store = ProposalStore(root=self._root)

    def teardown_method(self) -> None:
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_save_and_load(self):
        proposal = DeactivationProposal(
            id="save_test",
            skill_to_deactivate="skill_a",
            replacement="skill_b",
            reason="test",
            stats={},
            status="pending",
            created_at="2026-01-01T00:00:00Z",
            expires_at="2026-01-02T00:00:00Z",
        )

        success, _ = self._store.save(proposal)
        assert success is True

        loaded = self._store.load("save_test")
        assert loaded is not None
        assert loaded.id == "save_test"
        assert loaded.skill_to_deactivate == "skill_a"

    def test_load_nonexistent(self):
        loaded = self._store.load("nonexistent")
        assert loaded is None

    def test_list_pending_empty(self):
        proposals = self._store.list_pending()
        assert proposals == []

    def test_list_pending_with_proposals(self):
        for i in range(3):
            proposal = DeactivationProposal(
                id=f"pending_{i}",
                skill_to_deactivate=f"skill_{i}",
                replacement="better_skill",
                reason="test",
                stats={},
                status="pending",
                created_at="2026-01-01T00:00:00Z",
                expires_at="2099-01-02T00:00:00Z",
            )
            self._store.save(proposal)

        pending = self._store.list_pending()
        assert len(pending) == 3

    def test_list_pending_excludes_accepted(self):
        proposal = DeactivationProposal(
            id="accepted_test",
            skill_to_deactivate="skill_a",
            replacement="skill_b",
            reason="test",
            stats={},
            status="accepted",
            created_at="2026-01-01T00:00:00Z",
            expires_at="2099-01-02T00:00:00Z",
        )
        self._store.save(proposal)

        pending = self._store.list_pending()
        ids = [p.id for p in pending]
        assert "accepted_test" not in ids

    def test_update_status(self):
        proposal = DeactivationProposal(
            id="status_test",
            skill_to_deactivate="skill_a",
            replacement="skill_b",
            reason="test",
            stats={},
            status="pending",
            created_at="2026-01-01T00:00:00Z",
            expires_at="2099-01-02T00:00:00Z",
        )
        self._store.save(proposal)

        updated = self._store.update_status("status_test", "accepted")
        assert updated is not None
        assert updated.status == "accepted"

    def test_delete_existing(self):
        proposal = DeactivationProposal(
            id="delete_test",
            skill_to_deactivate="skill_a",
            replacement="skill_b",
            reason="test",
            stats={},
            status="pending",
            created_at="2026-01-01T00:00:00Z",
            expires_at="2099-01-02T00:00:00Z",
        )
        self._store.save(proposal)

        success, _ = self._store.delete("delete_test")
        assert success is True

        loaded = self._store.load("delete_test")
        assert loaded is None

    def test_delete_nonexistent(self):
        success, msg = self._store.delete("nonexistent")
        assert success is False
        assert "not found" in msg


class TestProposeDeactivation:
    def setup_method(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._root = Path(self._tmpdir)
        self._store = ProposalStore(root=self._root)

    def teardown_method(self) -> None:
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_propose_deactivation_eligible(self):
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
            winner="skill_b",
            loser="skill_a",
            comparison=comparison,
            deactivation_eligible=True,
            reason="skill_b performs 30% better",
        )

        proposal_id = None

        async def run():
            nonlocal proposal_id
            proposal_id = await propose_deactivation(report, self._store)

        import asyncio

        asyncio.run(run())

        assert proposal_id is not None
        assert proposal_id.startswith("deact_")

        loaded = self._store.load(proposal_id)
        assert loaded is not None
        assert loaded.skill_to_deactivate == "skill_a"
        assert loaded.replacement == "skill_b"

    def test_propose_deactivation_not_eligible(self):
        comparison = ComparisonResult(
            valid=True,
            reason="ok",
            skill_a_rate=0.55,
            skill_b_rate=0.50,
            significant=False,
            p_value=0.1,
            z_score=0.5,
            rate_difference=0.05,
        )
        report = ComparisonReport(
            winner="none",
            loser="none",
            comparison=comparison,
            deactivation_eligible=False,
            reason="no significant difference",
        )

        proposal_id = None

        async def run():
            nonlocal proposal_id
            proposal_id = await propose_deactivation(report, self._store)

        import asyncio

        asyncio.run(run())

        assert proposal_id is None

    def test_propose_deactivation_insufficient_data(self):
        report = ComparisonReport(
            winner="insufficient_data",
            loser="skill_a",
            comparison=None,
            deactivation_eligible=False,
            reason="insufficient_data",
        )

        proposal_id = None

        async def run():
            nonlocal proposal_id
            proposal_id = await propose_deactivation(report, self._store)

        import asyncio

        asyncio.run(run())

        assert proposal_id is None


class TestAcceptRejectProposal:
    def setup_method(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._root = Path(self._tmpdir)
        self._store = ProposalStore(root=self._root)

    def teardown_method(self) -> None:
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_accept_proposal(self):
        proposal = DeactivationProposal(
            id="accept_test",
            skill_to_deactivate="skill_a",
            replacement="skill_b",
            reason="test",
            stats={},
            status="pending",
            created_at="2026-01-01T00:00:00Z",
            expires_at="2099-01-02T00:00:00Z",
        )
        self._store.save(proposal)

        success, _ = accept_proposal("accept_test", self._store)
        assert success is True

        updated = self._store.load("accept_test")
        assert updated is not None
        assert updated.status == "accepted"

    def test_reject_proposal(self):
        proposal = DeactivationProposal(
            id="reject_test",
            skill_to_deactivate="skill_a",
            replacement="skill_b",
            reason="test",
            stats={},
            status="pending",
            created_at="2026-01-01T00:00:00Z",
            expires_at="2099-01-02T00:00:00Z",
        )
        self._store.save(proposal)

        success, _ = reject_proposal("reject_test", self._store)
        assert success is True

        updated = self._store.load("reject_test")
        assert updated is not None
        assert updated.status == "rejected"

    def test_accept_nonexistent(self):
        success, msg = accept_proposal("nonexistent", self._store)
        assert success is False
        assert "not found" in msg

    def test_accept_expired_proposal(self):
        proposal = DeactivationProposal(
            id="expired_test",
            skill_to_deactivate="skill_a",
            replacement="skill_b",
            reason="test",
            stats={},
            status="pending",
            created_at="2025-01-01T00:00:00Z",
            expires_at="2025-01-02T00:00:00Z",
        )
        self._store.save(proposal)

        success, msg = accept_proposal("expired_test", self._store)
        assert success is False
        assert "expired" in msg


class TestGetCurrentProposals:
    def setup_method(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._root = Path(self._tmpdir)
        self._store = ProposalStore(root=self._root)

    def teardown_method(self) -> None:
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_get_current_proposals_empty(self):
        proposals = get_current_proposals(self._store)
        assert proposals == []

    def test_get_current_proposals_with_pending(self):
        for i in range(2):
            proposal = DeactivationProposal(
                id=f"current_{i}",
                skill_to_deactivate=f"skill_{i}",
                replacement="better",
                reason="test",
                stats={},
                status="pending",
                created_at="2026-01-01T00:00:00Z",
                expires_at="2099-01-02T00:00:00Z",
            )
            self._store.save(proposal)

        proposals = get_current_proposals(self._store)
        assert len(proposals) == 2
