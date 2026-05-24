"""Deterministic conflict adjudication helpers."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from claude_bridge.agents.dag_records import AgentDagArtifactRecord, AgentDagConflictRecord


@dataclass(frozen=True)
class AdjudicationResult:
    """Deterministic adjudication result that keeps rejected artifacts visible."""

    conflict_id: str
    accepted_artifact_id: str
    rejected_artifact_ids: tuple[str, ...]
    reason: str

    def to_record_metadata(self) -> dict[str, Any]:
        return {
            "accepted_artifact_id": self.accepted_artifact_id,
            "rejected_artifact_ids": list(self.rejected_artifact_ids),
            "reason": self.reason,
        }


class DeterministicAdjudicator:
    """Rank candidate artifacts using fixed non-LLM ordering."""

    def adjudicate(
        self,
        conflict: AgentDagConflictRecord,
        artifacts: tuple[AgentDagArtifactRecord, ...],
    ) -> AdjudicationResult:
        candidates = [
            artifact
            for artifact in artifacts
            if artifact.node_id in conflict.node_ids
            or artifact.artifact_id in _candidate_ids(conflict)
        ]
        if not candidates:
            raise ValueError("no candidate artifacts for adjudication")
        ranked = sorted(candidates, key=_artifact_rank)
        accepted = ranked[0]
        rejected = tuple(artifact.artifact_id for artifact in ranked[1:])
        return AdjudicationResult(
            conflict_id=conflict.conflict_id,
            accepted_artifact_id=accepted.artifact_id,
            rejected_artifact_ids=rejected,
            reason="deterministic order: tests, verifier, diff size, risk, preference, id",
        )


def _candidate_ids(conflict: AgentDagConflictRecord) -> tuple[str, ...]:
    raw = conflict.metadata.get("artifact_ids")
    if not isinstance(raw, list | tuple | set):
        return ()
    return tuple(str(item) for item in raw if str(item))


def _artifact_rank(artifact: AgentDagArtifactRecord) -> tuple[int, int, int, int, int, str]:
    metadata = artifact.metadata
    tests_rank = 0 if metadata.get("tests_passed") is True else 1
    verifier_rank = 0 if metadata.get("verifier_passed") is True else 1
    diff_size = _int_metadata(metadata, "diff_size", 1_000_000)
    risk = _risk_rank(str(metadata.get("risk", "high")))
    preference = _int_metadata(metadata, "user_preference_rank", 1_000_000)
    return (tests_rank, verifier_rank, diff_size, risk, preference, artifact.artifact_id)


def _risk_rank(value: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(value, 3)


def _int_metadata(metadata: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(metadata.get(key, default))
    except (TypeError, ValueError):
        return default
