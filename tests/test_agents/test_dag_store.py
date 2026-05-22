"""Tests for append-only durable agent DAG storage."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
from typing import cast

import pytest

from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.dag_records import (
    AgentDagStatus,
    AgentDagArtifactRecord,
    AgentDagNodeRecord,
    AgentDagRunRecord,
    make_artifact_id,
    make_node_id,
    make_node_idempotency_key,
)
from claude_bridge.agents.dag_store import AgentDagStore
from claude_bridge.agents.dispatcher import TaskDispatcher
from claude_bridge.agents.result import AgentResult, AgentStatus


class StoreEchoAgent(BaseAgent):
    async def execute(self, task: str, context: dict) -> AgentResult:
        return AgentResult.success(
            findings=[task],
            artifacts={"findings": {"summary": task}},
            agent_name=self.name,
        )


def test_append_and_load_run_record(tmp_path) -> None:
    store = AgentDagStore(tmp_path / "dag")
    record = AgentDagRunRecord(
        run_id="run_1",
        goal="persist",
        status="pending",
        created_at=1.0,
        updated_at=1.0,
    )

    store.append_run(record)

    assert store.load_runs() == [record]
    assert (tmp_path / "dag" / "runs.jsonl").exists()


def test_append_and_load_node_record(tmp_path) -> None:
    store = AgentDagStore(tmp_path / "dag")
    record = _node_record()

    store.append_node(record)

    assert store.load_nodes() == [record]
    assert store.load_nodes(run_id="run_1") == [record]
    assert store.load_nodes(run_id="other") == []


def test_append_and_load_artifact_record(tmp_path) -> None:
    store = AgentDagStore(tmp_path / "dag")
    node = _node_record()
    artifact = _artifact_record(node.node_id)

    store.append_artifact(artifact)

    assert store.load_artifacts() == [artifact]
    assert store.load_artifacts(run_id=node.run_id) == [artifact]


def test_reconstruct_run_includes_run_nodes_and_artifacts(tmp_path) -> None:
    store = AgentDagStore(tmp_path / "dag")
    node = _node_record()
    artifact = _artifact_record(node.node_id)
    run = AgentDagRunRecord(
        run_id=node.run_id,
        goal="reconstruct",
        status="completed",
        created_at=1.0,
        updated_at=2.0,
        root_node_ids=(node.node_id,),
    )

    store.append_run(run)
    store.append_node(node)
    store.append_artifact(artifact)
    view = store.reconstruct_run(node.run_id)

    assert view.run == run
    assert view.nodes == (node,)
    assert view.artifacts == (artifact,)
    assert view.conflicts == ()


def test_reconstruct_missing_run_raises(tmp_path) -> None:
    store = AgentDagStore(tmp_path / "dag")

    with pytest.raises(ValueError):
        store.reconstruct_run("missing")


def test_materialized_view_uses_latest_append_for_same_id(tmp_path) -> None:
    store = AgentDagStore(tmp_path / "dag")
    pending = _node_record(status="pending", updated_at=1.0)
    completed = _node_record(status="completed", updated_at=2.0)

    store.append_node(pending)
    store.append_node(completed)

    assert store.load_nodes() == [completed]


def test_store_writes_only_under_explicit_temp_path(tmp_path) -> None:
    base = tmp_path / "explicit" / "dag"
    store = AgentDagStore(base)
    store.append_run(
        AgentDagRunRecord(
            run_id="run_1",
            goal="explicit path",
            status="pending",
            created_at=1.0,
            updated_at=1.0,
        )
    )

    assert store.runs_path == base.resolve() / "runs.jsonl"
    assert store.runs_path.exists()
    assert not (tmp_path / "runs.jsonl").exists()


def test_default_dispatcher_does_not_create_dag_records(tmp_path) -> None:
    dispatcher = TaskDispatcher()
    agent = StoreEchoAgent("research_agent")

    result = asyncio.run(
        dispatcher.distribute(
            [{"id": "task_1", "task": "record nothing", "agent_name": "research_agent"}],
            [agent],
        )
    )

    assert result[0].status == AgentStatus.SUCCESS
    assert not (tmp_path / "nodes.jsonl").exists()


def test_optional_dispatcher_dag_store_records_existing_execution(tmp_path) -> None:
    store = AgentDagStore(tmp_path / "dag")
    dispatcher = TaskDispatcher(dag_store=store, dag_run_id="run_dispatch")
    agent = StoreEchoAgent("research_agent")

    result = asyncio.run(
        dispatcher.distribute(
            [
                {
                    "id": "task_1",
                    "task": "record node",
                    "agent_name": "research_agent",
                    "read_set": ["src"],
                    "write_set": ["docs"],
                }
            ],
            [agent],
        )
    )
    nodes = store.load_nodes(run_id="run_dispatch")

    assert result[0].status == AgentStatus.SUCCESS
    assert len(nodes) == 1
    assert nodes[0].status == "completed"
    assert nodes[0].task_id == "task_1"
    assert nodes[0].metadata["agent_run_id"] == dispatcher.run_records[0].run_id


def test_optional_dispatcher_store_does_not_schedule_ready_nodes(tmp_path) -> None:
    store = AgentDagStore(tmp_path / "dag")
    dispatcher = TaskDispatcher(dag_store=store, dag_run_id="run_dispatch")

    result = asyncio.run(
        dispatcher.distribute(
            [{"id": "task_1", "task": "missing", "agent_name": "missing_agent"}],
            [],
        )
    )
    nodes = store.load_nodes(run_id="run_dispatch")

    assert result[0].status == AgentStatus.FAILURE
    assert nodes == []


def _node_record(status: str = "completed", updated_at: float = 2.0) -> AgentDagNodeRecord:
    node_id = make_node_id(
        run_id="run_1",
        task_id="task_1",
        agent_name="research_agent",
        kind="research",
        read_set=("src",),
        write_set=("docs",),
    )
    return AgentDagNodeRecord(
        node_id=node_id,
        run_id="run_1",
        task_id="task_1",
        agent_name="research_agent",
        kind="research",
        status=cast(AgentDagStatus, status),
        read_set=("src",),
        write_set=("docs",),
        idempotency_key=make_node_idempotency_key(
            run_id="run_1",
            task_id="task_1",
            agent_name="research_agent",
            kind="research",
            read_set=("src",),
            write_set=("docs",),
        ),
        created_at=1.0,
        updated_at=updated_at,
    )


def _artifact_record(node_id: str) -> AgentDagArtifactRecord:
    artifact_id = make_artifact_id(
        run_id="run_1",
        node_id=node_id,
        kind="findings",
        digest="sha256:test",
    )
    return AgentDagArtifactRecord(
        artifact_id=artifact_id,
        run_id="run_1",
        node_id=node_id,
        kind="findings",
        digest="sha256:test",
        summary="summary",
        path="",
        created_at=2.0,
    )
