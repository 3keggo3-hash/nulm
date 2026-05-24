"""Tests for deterministic conflict adjudication."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

from claude_bridge.agents.adjudicator import DeterministicAdjudicator
from claude_bridge.agents.dag_records import AgentDagArtifactRecord, AgentDagConflictRecord


def test_adjudication_order_is_deterministic() -> None:
    conflict = AgentDagConflictRecord(
        conflict_id="conflict_1",
        run_id="run_1",
        node_ids=("node_a", "node_b", "node_c"),
        type="overlapping_patch",
        files=("src/app.py",),
        signal="patch hunks overlap",
        created_at=1.0,
    )
    no_tests = _artifact(
        "artifact_c",
        "node_c",
        tests_passed=False,
        verifier_passed=True,
        diff_size=1,
        risk="low",
    )
    larger_verified = _artifact(
        "artifact_b",
        "node_b",
        tests_passed=True,
        verifier_passed=True,
        diff_size=20,
        risk="low",
    )
    smaller_verified = _artifact(
        "artifact_a",
        "node_a",
        tests_passed=True,
        verifier_passed=True,
        diff_size=5,
        risk="medium",
    )

    result = DeterministicAdjudicator().adjudicate(
        conflict,
        (no_tests, larger_verified, smaller_verified),
    )

    assert result.accepted_artifact_id == "artifact_a"
    assert result.rejected_artifact_ids == ("artifact_b", "artifact_c")
    assert "deterministic order" in result.reason


def test_adjudication_never_hides_rejected_artifacts() -> None:
    conflict = AgentDagConflictRecord(
        conflict_id="conflict_1",
        run_id="run_1",
        node_ids=("node_a", "node_b"),
        type="overlapping_write_set",
        files=("src/app.py",),
        signal="write set overlap",
        created_at=1.0,
    )

    result = DeterministicAdjudicator().adjudicate(
        conflict,
        (
            _artifact("artifact_a", "node_a", user_preference_rank=2),
            _artifact("artifact_b", "node_b", user_preference_rank=1),
        ),
    )
    metadata = result.to_record_metadata()

    assert metadata["accepted_artifact_id"] == "artifact_b"
    assert metadata["rejected_artifact_ids"] == ["artifact_a"]


def _artifact(
    artifact_id: str,
    node_id: str,
    *,
    tests_passed: bool = True,
    verifier_passed: bool = True,
    diff_size: int = 1,
    risk: str = "low",
    user_preference_rank: int = 100,
) -> AgentDagArtifactRecord:
    return AgentDagArtifactRecord(
        artifact_id=artifact_id,
        run_id="run_1",
        node_id=node_id,
        kind="patch",
        digest=f"sha256:{artifact_id}",
        summary=artifact_id,
        path="",
        created_at=1.0,
        metadata={
            "diff_size": diff_size,
            "risk": risk,
            "tests_passed": tests_passed,
            "user_preference_rank": user_preference_rank,
            "verifier_passed": verifier_passed,
        },
    )
