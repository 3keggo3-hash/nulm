"""Tests for ContextManifest and BudgetLedger."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


import time

from claude_bridge.agents.contracts import BudgetLedger, ContextManifest


def test_budget_ledger_from_allocated_within_budget():
    ledger = BudgetLedger.from_allocated(allocated=1000, consumed=300)
    assert ledger.budget_allocated == 1000
    assert ledger.budget_consumed == 300
    assert ledger.budget_remaining == 700
    assert ledger.within_budget is True


def test_budget_ledger_over_budget():
    ledger = BudgetLedger.from_allocated(allocated=1000, consumed=1500)
    assert ledger.budget_remaining == 0
    assert ledger.within_budget is False


def test_budget_ledger_zero_consumed():
    ledger = BudgetLedger.from_allocated(allocated=500)
    assert ledger.budget_consumed == 0
    assert ledger.budget_remaining == 500
    assert ledger.within_budget is True


def test_context_manifest_round_trip():
    manifest = ContextManifest(
        manifest_id="m_abc123",
        session_id="sess_xyz",
        created_at=time.time(),
        goal="Analyze codebase",
        target="src/claude_bridge",
        selected_files=("src/a.py", "src/b.py"),
        file_signatures=({"path": "src/a.py", "mtime_ns": "123"}, {"path": "src/b.py", "mtime_ns": "456"}),
        token_budget=5000,
        estimated_tokens=3200,
        digest="abc123digest",
        summary_text="Session focused on analysis",
        source_reason="function_match",
        taint="none",
        labels=("function_match",),
        duplicate_ratio=0.0,
        parent_manifest_id=None,
        budget_ledger=BudgetLedger.from_allocated(5000, 3200),
    )
    d = manifest.to_dict()
    reconstructed = ContextManifest.from_dict(d)
    assert reconstructed.manifest_id == manifest.manifest_id
    assert reconstructed.session_id == manifest.session_id
    assert reconstructed.goal == manifest.goal
    assert reconstructed.selected_files == manifest.selected_files
    assert reconstructed.budget_ledger.within_budget is True


def test_digest_deterministic_same_files_goal():
    m1 = ContextManifest(
        manifest_id="id1",
        session_id="sess",
        created_at=1.0,
        goal="analyze",
        target="src",
        file_signatures=({"path": "a.py", "mtime_ns": "1"}, {"path": "b.py", "mtime_ns": "2"}),
    )
    m2 = ContextManifest(
        manifest_id="id2",
        session_id="sess",
        created_at=2.0,
        goal="analyze",
        target="src",
        file_signatures=({"path": "a.py", "mtime_ns": "1"}, {"path": "b.py", "mtime_ns": "2"}),
    )
    assert m1.digest == m2.digest


def test_duplicate_ratio_novel():
    m1 = ContextManifest(
        manifest_id="id1",
        session_id="sess",
        created_at=1.0,
        goal="task1",
        target="src",
        selected_files=("a.py",),
        duplicate_ratio=0.0,
    )
    m2 = ContextManifest(
        manifest_id="id2",
        session_id="sess",
        created_at=2.0,
        goal="task2",
        target="src",
        selected_files=("b.py",),
        duplicate_ratio=0.0,
    )
    assert m1.duplicate_ratio == 0.0
    assert m2.duplicate_ratio == 0.0


def test_taint_user_requested():
    manifest = ContextManifest(
        manifest_id="m1",
        session_id="sess",
        created_at=time.time(),
        goal="user task",
        target="src",
        taint="user_requested",
    )
    assert manifest.taint == "user_requested"


def test_context_manifest_to_dict_has_all_fields():
    manifest = ContextManifest(
        manifest_id="m1",
        session_id="sess",
        created_at=100.0,
        goal="test goal",
        target="test target",
    )
    d = manifest.to_dict()
    assert d["manifest_id"] == "m1"
    assert d["session_id"] == "sess"
    assert d["created_at"] == 100.0
    assert d["goal"] == "test goal"
    assert d["target"] == "test target"
    assert d["selected_files"] == []
    assert d["file_signatures"] == []
    assert d["budget_ledger"]["within_budget"] is True