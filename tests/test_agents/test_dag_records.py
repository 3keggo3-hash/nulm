"""Tests for durable agent DAG record models."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import pytest

from claude_bridge.agents.dag_records import (
    AGENT_DAG_ARTIFACT_SCHEMA_VERSION,
    AGENT_DAG_CONFLICT_SCHEMA_VERSION,
    AGENT_DAG_NODE_SCHEMA_VERSION,
    AGENT_DAG_RUN_SCHEMA_VERSION,
    AgentDagArtifactRecord,
    AgentDagConflictRecord,
    AgentDagNodeRecord,
    AgentDagRunRecord,
    make_artifact_id,
    make_node_id,
    make_node_idempotency_key,
)


def test_run_record_round_trips() -> None:
    record = AgentDagRunRecord(
        run_id="run_1",
        goal="persist records",
        status="pending",
        created_at=1.0,
        updated_at=1.0,
        root_node_ids=("node_1",),
        metadata={"source": "test"},
    )

    loaded = AgentDagRunRecord.from_dict(record.to_dict())

    assert loaded == record
    assert loaded.to_dict()["schema_version"] == AGENT_DAG_RUN_SCHEMA_VERSION


def test_node_record_round_trips() -> None:
    record = AgentDagNodeRecord(
        node_id="node_1",
        run_id="run_1",
        task_id="task_1",
        agent_name="research_agent",
        kind="research",
        status="ready",
        node_event="node_ready",
        dependencies=("node_0",),
        read_set=("src",),
        write_set=("docs",),
        context_manifest_id="ctx_1",
        artifact_ids=("artifact_1",),
        idempotency_key="idem_1",
        lease_owner="",
        lease_expires_at=None,
        retry_count=1,
        failure_class=None,
        failure_message=None,
        created_at=1.0,
        updated_at=2.0,
        metadata={"priority": 1},
    )

    loaded = AgentDagNodeRecord.from_dict(record.to_dict())

    assert loaded == record
    assert loaded.to_dict()["schema_version"] == AGENT_DAG_NODE_SCHEMA_VERSION


def test_node_record_infers_event_from_status() -> None:
    record = AgentDagNodeRecord(
        node_id="node_1",
        run_id="run_1",
        task_id="task_1",
        agent_name="research_agent",
        kind="research",
        status="completed",
        created_at=1.0,
        updated_at=2.0,
    )

    loaded = AgentDagNodeRecord.from_dict(record.to_dict())

    assert loaded.node_event == "node_completed"


def test_invalid_node_event_raises() -> None:
    payload = AgentDagNodeRecord(
        node_id="node_1",
        run_id="run_1",
        task_id="task_1",
        agent_name="research_agent",
        kind="research",
        status="running",
        created_at=1.0,
        updated_at=2.0,
    ).to_dict()
    payload["node_event"] = "node_exploded"

    with pytest.raises(ValueError):
        AgentDagNodeRecord.from_dict(payload)


def test_artifact_record_round_trips() -> None:
    record = AgentDagArtifactRecord(
        artifact_id="artifact_1",
        run_id="run_1",
        node_id="node_1",
        kind="findings",
        digest="sha256:test",
        summary="found evidence",
        path="artifacts/findings.json",
        metadata={"format": "json"},
        created_at=3.0,
    )

    loaded = AgentDagArtifactRecord.from_dict(record.to_dict())

    assert loaded == record
    assert loaded.to_dict()["schema_version"] == AGENT_DAG_ARTIFACT_SCHEMA_VERSION


def test_conflict_record_round_trips() -> None:
    record = AgentDagConflictRecord(
        conflict_id="conflict_1",
        run_id="run_1",
        node_ids=("node_1", "node_2"),
        type="write_overlap",
        files=("src/app.py",),
        signal="same file",
        resolution="",
        created_at=4.0,
        metadata={"severity": "info"},
    )

    loaded = AgentDagConflictRecord.from_dict(record.to_dict())

    assert loaded == record
    assert loaded.to_dict()["schema_version"] == AGENT_DAG_CONFLICT_SCHEMA_VERSION


def test_invalid_schema_fails_closed() -> None:
    with pytest.raises(ValueError):
        AgentDagRunRecord.from_dict(
            {
                "schema_version": "agent_dag_run.v0",
                "run_id": "run_1",
                "goal": "bad",
                "status": "pending",
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )


def test_missing_required_field_raises() -> None:
    with pytest.raises(ValueError):
        AgentDagNodeRecord.from_dict(
            {
                "schema_version": AGENT_DAG_NODE_SCHEMA_VERSION,
                "run_id": "run_1",
                "task_id": "task_1",
                "agent_name": "research_agent",
                "kind": "research",
                "status": "pending",
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )


def test_invalid_status_raises() -> None:
    payload = AgentDagRunRecord(
        run_id="run_1",
        goal="bad status",
        status="pending",
        created_at=1.0,
        updated_at=1.0,
    ).to_dict()
    payload["status"] = "executing"

    with pytest.raises(ValueError):
        AgentDagRunRecord.from_dict(payload)


def test_node_idempotency_key_is_stable() -> None:
    kwargs = {
        "run_id": "run_1",
        "task_id": "task_1",
        "agent_name": "research_agent",
        "kind": "research",
        "read_set": ("b.py", "a.py"),
        "write_set": ("out.md",),
    }

    first = make_node_idempotency_key(**kwargs)
    second = make_node_idempotency_key(**kwargs)

    assert first == second
    assert make_node_id(**kwargs) == make_node_id(**kwargs)


def test_node_idempotency_key_changes_when_write_set_changes() -> None:
    base = {
        "run_id": "run_1",
        "task_id": "task_1",
        "agent_name": "research_agent",
        "kind": "research",
        "read_set": ("src",),
    }

    first = make_node_idempotency_key(**base, write_set=("docs/a.md",))
    second = make_node_idempotency_key(**base, write_set=("docs/b.md",))

    assert first != second


def test_artifact_id_is_deterministic() -> None:
    first = make_artifact_id(
        run_id="run_1",
        node_id="node_1",
        kind="findings",
        digest="sha256:test",
    )
    second = make_artifact_id(
        run_id="run_1",
        node_id="node_1",
        kind="findings",
        digest="sha256:test",
    )

    assert first == second
