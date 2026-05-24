"""Minimal deterministic scheduler for read-only agent DAG nodes."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Literal, cast

from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.contracts import TaskPermissions
from claude_bridge.agents.dag_records import (
    AgentDagConflictRecord,
    AgentDagNodeRecord,
    AgentDagRunRecord,
    make_agent_dag_id,
)
from claude_bridge.agents.dag_store import AgentDagRunView, AgentDagStore
from claude_bridge.agents.enforcement import EnforcementPolicy
from claude_bridge.agents.result import AgentResult, AgentStatus
from claude_bridge.agents.verifier import DeterministicVerifier, VerifierInput

AgentDagFailureClass = Literal[
    "agent_not_found",
    "schema_failure",
    "policy_failure",
    "transient_error",
    "context_insufficiency",
    "validation_failure",
    "unknown_failure",
]

FATAL_FAILURE_CLASSES: frozenset[str] = frozenset(
    {
        "agent_not_found",
        "schema_failure",
        "policy_failure",
        "validation_failure",
    }
)
RETRYABLE_FAILURE_CLASSES: frozenset[str] = frozenset(
    {
        "transient_error",
        "context_insufficiency",
        "unknown_failure",
    }
)


@dataclass(frozen=True)
class AgentDagSchedulerResult:
    """Summary of one scheduler pass."""

    ran: int = 0
    ready: int = 0
    completed: int = 0
    failed: int = 0
    blocked: int = 0

    @property
    def made_progress(self) -> bool:
        return self.ran > 0 or self.ready > 0 or self.blocked > 0


class AgentDagScheduler:
    """Execute dependency-ordered read-only DAG nodes from durable records."""

    def __init__(
        self,
        store: AgentDagStore,
        agents: list[BaseAgent],
        *,
        worker_id: str = "agent_dag_scheduler",
        max_retries: int = 2,
        lease_seconds: int = 60,
        concurrency: int = 1,
        enforcement_policy: EnforcementPolicy | None = None,
    ) -> None:
        self.store = store
        self.agents = {agent.name: agent for agent in agents}
        self.worker_id = worker_id
        self.max_retries = max(0, max_retries)
        self.lease_seconds = max(1, lease_seconds)
        self.concurrency = max(1, concurrency)
        self.verifier = DeterministicVerifier()
        self.enforcement_policy = enforcement_policy or EnforcementPolicy()

    def run_once(self, run_id: str) -> AgentDagSchedulerResult:
        """Run at most one conservative scheduler pass for a DAG run."""
        view = self.store.load_run_view(run_id)
        node_by_id = {node.node_id: node for node in view.nodes}
        blocked = self._block_nodes_with_terminal_dependencies(view, node_by_id)
        ready = self._mark_ready_nodes(view, node_by_id)
        view = self.store.load_run_view(run_id)
        runnable = self._runnable_nodes(view)
        runnable, batch_blocked = self._guard_runnable_batch(view, runnable)
        ran = 0
        completed = 0
        failed = 0
        for node in runnable[: self.concurrency]:
            result = self._run_node(node)
            ran += 1
            if result.status == "completed":
                completed += 1
            elif result.status == "failed":
                failed += 1
        self._update_run_status(run_id)
        return AgentDagSchedulerResult(
            ran=ran,
            ready=ready,
            completed=completed,
            failed=failed,
            blocked=blocked + batch_blocked,
        )

    def run_until_blocked(self, run_id: str, max_steps: int) -> AgentDagSchedulerResult:
        """Run scheduler passes until no progress is possible or max_steps is reached."""
        total = AgentDagSchedulerResult()
        for _ in range(max(0, max_steps)):
            result = self.run_once(run_id)
            total = AgentDagSchedulerResult(
                ran=total.ran + result.ran,
                ready=total.ready + result.ready,
                completed=total.completed + result.completed,
                failed=total.failed + result.failed,
                blocked=total.blocked + result.blocked,
            )
            if not result.made_progress:
                break
        return total

    def _block_nodes_with_terminal_dependencies(
        self,
        view: AgentDagRunView,
        node_by_id: dict[str, AgentDagNodeRecord],
    ) -> int:
        blocked = 0
        now = time.time()
        for node in view.nodes:
            if node.status not in ("pending", "ready"):
                continue
            terminal_dependency = next(
                (
                    dependency
                    for dependency in _dependencies(node)
                    if node_by_id.get(dependency) is not None
                    and node_by_id[dependency].status in ("failed", "blocked")
                ),
                None,
            )
            if terminal_dependency is None:
                continue
            self.store.append_node_record(
                self._copy_node(
                    node,
                    status="blocked",
                    updated_at=now,
                    failure_class="validation_failure",
                    failure_message=f"dependency {terminal_dependency} is terminal",
                )
            )
            blocked += 1
        return blocked

    def _mark_ready_nodes(
        self,
        view: AgentDagRunView,
        node_by_id: dict[str, AgentDagNodeRecord],
    ) -> int:
        ready = 0
        now = time.time()
        for node in view.nodes:
            if node.status != "pending":
                continue
            if not self._dependencies_completed(node, node_by_id):
                continue
            if not self._lease_available(node, now):
                continue
            blocked = self._blocked_by_node_policy(node, view, now)
            if blocked is not None:
                self.store.append_node_record(blocked)
                ready += 1
                continue
            self.store.append_node_record(self._copy_node(node, status="ready", updated_at=now))
            ready += 1
        return ready

    def _runnable_nodes(self, view: AgentDagRunView) -> list[AgentDagNodeRecord]:
        node_by_id = {node.node_id: node for node in view.nodes}
        now = time.time()
        runnable = []
        for node in view.nodes:
            if node.status not in ("ready", "failed"):
                continue
            if node.status == "failed" and not self._can_retry(node):
                continue
            if node.status == "ready" and not self._lease_available(node, now):
                continue
            if not self._dependencies_completed(node, node_by_id):
                continue
            runnable.append(node)
        return runnable

    def _guard_runnable_batch(
        self,
        view: AgentDagRunView,
        runnable: list[AgentDagNodeRecord],
    ) -> tuple[list[AgentDagNodeRecord], int]:
        selected: list[AgentDagNodeRecord] = []
        blocked = 0
        now = time.time()
        active_writers = [
            node for node in view.nodes if node.status in ("leased", "running") and node.write_set
        ]
        for node in runnable:
            if len(selected) >= self.concurrency:
                break
            conflict = _first_write_conflict(node, (*active_writers, *selected))
            if conflict is not None:
                self.store.append_conflict_record(_conflict_record(node, conflict, now))
                self.store.append_node_record(
                    self._copy_node(
                        node,
                        status="blocked",
                        updated_at=now,
                        failure_class="policy_failure",
                        failure_message=f"write_set overlaps with {conflict.node_id}",
                    )
                )
                blocked += 1
                continue
            read_conflict = _first_read_conflict(node, (*active_writers, *selected))
            if read_conflict is not None:
                overlap = _path_overlap(node.read_set, read_conflict.write_set)
                self.store.append_conflict_record(
                    _conflict_record(
                        node,
                        read_conflict,
                        now,
                        conflict_type="read_write_overlap",
                        signal="read_set overlaps active mutation write_set",
                        files=overlap,
                    )
                )
                self.store.append_node_record(
                    self._copy_node(
                        node,
                        status="blocked",
                        updated_at=now,
                        failure_class="policy_failure",
                        failure_message=f"read_set overlaps active mutation {read_conflict.node_id}",
                    )
                )
                blocked += 1
                continue
            selected.append(node)
        return selected, blocked

    def _run_node(self, node: AgentDagNodeRecord) -> AgentDagNodeRecord:
        now = time.time()
        lease = self._copy_node(
            node,
            status="leased",
            updated_at=now,
            lease_owner=self.worker_id,
            lease_expires_at=now + self.lease_seconds,
            retry_count=_next_retry_count(node),
        )
        self.store.append_node_record(lease)
        running = self._copy_node(lease, status="running", updated_at=time.time())
        self.store.append_node_record(running)
        if _is_verifier_node(node):
            return self._run_verifier_node(running)
        agent = self.agents.get(node.agent_name)
        if agent is None:
            failed = self._copy_node(
                running,
                status="failed",
                updated_at=time.time(),
                failure_class="agent_not_found",
                failure_message=f"agent {node.agent_name!r} not found",
                lease_owner=None,
                lease_expires_at=None,
            )
            self.store.append_node_record(failed)
            return failed
        task = _task_text(node)
        try:
            result = asyncio.run(agent.execute(task, {"dag_node": running, "task": task}))
        except Exception as exc:
            failed = self._copy_node(
                running,
                status="failed",
                updated_at=time.time(),
                failure_class="transient_error",
                failure_message=str(exc),
                lease_owner=None,
                lease_expires_at=None,
            )
            self.store.append_node_record(failed)
            return failed
        if not isinstance(result, AgentResult):
            failed = self._copy_node(
                running,
                status="failed",
                updated_at=time.time(),
                failure_class="schema_failure",
                failure_message="agent returned non-AgentResult",
                lease_owner=None,
                lease_expires_at=None,
            )
            self.store.append_node_record(failed)
            return failed
        if result.status == AgentStatus.SUCCESS:
            completed = self._copy_node(
                running,
                status="completed",
                updated_at=time.time(),
                artifact_ids=tuple(sorted(result.artifacts)),
                failure_class=None,
                failure_message=None,
                lease_owner=None,
                lease_expires_at=None,
            )
            self.store.append_node_record(completed)
            return completed
        failed = self._copy_node(
            running,
            status="failed",
            updated_at=time.time(),
            failure_class=_failure_class_from_result(result),
            failure_message=result.error or "agent returned failure",
            lease_owner=None,
            lease_expires_at=None,
        )
        self.store.append_node_record(failed)
        return failed

    def _run_verifier_node(self, node: AgentDagNodeRecord) -> AgentDagNodeRecord:
        view = self.store.load_run_view(node.run_id)
        verifier_input = _verifier_input(node, view)
        output = self.verifier.verify(verifier_input, view.artifacts)
        if output.verified:
            completed = self._copy_node(
                node,
                status="completed",
                updated_at=time.time(),
                artifact_ids=("verification",),
                failure_class=None,
                failure_message=None,
                lease_owner=None,
                lease_expires_at=None,
                metadata={**node.metadata, "verifier_output": output.to_artifact()},
            )
            self.store.append_node_record(completed)
            return completed
        failed = self._copy_node(
            node,
            status="failed",
            updated_at=time.time(),
            failure_class=output.failure_class or "validation_failure",
            failure_message=output.reason,
            lease_owner=None,
            lease_expires_at=None,
            metadata={**node.metadata, "verifier_output": output.to_artifact()},
        )
        self.store.append_node_record(failed)
        return failed

    def _update_run_status(self, run_id: str) -> None:
        view = self.store.load_run_view(run_id)
        statuses = {node.status for node in view.nodes}
        if view.nodes and statuses <= {"completed"}:
            status = "completed" if _mutating_nodes_verified(view) else "pending"
        elif any(status in statuses for status in ("failed", "blocked")):
            status = "blocked"
        else:
            status = view.run.status
        if status == view.run.status:
            return
        self.store.append_run_record(
            AgentDagRunRecord(
                run_id=view.run.run_id,
                goal=view.run.goal,
                status=cast(Any, status),
                created_at=view.run.created_at,
                updated_at=time.time(),
                root_node_ids=view.run.root_node_ids,
                metadata=view.run.metadata,
            )
        )

    def _dependencies_completed(
        self,
        node: AgentDagNodeRecord,
        node_by_id: dict[str, AgentDagNodeRecord],
    ) -> bool:
        for dependency in _dependencies(node):
            dependency_node = node_by_id.get(dependency)
            if dependency_node is None or dependency_node.status != "completed":
                return False
        return True

    def _lease_available(self, node: AgentDagNodeRecord, now: float) -> bool:
        return node.lease_owner is None or (node.lease_expires_at or 0.0) <= now

    def _is_read_only(self, node: AgentDagNodeRecord) -> bool:
        permissions = _permissions(node)
        return not node.write_set and not permissions.allow_mutation

    def _is_mutating(self, node: AgentDagNodeRecord) -> bool:
        permissions = _permissions(node)
        return bool(node.write_set or permissions.allow_mutation)

    def _blocked_by_node_policy(
        self,
        node: AgentDagNodeRecord,
        view: AgentDagRunView,
        now: float,
    ) -> AgentDagNodeRecord | None:
        permissions = _permissions(node)
        if not self._is_mutating(node):
            return _blocked_read_for_active_mutation(self.store, node, view, now)
        if not node.write_set:
            return self._copy_node(
                node,
                status="blocked",
                updated_at=now,
                failure_class="policy_failure",
                failure_message="mutating node must declare a non-empty write_set",
            )
        if not permissions.allow_mutation:
            return self._copy_node(
                node,
                status="blocked",
                updated_at=now,
                failure_class="policy_failure",
                failure_message="mutating node requires allow_mutation permission",
            )
        if not permissions.allowed_tools:
            return self._copy_node(
                node,
                status="blocked",
                updated_at=now,
                failure_class="policy_failure",
                failure_message="mutating node requires at least one allowed tool",
            )
        conflict = _write_set_conflict(node, view)
        if conflict is not None:
            conflict_record = _conflict_record(node, conflict, now)
            self.store.append_conflict_record(conflict_record)
            return self._copy_node(
                node,
                status="blocked",
                updated_at=now,
                failure_class="policy_failure",
                failure_message=f"write_set overlaps with {conflict.node_id}",
            )
        return None

    def _can_retry(self, node: AgentDagNodeRecord) -> bool:
        decision = self.enforcement_policy.decide_retry(node, max_retries=self.max_retries)
        if decision.action in ("stop", "escalate") and decision.enforced:
            return False
        if node.failure_class in FATAL_FAILURE_CLASSES:
            return False
        if node.failure_class not in RETRYABLE_FAILURE_CLASSES:
            return False
        return node.retry_count < self.max_retries

    def _copy_node(
        self,
        node: AgentDagNodeRecord,
        *,
        status: str,
        updated_at: float,
        artifact_ids: tuple[str, ...] | None = None,
        failure_class: str | None = None,
        failure_message: str | None = None,
        lease_owner: str | None = None,
        lease_expires_at: float | None = None,
        retry_count: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentDagNodeRecord:
        return AgentDagNodeRecord(
            node_id=node.node_id,
            run_id=node.run_id,
            task_id=node.task_id,
            agent_name=node.agent_name,
            kind=node.kind,
            status=cast(Any, status),
            dependencies=node.dependencies,
            read_set=node.read_set,
            write_set=node.write_set,
            context_manifest_id=node.context_manifest_id,
            artifact_ids=artifact_ids if artifact_ids is not None else node.artifact_ids,
            idempotency_key=node.idempotency_key,
            lease_owner=lease_owner,
            lease_expires_at=lease_expires_at,
            retry_count=retry_count if retry_count is not None else node.retry_count,
            failure_class=failure_class,
            failure_message=failure_message,
            created_at=node.created_at,
            updated_at=updated_at,
            metadata=metadata if metadata is not None else node.metadata,
        )


def _dependencies(node: AgentDagNodeRecord) -> tuple[str, ...]:
    if node.dependencies:
        return node.dependencies
    raw = node.metadata.get("dependencies")
    if not isinstance(raw, list | tuple | set):
        return ()
    return tuple(str(item) for item in raw if str(item))


def _permissions(node: AgentDagNodeRecord) -> TaskPermissions:
    raw = node.metadata.get("permissions") or node.metadata.get("task_permissions")
    return TaskPermissions.from_raw(raw)


def _task_text(node: AgentDagNodeRecord) -> str:
    for key in ("task", "goal", "task_goal"):
        raw = node.metadata.get(key)
        if isinstance(raw, str) and raw:
            return raw
    return node.task_id


def _is_verifier_node(node: AgentDagNodeRecord) -> bool:
    return node.kind == "verifier" or node.agent_name == "verification_agent"


def _verifier_input(node: AgentDagNodeRecord, view: AgentDagRunView) -> VerifierInput:
    artifact_ids = _string_tuple_from_metadata(node, "artifact_ids")
    if not artifact_ids:
        artifact_ids = _string_tuple_from_metadata(node, "required_artifact_ids")
    if not artifact_ids:
        dependency_artifacts: list[str] = []
        nodes_by_id = {candidate.node_id: candidate for candidate in view.nodes}
        for dependency in _dependencies(node):
            dependency_artifacts.extend(nodes_by_id.get(dependency, node).artifact_ids)
        artifact_ids = tuple(dict.fromkeys(dependency_artifacts))
    return VerifierInput(
        task_id=str(node.metadata.get("verifies_task_id") or node.task_id),
        artifact_ids=artifact_ids,
        acceptance_criteria=_string_tuple_from_metadata(node, "acceptance_criteria"),
        expected_evidence=_string_tuple_from_metadata(node, "expected_evidence"),
        mission_brief_id=(
            str(node.metadata["mission_brief_id"])
            if node.metadata.get("mission_brief_id") is not None
            else None
        ),
        test_output=str(node.metadata.get("test_output") or ""),
    )


def _mutating_nodes_verified(view: AgentDagRunView) -> bool:
    completed_mutations = [
        node for node in view.nodes if node.status == "completed" and node.write_set
    ]
    if not completed_mutations:
        return True
    completed_verifiers = [
        node for node in view.nodes if node.status == "completed" and _is_verifier_node(node)
    ]
    for mutation in completed_mutations:
        if not any(
            _verifier_covers_mutation(verifier, mutation) for verifier in completed_verifiers
        ):
            return False
    return True


def _verifier_covers_mutation(
    verifier: AgentDagNodeRecord,
    mutation: AgentDagNodeRecord,
) -> bool:
    if verifier.metadata.get("verifies_node_id") == mutation.node_id:
        return True
    return mutation.node_id in _dependencies(verifier)


def _string_tuple_from_metadata(node: AgentDagNodeRecord, key: str) -> tuple[str, ...]:
    raw = node.metadata.get(key)
    if not isinstance(raw, list | tuple | set):
        return ()
    return tuple(str(item) for item in raw if str(item))


def _next_retry_count(node: AgentDagNodeRecord) -> int:
    if node.status == "failed":
        return node.retry_count + 1
    return node.retry_count


def _blocked_read_for_active_mutation(
    store: AgentDagStore,
    node: AgentDagNodeRecord,
    view: AgentDagRunView,
    now: float,
) -> AgentDagNodeRecord | None:
    if _stale_reads_allowed(node):
        return None
    for active in view.nodes:
        if active.node_id == node.node_id or active.status not in ("leased", "running"):
            continue
        if not active.write_set:
            continue
        overlap = _path_overlap(node.read_set, active.write_set)
        if not overlap:
            continue
        store.append_conflict_record(
            _conflict_record(
                node,
                active,
                now,
                conflict_type="read_write_overlap",
                signal="read_set overlaps active mutation write_set",
                files=overlap,
            )
        )
        return AgentDagNodeRecord(
            node_id=node.node_id,
            run_id=node.run_id,
            task_id=node.task_id,
            agent_name=node.agent_name,
            kind=node.kind,
            status="blocked",
            dependencies=node.dependencies,
            read_set=node.read_set,
            write_set=node.write_set,
            context_manifest_id=node.context_manifest_id,
            artifact_ids=node.artifact_ids,
            idempotency_key=node.idempotency_key,
            retry_count=node.retry_count,
            failure_class="policy_failure",
            failure_message=f"read_set overlaps active mutation {active.node_id}",
            created_at=node.created_at,
            updated_at=now,
            metadata=node.metadata,
        )
    return None


def _write_set_conflict(
    node: AgentDagNodeRecord,
    view: AgentDagRunView,
) -> AgentDagNodeRecord | None:
    active_nodes = tuple(
        active
        for active in view.nodes
        if active.node_id != node.node_id and active.status in ("leased", "running")
    )
    return _first_write_conflict(node, active_nodes)


def _first_write_conflict(
    node: AgentDagNodeRecord,
    others: tuple[AgentDagNodeRecord, ...],
) -> AgentDagNodeRecord | None:
    if not node.write_set:
        return None
    for other in others:
        if other.node_id == node.node_id or not other.write_set:
            continue
        if _path_overlap(node.write_set, other.write_set):
            return other
    return None


def _first_read_conflict(
    node: AgentDagNodeRecord,
    others: tuple[AgentDagNodeRecord, ...],
) -> AgentDagNodeRecord | None:
    if not node.read_set or _stale_reads_allowed(node):
        return None
    for other in others:
        if other.node_id == node.node_id or not other.write_set:
            continue
        if _path_overlap(node.read_set, other.write_set):
            return other
    return None


def _conflict_record(
    node: AgentDagNodeRecord,
    other: AgentDagNodeRecord,
    now: float,
    *,
    conflict_type: str = "overlapping_write_set",
    signal: str = "write_set overlaps active mutation write_set",
    files: tuple[str, ...] | None = None,
) -> AgentDagConflictRecord:
    overlap = files if files is not None else _path_overlap(node.write_set, other.write_set)
    node_ids = tuple(sorted((node.node_id, other.node_id)))
    conflict_id = make_agent_dag_id(
        "conflict",
        {
            "files": list(overlap),
            "node_ids": list(node_ids),
            "run_id": node.run_id,
            "type": conflict_type,
        },
    )
    return AgentDagConflictRecord(
        conflict_id=conflict_id,
        run_id=node.run_id,
        node_ids=node_ids,
        type=conflict_type,
        files=overlap,
        signal=signal,
        created_at=now,
    )


def _path_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    left_paths = {_normalize_path(path) for path in left if path}
    right_paths = {_normalize_path(path) for path in right if path}
    return tuple(sorted(left_paths & right_paths))


def _normalize_path(path: str) -> str:
    return path.rstrip("/")


def _stale_reads_allowed(node: AgentDagNodeRecord) -> bool:
    return bool(node.metadata.get("allow_stale_reads", False))


def _failure_class_from_result(result: AgentResult) -> AgentDagFailureClass:
    raw = result.error or ""
    lowered = raw.lower()
    if "context" in lowered and "insufficient" in lowered:
        return "context_insufficiency"
    if "policy" in lowered or "permission" in lowered:
        return "policy_failure"
    if "schema" in lowered:
        return "schema_failure"
    return "unknown_failure"
