"""Tests for task dispatcher."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


import pytest

from claude_bridge.agents.dispatcher import TaskDispatcher
from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.contracts import TaskBudget, TaskPermissions, TaskSpec
from claude_bridge.agents.result import AgentResult, AgentStatus
from claude_bridge.agents.run_record import compact_run_summary
from claude_bridge.agents.shared_memory import SharedMemorySpace
from claude_bridge.audit import _load_records, current_session_id, get_recent_tool_calls
from claude_bridge.audit import summarize_session


class DummyAgent(BaseAgent):
    async def execute(self, task: str, context: dict) -> AgentResult:
        return AgentResult.success(
            findings=[f"executed: {task}"],
            agent_name=self.name,
        )


class ContextCapturingAgent(BaseAgent):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.last_context: dict | None = None

    async def execute(self, task: str, context: dict) -> AgentResult:
        self.last_context = context
        return AgentResult.success(findings=[task], agent_name=self.name)


@pytest.mark.asyncio
async def test_distribute_single_task():
    dispatcher = TaskDispatcher()
    agent = DummyAgent("test_agent")

    result = await dispatcher.distribute_single("test task", agent)

    assert result.status == AgentStatus.SUCCESS
    assert "executed: test task" in result.findings
    assert len(dispatcher.run_records) == 1
    assert dispatcher.run_records[0].task_id == "single"
    assert dispatcher.run_records[0].status == "success"


@pytest.mark.asyncio
async def test_distribute_multiple_subtasks():
    dispatcher = TaskDispatcher()
    agents = [DummyAgent("agent1"), DummyAgent("agent2")]

    subtasks = [
        {"id": "1", "task": "task1", "agent_name": "agent1"},
        {"id": "2", "task": "task2", "agent_name": "agent2"},
    ]

    results = await dispatcher.distribute(subtasks, agents)

    assert len(results) == 2
    assert all(r.status == AgentStatus.SUCCESS for r in results)
    assert len(dispatcher.run_records) == 2
    assert {record.task_id for record in dispatcher.run_records} == {"1", "2"}
    assert all(record.status == "success" for record in dispatcher.run_records)
    assert all(record.duration_ms is not None for record in dispatcher.run_records)
    audit_records = _load_records(current_session_id())
    agent_records = [record for record in audit_records if record.get("tool_name") == "agent_run"]
    assert len(agent_records) == 2
    assert {record["params"]["task_id"] for record in agent_records} == {"1", "2"}
    assert all(record["result"]["schema_version"] == "agent_run.v1" for record in agent_records)
    recent = get_recent_tool_calls(tool_name="agent_run", limit=10)
    assert recent["query_strategy"] == "audit_index"
    assert recent["returned_records"] == 2
    session = summarize_session(limit=10)
    assert session["agent_runs"]["run_count"] == 2
    assert session["agent_runs"]["status_counts"] == {"success": 2}
    assert session["agent_runs"]["agent_names"] == ["agent1", "agent2"]


@pytest.mark.asyncio
async def test_distribute_unknown_agent():
    dispatcher = TaskDispatcher()
    agents = [DummyAgent("known_agent")]

    subtasks = [
        {"id": "1", "task": "task1", "agent_name": "unknown_agent"},
    ]

    results = await dispatcher.distribute(subtasks, agents)

    assert len(results) == 1
    assert results[0].status == AgentStatus.FAILURE
    assert "not found" in results[0].error
    assert len(dispatcher.run_records) == 1
    record = dispatcher.run_records[0]
    assert record.task_id == "1"
    assert record.agent_name == "unknown_agent"
    assert record.status == "failure"
    assert record.error_class == "AgentNotFound"


@pytest.mark.asyncio
async def test_distribute_with_shared_memory():
    memory = SharedMemorySpace()
    dispatcher = TaskDispatcher(memory)
    agent = DummyAgent("test_agent")

    memory.write("shared_key", "shared_value")

    result = await dispatcher.distribute_single("test", agent)

    assert result.status == AgentStatus.SUCCESS


@pytest.mark.asyncio
async def test_distribute_records_exception_class():
    class ExplodingAgent(BaseAgent):
        async def execute(self, task: str, context: dict) -> AgentResult:
            raise RuntimeError("boom")

    dispatcher = TaskDispatcher()
    agent = ExplodingAgent("debug_agent")

    results = await dispatcher.distribute(
        [{"id": "debug_task", "task": "debug", "agent_name": "debug_agent"}],
        [agent],
    )

    assert results[0].status == AgentStatus.FAILURE
    assert dispatcher.run_records[0].error_class == "RuntimeError"
    assert dispatcher.run_records[0].error_message == "boom"


@pytest.mark.asyncio
async def test_distribute_records_agent_failure_class():
    class FailingAgent(BaseAgent):
        async def execute(self, task: str, context: dict) -> AgentResult:
            return AgentResult.failure(error="bad result", agent_name=self.name)

    dispatcher = TaskDispatcher()
    agent = FailingAgent("review_agent")

    results = await dispatcher.distribute(
        [{"id": "review_task", "task": "review", "agent_name": "review_agent"}],
        [agent],
    )

    assert results[0].status == AgentStatus.FAILURE
    assert dispatcher.run_records[0].status == "failure"
    assert dispatcher.run_records[0].error_class == "AgentFailure"


@pytest.mark.asyncio
async def test_distribute_records_malformed_agent_result():
    class MalformedAgent(BaseAgent):
        async def execute(self, task: str, context: dict) -> AgentResult:  # type: ignore[override]
            return {"ok": True}  # type: ignore[return-value]

    dispatcher = TaskDispatcher()
    agent = MalformedAgent("research_agent")

    results = await dispatcher.distribute(
        [{"id": "research_task", "task": "research", "agent_name": "research_agent"}],
        [agent],
    )

    assert results[0].status == AgentStatus.FAILURE
    assert dispatcher.run_records[0].status == "failure"
    assert dispatcher.run_records[0].error_class == "AttributeError"


def test_compact_run_summary_handles_empty_records():
    summary = compact_run_summary([])

    assert summary["schema_version"] == "agent_run_summary.v1"
    assert summary["run_count"] == 0


def test_task_spec_legacy_adapter_preserves_existing_subtask_shape():
    spec = TaskSpec.from_legacy_dict(
        {
            "id": "research_task",
            "task": "Analyze current agent layer",
            "agent_name": "research_agent",
            "read_set": ["src"],
            "write_set": [],
            "budget": {"max_tool_calls": 10, "timeout_seconds": 120},
            "permissions": {"allowed_tools": ["search"], "allow_mutation": False},
            "expected_artifacts": ["findings"],
            "priority": 1,
        }
    )

    assert spec.task_id == "research_task"
    assert spec.kind == "research"
    assert spec.goal == "Analyze current agent layer"
    assert spec.read_set == ("src",)
    assert spec.budget == TaskBudget(max_tool_calls=10, timeout_seconds=120)
    assert spec.permissions == TaskPermissions(allowed_tools=frozenset({"search"}))
    assert spec.expected_artifacts == ("findings",)
    assert spec.to_legacy_context()["task"] == "Analyze current agent layer"


@pytest.mark.asyncio
async def test_distribute_accepts_typed_task_spec():
    dispatcher = TaskDispatcher()
    agent = DummyAgent("research_agent")
    spec = TaskSpec(
        task_id="typed_task",
        kind="research",
        goal="typed research",
        agent_name="research_agent",
    )

    results = await dispatcher.distribute([spec], [agent])

    assert results[0].status == AgentStatus.SUCCESS
    assert dispatcher.run_records[0].task_id == "typed_task"
    assert dispatcher.run_records[0].task_kind == "research"


@pytest.mark.asyncio
async def test_distribute_attaches_context_manifest_id_for_typed_task(tmp_path):
    source = tmp_path / "target.py"
    source.write_text("x = 1\n", encoding="utf-8")
    dispatcher = TaskDispatcher()
    agent = ContextCapturingAgent("research_agent")
    spec = TaskSpec(
        task_id="typed_context",
        kind="research",
        goal="inspect context",
        agent_name="research_agent",
        read_set=(str(source),),
    )

    results = await dispatcher.distribute([spec], [agent])

    record = dispatcher.run_records[0]
    assert results[0].status == AgentStatus.SUCCESS
    assert record.context_manifest_id
    assert agent.last_context is not None
    assert agent.last_context["context_manifest_id"] == record.context_manifest_id
    assert agent.last_context["context_manifest"].selected_files == (str(source),)


@pytest.mark.asyncio
async def test_distribute_legacy_dict_subtask_gets_context_manifest():
    dispatcher = TaskDispatcher()
    agent = ContextCapturingAgent("research_agent")

    results = await dispatcher.distribute(
        [{"id": "legacy_context", "task": "legacy", "agent_name": "research_agent"}],
        [agent],
    )

    record = dispatcher.run_records[0]
    assert results[0].status == AgentStatus.SUCCESS
    assert record.context_manifest_id
    assert agent.last_context is not None
    assert agent.last_context["context_manifest_id"] == record.context_manifest_id
    assert agent.last_context["context_manifest"].selected_files == ()
