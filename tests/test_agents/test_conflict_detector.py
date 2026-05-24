"""Tests for deterministic agent DAG conflict detection."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

from claude_bridge.agents.conflict_detector import ConflictDetector, PatchHunk, conflict_rate
from claude_bridge.agents.dag_records import AgentDagNodeRecord, make_node_id


def test_same_file_in_two_write_sets_produces_conflict() -> None:
    left = _node("left", write_set=("src/app.py",))
    right = _node("right", write_set=("src/app.py",))

    conflicts = ConflictDetector().detect_write_set_conflicts((left, right), now=1.0)

    assert len(conflicts) == 1
    assert conflicts[0].type == "overlapping_write_set"
    assert conflicts[0].files == ("src/app.py",)
    assert set(conflicts[0].node_ids) == {left.node_id, right.node_id}
    assert conflicts[0].signal == "declared write_set overlap"


def test_disjoint_files_do_not_conflict() -> None:
    left = _node("left", write_set=("src/a.py",))
    right = _node("right", write_set=("src/b.py",))

    conflicts = ConflictDetector().detect_write_set_conflicts((left, right), now=1.0)

    assert conflicts == ()


def test_overlapping_patch_ranges_produce_conflict() -> None:
    conflicts = ConflictDetector().detect_patch_conflicts(
        "run_1",
        (
            PatchHunk(node_id="node_a", file_path="src/app.py", start_line=10, end_line=20),
            PatchHunk(node_id="node_b", file_path="src/app.py", start_line=15, end_line=25),
        ),
        now=1.0,
    )

    assert len(conflicts) == 1
    assert conflicts[0].type == "overlapping_patch"
    assert conflicts[0].files == ("src/app.py",)
    assert conflicts[0].metadata["left_range"] == [10, 20]
    assert conflicts[0].metadata["right_range"] == [15, 25]


def test_non_overlapping_patch_ranges_do_not_conflict() -> None:
    conflicts = ConflictDetector().detect_patch_conflicts(
        "run_1",
        (
            PatchHunk(node_id="node_a", file_path="src/app.py", start_line=10, end_line=20),
            PatchHunk(node_id="node_b", file_path="src/app.py", start_line=21, end_line=25),
        ),
        now=1.0,
    )

    assert conflicts == ()


def test_task_boundary_ambiguity_records_different_goals_on_same_file() -> None:
    left = _node("left", write_set=("src/app.py",), goal="add auth")
    right = _node("right", write_set=("src/app.py",), goal="remove auth")

    conflicts = ConflictDetector().detect_task_boundary_conflicts((left, right), now=1.0)

    assert len(conflicts) == 1
    assert conflicts[0].type == "task_boundary_ambiguity"
    assert conflicts[0].files == ("src/app.py",)
    assert conflicts[0].metadata["left_goal"] == "add auth"
    assert conflicts[0].metadata["right_goal"] == "remove auth"


def test_conflict_rate_is_measurable() -> None:
    left = _node("left", write_set=("src/app.py",))
    right = _node("right", write_set=("src/app.py",))
    conflicts = ConflictDetector().detect_write_set_conflicts((left, right), now=1.0)

    assert conflict_rate(conflicts, node_count=2) == 0.5


def _node(
    task_id: str,
    *,
    write_set: tuple[str, ...],
    goal: str = "same goal",
) -> AgentDagNodeRecord:
    node_id = make_node_id(
        run_id="run_1",
        task_id=task_id,
        agent_name="research_agent",
        kind="research",
        read_set=("src",),
        write_set=write_set,
    )
    return AgentDagNodeRecord(
        node_id=node_id,
        run_id="run_1",
        task_id=task_id,
        agent_name="research_agent",
        kind="research",
        status="pending",
        read_set=("src",),
        write_set=write_set,
        created_at=1.0,
        updated_at=1.0,
        metadata={"goal": goal},
    )
