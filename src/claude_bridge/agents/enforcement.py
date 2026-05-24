"""Limited behavioral enforcement for agent DAG runtime decisions."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from claude_bridge.agents.dag_records import AgentDagArtifactRecord, AgentDagNodeRecord

EnforcementAction = Literal["allow", "retry", "stop", "escalate", "audit_only"]


@dataclass(frozen=True)
class EnforcementDecision:
    """Recorded runtime decision for limited behavioral enforcement."""

    action: EnforcementAction
    reason: str
    signal: str
    enforced: bool = True

    def to_metadata(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "enforced": self.enforced,
            "reason": self.reason,
            "signal": self.signal,
        }


@dataclass(frozen=True)
class EnforcementPolicy:
    """Feature-flagged deterministic enforcement policy."""

    enabled: bool = True
    enforce_confidence: bool = False
    confidence_threshold: float = 0.5

    def decide_retry(
        self,
        node: AgentDagNodeRecord,
        *,
        max_retries: int,
    ) -> EnforcementDecision:
        failure_class = node.failure_class or ""
        if failure_class in {"schema_failure", "policy_failure"}:
            return EnforcementDecision(
                action="stop",
                reason=f"{failure_class} is fatal",
                signal=failure_class,
                enforced=self.enabled,
            )
        if failure_class == "context_insufficiency":
            return EnforcementDecision(
                action="escalate",
                reason="context insufficiency requires operator/context escalation",
                signal=failure_class,
                enforced=self.enabled,
            )
        if node.retry_count >= max_retries:
            return EnforcementDecision(
                action="stop",
                reason="retry cap reached for same failure class",
                signal=failure_class or "retry_cap",
                enforced=self.enabled,
            )
        return EnforcementDecision(
            action="retry",
            reason="retryable failure below cap",
            signal=failure_class or "unknown_failure",
            enforced=self.enabled,
        )

    def decide_confidence(self, confidence: float | None) -> EnforcementDecision:
        if confidence is None or confidence >= self.confidence_threshold:
            return EnforcementDecision(
                action="allow",
                reason="confidence signal absent or above threshold",
                signal="confidence",
                enforced=False,
            )
        if self.enabled and self.enforce_confidence:
            return EnforcementDecision(
                action="escalate",
                reason="confidence below threshold",
                signal="confidence",
                enforced=True,
            )
        return EnforcementDecision(
            action="audit_only",
            reason="confidence below threshold logged but not enforced",
            signal="confidence",
            enforced=False,
        )

    def promotable_artifacts(
        self,
        artifacts: tuple[AgentDagArtifactRecord, ...],
    ) -> tuple[AgentDagArtifactRecord, ...]:
        promotable = []
        for artifact in artifacts:
            score = _relevance_score(artifact)
            if score is None or score >= _relevance_threshold(artifact):
                promotable.append(artifact)
        return tuple(promotable)

    def audit_only_artifacts(
        self,
        artifacts: tuple[AgentDagArtifactRecord, ...],
    ) -> tuple[AgentDagArtifactRecord, ...]:
        audit_only = []
        for artifact in artifacts:
            score = _relevance_score(artifact)
            if score is not None and score < _relevance_threshold(artifact):
                audit_only.append(artifact)
        return tuple(audit_only)


def _relevance_score(artifact: AgentDagArtifactRecord) -> float | None:
    raw = artifact.metadata.get("relevance_score")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _relevance_threshold(artifact: AgentDagArtifactRecord) -> float:
    raw = artifact.metadata.get("relevance_threshold", 0.5)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.5
