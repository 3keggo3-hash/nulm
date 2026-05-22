"""Task dispatcher for distributing work to sub-agents."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, cast

from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.context_manifest import build_context_manifest
from claude_bridge.agents.contracts import TaskSpec, coerce_task_spec
from claude_bridge.agents.dag_records import (
    AgentDagStatus,
    AgentDagNodeRecord,
    make_node_id,
    make_node_idempotency_key,
)
from claude_bridge.agents.dag_store import AgentDagStore
from claude_bridge.agents.result import AgentResult
from claude_bridge.agents.run_record import AgentRunRecord, finish_agent_run, start_agent_run
from claude_bridge.agents.shared_memory import SharedMemorySpace
from claude_bridge.audit import current_session_id


class TaskDispatcher:
    """Dispatches tasks to sub-agents using asyncio.gather."""

    def __init__(
        self,
        shared_memory: SharedMemorySpace | None = None,
        *,
        dag_store: AgentDagStore | None = None,
        dag_run_id: str | None = None,
    ) -> None:
        self.shared_memory = shared_memory or SharedMemorySpace()
        self.dag_store = dag_store
        self.dag_run_id = dag_run_id
        self.run_records: list[AgentRunRecord] = []

    async def distribute(
        self,
        subtasks: Sequence[TaskSpec | dict[str, Any]],
        agents: list[BaseAgent],
    ) -> list[AgentResult]:
        """Distribute subtasks to agents and execute them in parallel.

        Args:
            subtasks: List of subtask dictionaries with 'task' and 'agent_name' keys.
            agents: List of BaseAgent instances to execute subtasks.

        Returns:
            List of AgentResult from each subtask execution.
        """
        agent_map = {agent.name: agent for agent in agents}
        task_specs = [coerce_task_spec(subtask) for subtask in subtasks]
        self.run_records = []

        async def execute_subtask(subtask: TaskSpec) -> AgentResult:
            agent_name = subtask.agent_name
            task = subtask.goal
            task_id = subtask.task_id
            record = self._start_run_record(
                task_id=task_id,
                agent_name=agent_name,
                task_kind=subtask.kind,
            )

            agent = agent_map.get(agent_name)
            if agent is None:
                result = AgentResult.failure(
                    error=f"Agent '{agent_name}' not found",
                    agent_name=agent_name,
                )
                finish_agent_run(
                    record,
                    result,
                    error_class="AgentNotFound",
                    error_message=result.error,
                )
                return result

            manifest = build_context_manifest(
                task=subtask,
                run_id=record.run_id,
                session_id=current_session_id(),
            )
            record.context_manifest_id = manifest.manifest_id
            dag_node = self._append_dag_node_record(
                subtask,
                record,
                status="running",
                context_manifest_id=manifest.manifest_id,
            )
            context = {
                "shared_memory": self.shared_memory,
                "subtask": subtask,
                "subtask_id": subtask.task_id,
                "agent_run_record": record,
                "context_manifest": manifest,
                "context_manifest_id": manifest.manifest_id,
            }

            try:
                result = await agent.execute(task, context)
                finish_agent_run(record, result)
                self._append_dag_node_record(
                    subtask,
                    record,
                    status="completed" if result.status.value == "success" else "failed",
                    context_manifest_id=manifest.manifest_id,
                    previous_node=dag_node,
                    artifact_ids=tuple(sorted(getattr(result, "artifacts", {}))),
                    failure_class=record.error_class,
                    failure_message=record.error_message,
                )
                return result
            except Exception as e:
                result = AgentResult.failure(
                    error=str(e),
                    agent_name=agent_name,
                )
                finish_agent_run(
                    record,
                    result,
                    error_class=type(e).__name__,
                    error_message=str(e),
                )
                self._append_dag_node_record(
                    subtask,
                    record,
                    status="failed",
                    context_manifest_id=manifest.manifest_id,
                    previous_node=dag_node,
                    failure_class=record.error_class,
                    failure_message=record.error_message,
                )
                return result

        tasks = [execute_subtask(st) for st in task_specs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_results: list[AgentResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                agent_name = task_specs[i].agent_name or "unknown"
                processed_results.append(
                    AgentResult.failure(
                        error=str(result),
                        agent_name=agent_name,
                    )
                )
            else:
                processed_results.append(cast(AgentResult, result))

        return processed_results

    async def distribute_single(
        self,
        task: str,
        agent: BaseAgent,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Execute a single task with an agent.

        Args:
            task: The task to execute.
            agent: The agent to execute with.
            context: Optional context dict.

        Returns:
            AgentResult from the execution.
        """
        ctx = dict(context) if context else {}
        ctx["shared_memory"] = self.shared_memory
        self.run_records = []
        result, record = await agent.execute_traced(
            task,
            ctx,
            task_id=str(ctx.get("subtask_id") or "single"),
            task_kind=agent.name.removesuffix("_agent") or "single",
        )
        self.run_records.append(record)
        return result

    def _start_run_record(
        self,
        *,
        task_id: str,
        agent_name: str,
        task_kind: str,
    ) -> AgentRunRecord:
        record = start_agent_run(
            task_id=task_id,
            agent_name=agent_name,
            task_kind=task_kind,
        )
        self.run_records.append(record)
        return record

    def _append_dag_node_record(
        self,
        task: TaskSpec,
        record: AgentRunRecord,
        *,
        status: AgentDagStatus,
        context_manifest_id: str | None,
        previous_node: AgentDagNodeRecord | None = None,
        artifact_ids: tuple[str, ...] = (),
        failure_class: str | None = None,
        failure_message: str | None = None,
    ) -> AgentDagNodeRecord | None:
        if self.dag_store is None:
            return None

        import time

        run_id = self.dag_run_id or current_session_id()
        node_id = make_node_id(
            run_id=run_id,
            task_id=task.task_id,
            agent_name=task.agent_name,
            kind=task.kind,
            read_set=task.read_set,
            write_set=task.write_set,
        )
        idempotency_key = make_node_idempotency_key(
            run_id=run_id,
            task_id=task.task_id,
            agent_name=task.agent_name,
            kind=task.kind,
            read_set=task.read_set,
            write_set=task.write_set,
        )
        now = time.time()
        node = AgentDagNodeRecord(
            node_id=node_id,
            run_id=run_id,
            task_id=task.task_id,
            agent_name=task.agent_name,
            kind=task.kind,
            status=status,
            dependencies=previous_node.dependencies if previous_node is not None else (),
            read_set=task.read_set,
            write_set=task.write_set,
            context_manifest_id=context_manifest_id,
            artifact_ids=artifact_ids,
            idempotency_key=idempotency_key,
            retry_count=previous_node.retry_count if previous_node is not None else 0,
            failure_class=failure_class,
            failure_message=failure_message,
            created_at=previous_node.created_at if previous_node is not None else now,
            updated_at=now,
            metadata={"agent_run_id": record.run_id},
        )
        self.dag_store.append_node(node)
        return node
