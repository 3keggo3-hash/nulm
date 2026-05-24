"""Tests for deterministic DAG verifier nodes."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Any

from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.dag_records import (
    AgentDagArtifactRecord,
    AgentDagNodeRecord,
    AgentDagRunRecord,
    make_artifact_id,
    make_node_id,
    make_node_idempotency_key,
)
from claude_bridge.agents.dag_scheduler import AgentDagScheduler
from claude_bridge.agents.dag_store import AgentDagStore
from claude_bridge.agents.result import AgentResult
from claude_bridge.agents.verifier import DeterministicVerifier, VerifierInput


class MutatingAgent(BaseAgent):
    async def execute(self, task: str, context: dict[str, Any]) -> AgentResult:
        return AgentResult.success(
            findings=[task],
            artifacts={"mutation": {"task": task}},
            agent_name=self.name,
        )


def test_verifier_passes_when_required_artifact_exists(tmp_path) -> None:
    store = _store_with_run(tmp_path)
    artifact = _artifact("artifact_1", summary="criterion met")
    verifier = _verifier_node("verify", artifact_ids=(artifact.artifact_id,))
    store.append_artifact_record(artifact)
    store.append_node_record(verifier)

    result = AgentDagScheduler(store, []).run_until_blocked("run_1", max_steps=2)
    loaded = store.latest_node_records("run_1")[0]

    assert result.ran == 1
    assert loaded.status == "completed"
    assert loaded.artifact_ids == ("verification",)
    assert loaded.metadata["verifier_output"]["verified"] is True
    assert loaded.metadata["verifier_output"]["evidence_refs"][0]["ref"] == artifact.artifact_id


def test_verifier_fails_when_required_artifact_missing(tmp_path) -> None:
    store = _store_with_run(tmp_path)
    store.append_node_record(_verifier_node("verify", artifact_ids=("missing_artifact",)))

    result = AgentDagScheduler(store, []).run_until_blocked("run_1", max_steps=2)
    loaded = store.latest_node_records("run_1")[0]

    assert result.ran == 1
    assert loaded.status == "failed"
    assert loaded.failure_class == "validation_failure"
    assert "missing_artifact" in (loaded.failure_message or "")
    assert loaded.metadata["verifier_output"]["next_action"] == "block"


def test_verifier_cannot_mutate(tmp_path) -> None:
    store = _store_with_run(tmp_path)
    store.append_node_record(_verifier_node("verify", write_set=("src/app.py",)))

    result = AgentDagScheduler(store, []).run_once("run_1")
    loaded = store.latest_node_records("run_1")[0]

    assert result.ran == 0
    assert loaded.status == "blocked"
    assert loaded.failure_class == "policy_failure"


def test_mutating_dag_requires_verifier_pass_before_final_success(tmp_path) -> None:
    store = _store_with_run(tmp_path)
    mutation = _mutating_node("mutate")
    store.append_node_record(mutation)
    scheduler = AgentDagScheduler(store, [MutatingAgent("research_agent")])

    scheduler.run_until_blocked("run_1", max_steps=2)
    mutation = store.latest_node_records("run_1")[0]

    assert mutation.status == "completed"
    assert store.load_run_view("run_1").run.status == "pending"

    artifact = _artifact(mutation.artifact_ids[0], node_id=mutation.node_id)
    verifier = _verifier_node(
        "verify_mutation",
        dependencies=(mutation.node_id,),
        artifact_ids=mutation.artifact_ids,
        metadata={"verifies_node_id": mutation.node_id},
    )
    store.append_artifact_record(artifact)
    store.append_node_record(verifier)

    scheduler.run_until_blocked("run_1", max_steps=3)

    view = store.load_run_view("run_1")
    assert {node.task_id: node.status for node in view.nodes} == {
        "mutate": "completed",
        "verify_mutation": "completed",
    }
    assert view.run.status == "completed"


def test_same_verifier_failure_does_not_retry_indefinitely(tmp_path) -> None:
    store = _store_with_run(tmp_path)
    store.append_node_record(_verifier_node("verify", artifact_ids=("missing_artifact",)))

    result = AgentDagScheduler(store, [], max_retries=5).run_until_blocked(
        "run_1",
        max_steps=5,
    )
    loaded = store.latest_node_records("run_1")[0]

    assert result.ran == 1
    assert loaded.status == "failed"
    assert loaded.failure_class == "validation_failure"
    assert loaded.retry_count == 0


def test_deterministic_verifier_checks_acceptance_criteria() -> None:
    artifact = _artifact("artifact_1", summary="implemented login behavior")
    output = DeterministicVerifier().verify(
        VerifierInput(
            task_id="verify",
            artifact_ids=(artifact.artifact_id,),
            acceptance_criteria=("login behavior",),
        ),
        (artifact,),
    )

    assert output.verified is True
    assert output.evidence_refs[0].ref == artifact.artifact_id


def _store_with_run(tmp_path) -> AgentDagStore:
    store = AgentDagStore(tmp_path / "dag")
    store.append_run_record(
        AgentDagRunRecord(
            run_id="run_1",
            goal="verifier test",
            status="pending",
            created_at=1.0,
            updated_at=1.0,
        )
    )
    return store


def _verifier_node(
    task_id: str,
    *,
    dependencies: tuple[str, ...] = (),
    artifact_ids: tuple[str, ...] = (),
    write_set: tuple[str, ...] = (),
    metadata: dict[str, Any] | None = None,
) -> AgentDagNodeRecord:
    merged_metadata = {"artifact_ids": list(artifact_ids)}
    if metadata:
        merged_metadata.update(metadata)
    return _node(
        task_id,
        kind="verifier",
        agent_name="verification_agent",
        dependencies=dependencies,
        write_set=write_set,
        metadata=merged_metadata,
    )


def _mutating_node(task_id: str) -> AgentDagNodeRecord:
    return _node(
        task_id,
        write_set=("src/app.py",),
        metadata={
            "task": task_id,
            "permissions": {"allow_mutation": True, "allowed_tools": ["file_write"]},
        },
    )


def _node(
    task_id: str,
    *,
    kind: str = "research",
    agent_name: str = "research_agent",
    dependencies: tuple[str, ...] = (),
    write_set: tuple[str, ...] = (),
    metadata: dict[str, Any] | None = None,
) -> AgentDagNodeRecord:
    node_id = make_node_id(
        run_id="run_1",
        task_id=task_id,
        agent_name=agent_name,
        kind=kind,
        read_set=("src",),
        write_set=write_set,
    )
    return AgentDagNodeRecord(
        node_id=node_id,
        run_id="run_1",
        task_id=task_id,
        agent_name=agent_name,
        kind=kind,
        status="pending",
        dependencies=dependencies,
        read_set=("src",),
        write_set=write_set,
        idempotency_key=make_node_idempotency_key(
            run_id="run_1",
            task_id=task_id,
            agent_name=agent_name,
            kind=kind,
            read_set=("src",),
            write_set=write_set,
        ),
        created_at=1.0,
        updated_at=1.0,
        metadata=metadata or {"task": task_id},
    )


def _artifact(
    artifact_id: str,
    *,
    node_id: str = "node_1",
    summary: str = "summary",
) -> AgentDagArtifactRecord:
    resolved_id = artifact_id or make_artifact_id(
        run_id="run_1",
        node_id=node_id,
        kind="findings",
        digest="sha256:test",
    )
    return AgentDagArtifactRecord(
        artifact_id=resolved_id,
        run_id="run_1",
        node_id=node_id,
        kind="findings",
        digest="sha256:test",
        summary=summary,
        path="",
        created_at=2.0,
    )
