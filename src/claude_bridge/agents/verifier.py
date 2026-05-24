"""Deterministic verifier contract for DAG verifier nodes."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from claude_bridge.agents.contracts import EvidenceRef
from claude_bridge.agents.dag_records import AgentDagArtifactRecord

VerifierNextAction = Literal["pass", "retry", "block", "ask_user"]


@dataclass(frozen=True)
class VerifierInput:
    """Inputs consumed by a deterministic verifier node."""

    task_id: str
    artifact_ids: tuple[str, ...]
    acceptance_criteria: tuple[str, ...] = ()
    expected_evidence: tuple[str, ...] = ()
    mission_brief_id: str | None = None
    test_output: str = ""


@dataclass(frozen=True)
class VerifierOutput:
    """Typed verifier result."""

    verified: bool
    failure_class: str | None
    evidence_refs: tuple[EvidenceRef, ...]
    reason: str
    next_action: VerifierNextAction

    def to_artifact(self) -> dict[str, object]:
        return {
            "verified": self.verified,
            "failure_class": self.failure_class,
            "evidence_refs": [
                {"kind": ref.kind, "ref": ref.ref, "summary": ref.summary}
                for ref in self.evidence_refs
            ],
            "reason": self.reason,
            "next_action": self.next_action,
        }


class DeterministicVerifier:
    """Small schema/artifact verifier with no provider-backed reasoning."""

    def verify(
        self,
        verifier_input: VerifierInput,
        artifacts: tuple[AgentDagArtifactRecord, ...],
    ) -> VerifierOutput:
        artifacts_by_id = {artifact.artifact_id: artifact for artifact in artifacts}
        missing = tuple(
            artifact_id
            for artifact_id in verifier_input.artifact_ids
            if artifact_id not in artifacts_by_id
        )
        if missing:
            return VerifierOutput(
                verified=False,
                failure_class="validation_failure",
                evidence_refs=(),
                reason=f"missing required artifact(s): {', '.join(missing)}",
                next_action="block",
            )
        if verifier_input.test_output and _looks_like_failed_test(verifier_input.test_output):
            return VerifierOutput(
                verified=False,
                failure_class="validation_failure",
                evidence_refs=_artifact_evidence(verifier_input.artifact_ids, artifacts_by_id),
                reason="test output indicates failure",
                next_action="block",
            )
        criteria_missing = tuple(
            criterion
            for criterion in verifier_input.acceptance_criteria
            if criterion and not _criterion_present(criterion, artifacts)
        )
        if criteria_missing:
            return VerifierOutput(
                verified=False,
                failure_class="validation_failure",
                evidence_refs=_artifact_evidence(verifier_input.artifact_ids, artifacts_by_id),
                reason=f"acceptance criteria not evidenced: {', '.join(criteria_missing)}",
                next_action="block",
            )
        evidence_refs = _artifact_evidence(verifier_input.artifact_ids, artifacts_by_id)
        if verifier_input.expected_evidence:
            evidence_refs = (
                *evidence_refs,
                *(
                    EvidenceRef(kind="expected_evidence", ref=item, summary=item)
                    for item in verifier_input.expected_evidence
                ),
            )
        return VerifierOutput(
            verified=True,
            failure_class=None,
            evidence_refs=evidence_refs,
            reason="verification passed",
            next_action="pass",
        )


def _artifact_evidence(
    artifact_ids: tuple[str, ...],
    artifacts_by_id: dict[str, AgentDagArtifactRecord],
) -> tuple[EvidenceRef, ...]:
    return tuple(
        EvidenceRef(
            kind="artifact",
            ref=artifact_id,
            summary=artifacts_by_id[artifact_id].summary,
        )
        for artifact_id in artifact_ids
        if artifact_id in artifacts_by_id
    )


def _criterion_present(criterion: str, artifacts: tuple[AgentDagArtifactRecord, ...]) -> bool:
    needle = criterion.lower()
    return any(
        needle in artifact.summary.lower()
        or needle in artifact.kind.lower()
        or needle in artifact.path.lower()
        for artifact in artifacts
    )


def _looks_like_failed_test(output: str) -> bool:
    lowered = output.lower()
    return "failed" in lowered or "error" in lowered or "traceback" in lowered
