"""Tests for the minimal read-only agent DAG scheduler."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Any

from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.dag_records import (
    AgentDagNodeRecord,
    AgentDagRunRecord,
    make_node_id,
    make_node_idempotency_key,
)
from claude_bridge.agents.dag_scheduler import AgentDagScheduler
from claude_bridge.agents.dag_store import AgentDagStore
from claude_bridge.agents.result import AgentResult


class SchedulerEchoAgent(BaseAgent):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.tasks: list[str] = []

    async def execute(self, task: str, context: dict[str, Any]) -> AgentResult:
        self.tasks.append(task)
        return AgentResult.success(
            findings=[task],
            artifacts={"findings": {"task": task}},
            agent_name=self.name,
        )


class SchedulerFailingAgent(BaseAgent):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.calls = 0

    async def execute(self, task: str, context: dict[str, Any]) -> AgentResult:
        self.calls += 1
        return AgentResult.failure(error="temporary failure", agent_name=self.name)


class SchedulerFlakyAgent(BaseAgent):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.calls = 0

    async def execute(self, task: str, context: dict[str, Any]) -> AgentResult:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary outage")
        return AgentResult.success(findings=[task], agent_name=self.name)


def test_node_with_no_dependencies_becomes_ready_and_runs(tmp_path) -> None:
    store = _store_with_run(tmp_path)
    agent = SchedulerEchoAgent("research_agent")
    node = _node("task_1", metadata={"task": "inspect repo"})
    store.append_node_record(node)

    result = AgentDagScheduler(store, [agent]).run_until_blocked("run_1", max_steps=3)
    loaded = store.latest_node_records("run_1")[0]

    assert result.ran == 1
    assert loaded.status == "completed"
    assert loaded.artifact_ids == ("findings",)
    assert agent.tasks == ["inspect repo"]
    assert store.load_run_view("run_1").run.status == "completed"


def test_node_waits_for_dependency(tmp_path) -> None:
    store = _store_with_run(tmp_path)
    first = _node("first")
    second = _node("second", dependencies=(first.node_id,))
    store.append_node_record(first)
    store.append_node_record(second)

    AgentDagScheduler(store, [SchedulerEchoAgent("research_agent")]).run_once("run_1")
    nodes = {node.task_id: node for node in store.latest_node_records("run_1")}

    assert nodes["first"].status == "completed"
    assert nodes["second"].status == "pending"


def test_node_does_not_run_after_failed_dependency(tmp_path) -> None:
    store = _store_with_run(tmp_path)
    failed = _node("failed", status="failed", failure_class="validation_failure")
    waiting = _node("waiting", dependencies=(failed.node_id,))
    store.append_node_record(failed)
    store.append_node_record(waiting)

    result = AgentDagScheduler(store, [SchedulerEchoAgent("research_agent")]).run_once("run_1")
    nodes = {node.task_id: node for node in store.latest_node_records("run_1")}

    assert result.ran == 0
    assert nodes["waiting"].status == "blocked"
    assert nodes["waiting"].failure_class == "validation_failure"


def test_missing_agent_fails_with_typed_class(tmp_path) -> None:
    store = _store_with_run(tmp_path)
    store.append_node_record(_node("missing", agent_name="missing_agent"))

    AgentDagScheduler(store, []).run_until_blocked("run_1", max_steps=2)
    loaded = store.latest_node_records("run_1")[0]

    assert loaded.status == "failed"
    assert loaded.failure_class == "agent_not_found"


def test_retryable_failure_retries_up_to_cap(tmp_path) -> None:
    store = _store_with_run(tmp_path)
    agent = SchedulerFlakyAgent("research_agent")
    store.append_node_record(_node("flaky"))

    result = AgentDagScheduler(store, [agent], max_retries=2).run_until_blocked(
        "run_1",
        max_steps=4,
    )
    loaded = store.latest_node_records("run_1")[0]

    assert result.ran == 2
    assert loaded.status == "completed"
    assert loaded.retry_count == 1


def test_retry_cap_prevents_infinite_loop(tmp_path) -> None:
    store = _store_with_run(tmp_path)
    agent = SchedulerFailingAgent("research_agent")
    store.append_node_record(_node("always_fail"))

    result = AgentDagScheduler(store, [agent], max_retries=1).run_until_blocked(
        "run_1",
        max_steps=5,
    )
    loaded = store.latest_node_records("run_1")[0]

    assert result.ran == 2
    assert agent.calls == 2
    assert loaded.status == "failed"
    assert loaded.failure_class == "unknown_failure"
    assert loaded.retry_count == 1


def test_fatal_failure_does_not_retry(tmp_path) -> None:
    store = _store_with_run(tmp_path)
    store.append_node_record(_node("fatal", status="failed", failure_class="schema_failure"))

    result = AgentDagScheduler(store, [SchedulerEchoAgent("research_agent")]).run_until_blocked(
        "run_1",
        max_steps=3,
    )
    loaded = store.latest_node_records("run_1")[0]

    assert result.ran == 0
    assert loaded.status == "failed"
    assert loaded.failure_class == "schema_failure"


def test_process_restart_reconstruction_does_not_rerun_completed_node(tmp_path) -> None:
    store = _store_with_run(tmp_path)
    agent = SchedulerEchoAgent("research_agent")
    completed = _node("done", status="completed", artifact_ids=("findings",))
    store.append_node_record(completed)

    result = AgentDagScheduler(store, [agent]).run_until_blocked("run_1", max_steps=2)
    loaded = store.latest_node_records("run_1")[0]

    assert result.ran == 0
    assert loaded.status == "completed"
    assert agent.tasks == []


def test_scheduler_blocks_mutating_node_without_running(tmp_path) -> None:
    store = _store_with_run(tmp_path)
    agent = SchedulerEchoAgent("research_agent")
    store.append_node_record(_node("mutating", write_set=("src/app.py",)))

    result = AgentDagScheduler(store, [agent]).run_once("run_1")
    loaded = store.latest_node_records("run_1")[0]

    assert result.ran == 0
    assert loaded.status == "blocked"
    assert loaded.failure_class == "policy_failure"
    assert agent.tasks == []


def test_mutation_without_write_set_is_rejected(tmp_path) -> None:
    store = _store_with_run(tmp_path)
    agent = SchedulerEchoAgent("research_agent")
    store.append_node_record(
        _node(
            "mutating_no_write_set",
            metadata={
                "task": "mutate without write set",
                "permissions": {"allow_mutation": True, "allowed_tools": ["file_write"]},
            },
        )
    )

    result = AgentDagScheduler(store, [agent]).run_once("run_1")
    loaded = store.latest_node_records("run_1")[0]

    assert result.ran == 0
    assert loaded.status == "blocked"
    assert loaded.failure_class == "policy_failure"
    assert "write_set" in (loaded.failure_message or "")
    assert agent.tasks == []


def test_mutation_without_permission_is_rejected(tmp_path) -> None:
    store = _store_with_run(tmp_path)
    agent = SchedulerEchoAgent("research_agent")
    store.append_node_record(_node("mutating_without_permission", write_set=("src/a.py",)))

    result = AgentDagScheduler(store, [agent]).run_once("run_1")
    loaded = store.latest_node_records("run_1")[0]

    assert result.ran == 0
    assert loaded.status == "blocked"
    assert loaded.failure_class == "policy_failure"
    assert "allow_mutation" in (loaded.failure_message or "")
    assert agent.tasks == []


def test_disjoint_write_sets_run_with_configured_concurrency(tmp_path) -> None:
    store = _store_with_run(tmp_path)
    agent = SchedulerEchoAgent("research_agent")
    store.append_node_record(_mutating_node("mutate_a", write_set=("src/a.py",)))
    store.append_node_record(_mutating_node("mutate_b", write_set=("src/b.py",)))

    result = AgentDagScheduler(store, [agent], concurrency=2).run_once("run_1")
    nodes = {node.task_id: node for node in store.latest_node_records("run_1")}

    assert result.ran == 2
    assert nodes["mutate_a"].status == "completed"
    assert nodes["mutate_b"].status == "completed"
    assert agent.tasks == ["mutate_a", "mutate_b"]


def test_overlapping_write_sets_are_blocked_and_recorded(tmp_path) -> None:
    store = _store_with_run(tmp_path)
    agent = SchedulerEchoAgent("research_agent")
    store.append_node_record(_mutating_node("mutate_a", write_set=("src/shared.py",)))
    store.append_node_record(_mutating_node("mutate_b", write_set=("src/shared.py",)))

    result = AgentDagScheduler(store, [agent], concurrency=2).run_once("run_1")
    nodes = {node.task_id: node for node in store.latest_node_records("run_1")}
    conflicts = store.load_conflicts("run_1")

    assert result.ran == 1
    assert result.blocked == 1
    assert nodes["mutate_a"].status == "completed"
    assert nodes["mutate_b"].status == "blocked"
    assert nodes["mutate_b"].failure_class == "policy_failure"
    assert len(conflicts) == 1
    assert conflicts[0].run_id == "run_1"
    assert conflicts[0].type == "overlapping_write_set"
    assert conflicts[0].files == ("src/shared.py",)
    assert set(conflicts[0].node_ids) == {nodes["mutate_a"].node_id, nodes["mutate_b"].node_id}
    assert conflicts[0].signal == "write_set overlaps active mutation write_set"


def test_read_only_overlap_with_mutation_write_set_is_blocked(tmp_path) -> None:
    store = _store_with_run(tmp_path)
    agent = SchedulerEchoAgent("research_agent")
    store.append_node_record(_mutating_node("mutate_a", write_set=("src/shared.py",)))
    store.append_node_record(_node("read_a", read_set=("src/shared.py",)))

    result = AgentDagScheduler(store, [agent], concurrency=2).run_once("run_1")
    nodes = {node.task_id: node for node in store.latest_node_records("run_1")}
    conflicts = store.load_conflicts("run_1")

    assert result.ran == 1
    assert nodes["mutate_a"].status == "completed"
    assert nodes["read_a"].status == "blocked"
    assert conflicts[0].type == "read_write_overlap"
    assert conflicts[0].files == ("src/shared.py",)


def _store_with_run(tmp_path) -> AgentDagStore:
    store = AgentDagStore(tmp_path / "dag")
    store.append_run_record(
        AgentDagRunRecord(
            run_id="run_1",
            goal="scheduler test",
            status="pending",
            created_at=1.0,
            updated_at=1.0,
        )
    )
    return store


def _node(
    task_id: str,
    *,
    status: str = "pending",
    agent_name: str = "research_agent",
    dependencies: tuple[str, ...] = (),
    read_set: tuple[str, ...] = ("src",),
    write_set: tuple[str, ...] = (),
    artifact_ids: tuple[str, ...] = (),
    failure_class: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AgentDagNodeRecord:
    node_id = make_node_id(
        run_id="run_1",
        task_id=task_id,
        agent_name=agent_name,
        kind="research",
        read_set=read_set,
        write_set=write_set,
    )
    return AgentDagNodeRecord(
        node_id=node_id,
        run_id="run_1",
        task_id=task_id,
        agent_name=agent_name,
        kind="research",
        status=status,  # type: ignore[arg-type]
        dependencies=dependencies,
        read_set=read_set,
        write_set=write_set,
        artifact_ids=artifact_ids,
        idempotency_key=make_node_idempotency_key(
            run_id="run_1",
            task_id=task_id,
            agent_name=agent_name,
            kind="research",
            read_set=read_set,
            write_set=write_set,
        ),
        retry_count=0,
        failure_class=failure_class,
        created_at=1.0,
        updated_at=1.0,
        metadata=metadata or {"task": task_id},
    )


def _mutating_node(task_id: str, *, write_set: tuple[str, ...]) -> AgentDagNodeRecord:
    return _node(
        task_id,
        write_set=write_set,
        metadata={
            "task": task_id,
            "permissions": {"allow_mutation": True, "allowed_tools": ["file_write"]},
        },
    )
