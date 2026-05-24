"""Tests for limited behavioral enforcement policy."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

from claude_bridge.agents.dag_records import AgentDagArtifactRecord, AgentDagNodeRecord
from claude_bridge.agents.enforcement import EnforcementPolicy


def test_schema_and_policy_failures_stop() -> None:
    policy = EnforcementPolicy()

    schema = policy.decide_retry(_node("schema_failure"), max_retries=3)
    policy_failure = policy.decide_retry(_node("policy_failure"), max_retries=3)

    assert schema.action == "stop"
    assert schema.enforced is True
    assert policy_failure.action == "stop"
    assert policy_failure.enforced is True


def test_same_failure_class_cannot_retry_forever() -> None:
    decision = EnforcementPolicy().decide_retry(
        _node("unknown_failure", retry_count=2),
        max_retries=2,
    )

    assert decision.action == "stop"
    assert "retry cap" in decision.reason


def test_context_insufficiency_escalates() -> None:
    decision = EnforcementPolicy().decide_retry(
        _node("context_insufficiency"),
        max_retries=3,
    )

    assert decision.action == "escalate"
    assert decision.signal == "context_insufficiency"


def test_low_relevance_artifacts_remain_audit_only_by_default() -> None:
    low = _artifact("low", relevance_score=0.1)
    high = _artifact("high", relevance_score=0.9)
    no_signal = _artifact("no_signal")
    policy = EnforcementPolicy()

    assert policy.promotable_artifacts((low, high, no_signal)) == (high, no_signal)
    assert policy.audit_only_artifacts((low, high, no_signal)) == (low,)


def test_confidence_below_threshold_is_logged_but_not_enforced_by_default() -> None:
    decision = EnforcementPolicy(enforce_confidence=False).decide_confidence(0.1)

    assert decision.action == "audit_only"
    assert decision.enforced is False


def test_confidence_enforcement_requires_explicit_flag() -> None:
    decision = EnforcementPolicy(enforce_confidence=True).decide_confidence(0.1)

    assert decision.action == "escalate"
    assert decision.enforced is True


def test_feature_flag_can_disable_retry_enforcement() -> None:
    decision = EnforcementPolicy(enabled=False).decide_retry(
        _node("schema_failure"),
        max_retries=3,
    )

    assert decision.action == "stop"
    assert decision.enforced is False


def _node(failure_class: str, *, retry_count: int = 0) -> AgentDagNodeRecord:
    return AgentDagNodeRecord(
        node_id="node_1",
        run_id="run_1",
        task_id="task_1",
        agent_name="research_agent",
        kind="research",
        status="failed",
        retry_count=retry_count,
        failure_class=failure_class,
        created_at=1.0,
        updated_at=1.0,
    )


def _artifact(
    artifact_id: str,
    *,
    relevance_score: float | None = None,
) -> AgentDagArtifactRecord:
    metadata = {}
    if relevance_score is not None:
        metadata["relevance_score"] = relevance_score
    return AgentDagArtifactRecord(
        artifact_id=artifact_id,
        run_id="run_1",
        node_id="node_1",
        kind="finding",
        digest=f"sha256:{artifact_id}",
        summary=artifact_id,
        path="",
        created_at=1.0,
        metadata=metadata,
    )
