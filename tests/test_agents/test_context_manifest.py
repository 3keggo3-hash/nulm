"""Tests for ContextManifest and BudgetLedger."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


import ast
from pathlib import Path
import time

from claude_bridge.agents.context_manifest import build_context_manifest, duplicate_context_ratio
from claude_bridge.agents.contracts import BudgetLedger, ContextManifest
from claude_bridge.agents.contracts import TaskSpec


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
        file_signatures=(
            {"path": "src/a.py", "mtime_ns": "123"},
            {"path": "src/b.py", "mtime_ns": "456"},
        ),
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


def test_builder_creates_deterministic_digest_for_same_goal_and_files(tmp_path):
    source = tmp_path / "a.py"
    source.write_text("print('hi')\n", encoding="utf-8")
    spec = TaskSpec(
        task_id="t",
        kind="research",
        goal="analyze",
        agent_name="research_agent",
        read_set=(str(source),),
    )

    first = build_context_manifest(task=spec, run_id="run1", session_id="sess")
    second = build_context_manifest(task=spec, run_id="run2", session_id="sess")

    assert first.digest == second.digest
    assert first.manifest_id != second.manifest_id
    assert first.selected_files == (str(source),)
    assert first.source_reason == "task_read_set"


def test_builder_handles_missing_files_without_crashing(tmp_path):
    missing = tmp_path / "missing.py"
    spec = TaskSpec(
        task_id="t",
        kind="research",
        goal="analyze missing",
        agent_name="research_agent",
        read_set=(str(missing),),
    )

    manifest = build_context_manifest(task=spec, run_id="run", session_id="sess")

    assert manifest.selected_files == (str(missing),)
    assert manifest.file_signatures[0]["exists"] == "false"
    assert manifest.digest


def test_builder_uses_context_files_when_read_set_empty(tmp_path):
    source = tmp_path / "b.py"
    source.write_text("x = 1\n", encoding="utf-8")
    spec = TaskSpec(
        task_id="t",
        kind="research",
        goal="analyze context",
        agent_name="research_agent",
    )

    manifest = build_context_manifest(
        task=spec,
        run_id="run",
        session_id="sess",
        context={"selected_files": [str(source)]},
    )

    assert manifest.selected_files == (str(source),)
    assert manifest.source_reason == "context_selected_files"


def test_builder_budget_ledger_within_and_over_budget(tmp_path):
    small = tmp_path / "small.py"
    small.write_text("x = 1\n", encoding="utf-8")
    big = tmp_path / "big.py"
    big.write_text("x = '" + ("a" * 1000) + "'\n", encoding="utf-8")
    small_spec = TaskSpec(
        task_id="small",
        kind="research",
        goal="small",
        agent_name="research_agent",
        read_set=(str(small),),
    )
    big_spec = TaskSpec(
        task_id="big",
        kind="research",
        goal="big",
        agent_name="research_agent",
        read_set=(str(big),),
    )

    within = build_context_manifest(
        task=small_spec,
        run_id="run1",
        session_id="sess",
        context={"token_budget": 1000},
    )
    over = build_context_manifest(
        task=big_spec,
        run_id="run2",
        session_id="sess",
        context={"token_budget": 1},
    )

    assert within.budget_ledger.within_budget is True
    assert within.budget_ledger.budget_remaining >= 0
    assert over.budget_ledger.within_budget is False
    assert over.budget_ledger.budget_remaining == 0


def test_duplicate_context_ratio_novel_and_repeated():
    novel = duplicate_context_ratio(
        selected_files=("a.py", "b.py"),
        previous_selected_files=("c.py",),
    )
    repeated = duplicate_context_ratio(
        selected_files=("a.py", "b.py"),
        previous_selected_files=("a.py", "c.py"),
    )

    assert novel == 0.0
    assert repeated == 0.5


def test_builder_computes_duplicate_ratio_from_parent(tmp_path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("x = 1\n", encoding="utf-8")
    second.write_text("y = 2\n", encoding="utf-8")
    parent = ContextManifest(
        manifest_id="parent",
        session_id="sess",
        created_at=1.0,
        goal="parent",
        target=".",
        selected_files=(str(first),),
    )
    spec = TaskSpec(
        task_id="child",
        kind="research",
        goal="child",
        agent_name="research_agent",
        read_set=(str(first), str(second)),
    )

    manifest = build_context_manifest(
        task=spec,
        run_id="run",
        session_id="sess",
        parent_manifest=parent,
    )

    assert manifest.parent_manifest_id == "parent"
    assert manifest.duplicate_ratio == 0.5


def test_context_manifest_builder_does_not_use_broad_filesystem_scans():
    path = Path("src/claude_bridge/agents/context_manifest.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_calls = {"glob", "rglob", "walk"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden_calls
