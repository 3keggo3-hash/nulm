"""Deterministic benchmark harness for agent-layer workflow checks."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import ast
import asyncio
import json
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.broker import AgentToolBroker
from claude_bridge.agents.context_manifest import build_context_manifest
from claude_bridge.agents.contracts import ContextManifest, TaskPermissions, TaskSpec
from claude_bridge.agents.dag_records import (
    AgentDagArtifactRecord,
    AgentDagNodeRecord,
    AgentDagRunRecord,
    AgentDagStatus,
    make_artifact_id,
    make_node_id,
    make_node_idempotency_key,
)
from claude_bridge.agents.conflict_detector import ConflictDetector, PatchHunk
from claude_bridge.agents.dag_scheduler import AgentDagScheduler
from claude_bridge.agents.dag_store import AgentDagStore
from claude_bridge.agents.enforcement import EnforcementPolicy
from claude_bridge.agents.dispatcher import TaskDispatcher
from claude_bridge.agents.mission_brief import ContextCurator
from claude_bridge.agents.result import AgentResult, AgentStatus
from claude_bridge.agents.run_record import AgentRunRecord, start_agent_run
from claude_bridge.ai_router import (
    AIModelProfile,
    AIModelRouter,
    reset_route_telemetry,
    route_telemetry_summary,
)

AGENT_BENCHMARK_SCHEMA_VERSION = "agent_benchmark_run.v1"
_MISSING_API_KEY_ENV = "__CLAUDE_BRIDGE_AGENT_BENCHMARK_MISSING_API_KEY__"
_DEFAULT_BYPASS_SCAN_TARGETS = (
    Path("src/claude_bridge/agents/sub/git_agent.py"),
    Path("src/claude_bridge/agents/sub/research_agent.py"),
    Path("src/claude_bridge/agents/sub/debug_agent.py"),
)


@dataclass(frozen=True)
class AgentBenchmarkMetrics:
    """Stable metric payload for one benchmark scenario."""

    verified_success: bool = False
    tool_call_count: int = 0
    trace_complete: bool = False
    context_manifest_present: bool = False
    mission_brief_present: bool = False
    estimated_tokens: int = 0
    duplicate_context_ratio: float = 0.0
    policy_denial_correct: bool = False
    retry_count: int = 0
    route_decision_count: int = 0
    fallback_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "verified_success": self.verified_success,
            "tool_call_count": self.tool_call_count,
            "trace_complete": self.trace_complete,
            "context_manifest_present": self.context_manifest_present,
            "mission_brief_present": self.mission_brief_present,
            "estimated_tokens": self.estimated_tokens,
            "duplicate_context_ratio": self.duplicate_context_ratio,
            "policy_denial_correct": self.policy_denial_correct,
            "retry_count": self.retry_count,
            "route_decision_count": self.route_decision_count,
            "fallback_count": self.fallback_count,
        }


@dataclass(frozen=True)
class AgentBenchmarkScenarioResult:
    """Result for one agent benchmark scenario."""

    name: str
    ok: bool
    duration_ms: float
    failure_class: str = ""
    message: str = ""
    metrics: AgentBenchmarkMetrics = field(default_factory=AgentBenchmarkMetrics)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "name": self.name,
            "ok": self.ok,
            "duration_ms": round(self.duration_ms, 3),
            "failure_class": self.failure_class,
            "message": self.message,
            "metrics": self.metrics.to_dict(),
        }


@dataclass(frozen=True)
class AgentBenchmarkRun:
    """Stable JSON-serializable benchmark run payload."""

    started_at: float
    ended_at: float
    results: tuple[AgentBenchmarkScenarioResult, ...]
    schema_version: str = AGENT_BENCHMARK_SCHEMA_VERSION

    @property
    def duration_ms(self) -> float:
        return max(0.0, (self.ended_at - self.started_at) * 1000)

    @property
    def passed(self) -> int:
        return sum(1 for result in self.results if result.ok)

    @property
    def failed(self) -> int:
        return len(self.results) - self.passed

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "schema_version": self.schema_version,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": round(self.duration_ms, 3),
            "scenario_count": len(self.results),
            "passed": self.passed,
            "failed": self.failed,
            "results": [result.to_dict() for result in self.results],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize the benchmark run as stable-key JSON."""
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    def save_json(self, path: str | Path, *, indent: int | None = 2) -> None:
        """Persist benchmark results only when a caller explicitly provides a path."""
        Path(path).write_text(self.to_json(indent=indent) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class AgentBenchmarkScenario:
    """Named scenario callable used by the harness runner."""

    name: str
    run: Callable[[], AgentBenchmarkMetrics]


def run_agent_benchmark(
    scenarios: Sequence[AgentBenchmarkScenario] | None = None,
    *,
    save_path: str | Path | None = None,
) -> AgentBenchmarkRun:
    """Run deterministic local agent benchmark scenarios."""
    started_at = time.time()
    results = tuple(_run_scenario(scenario) for scenario in (scenarios or default_scenarios()))
    ended_at = time.time()
    run = AgentBenchmarkRun(started_at=started_at, ended_at=ended_at, results=results)
    if save_path is not None:
        run.save_json(save_path)
    return run


def default_scenarios() -> tuple[AgentBenchmarkScenario, ...]:
    """Return the default Phase 6 MVP scenario set."""
    return (
        AgentBenchmarkScenario("typed_task_dispatch", _scenario_typed_task_dispatch),
        AgentBenchmarkScenario("malformed_legacy_task_fail_closed", _scenario_malformed_task),
        AgentBenchmarkScenario("missing_agent_typed_failure", _scenario_missing_agent),
        AgentBenchmarkScenario("permission_denied_broker_tool", _scenario_permission_denied),
        AgentBenchmarkScenario("git_status_agent_tool_broker", _scenario_git_status_broker),
        AgentBenchmarkScenario("research_context_manifest_selection", _scenario_context_selection),
        AgentBenchmarkScenario(
            "mission_brief_filters_irrelevant_context",
            _scenario_mission_brief_filters_irrelevant_context,
        ),
        AgentBenchmarkScenario("route_telemetry_local_disabled", _scenario_route_local_disabled),
        AgentBenchmarkScenario("route_telemetry_provider_fallback", _scenario_provider_fallback),
        AgentBenchmarkScenario("context_manifest_token_budget_overrun", _scenario_budget_overrun),
        AgentBenchmarkScenario("durable_dag_reconstruct_run", _scenario_durable_dag_reconstruct),
        AgentBenchmarkScenario(
            "dag_readonly_dependency_order",
            _scenario_dag_readonly_dependency_order,
        ),
        AgentBenchmarkScenario(
            "dag_completed_node_not_rerun",
            _scenario_dag_completed_node_not_rerun,
        ),
        AgentBenchmarkScenario(
            "dag_retry_cap_same_failure",
            _scenario_dag_retry_cap_same_failure,
        ),
        AgentBenchmarkScenario(
            "dag_mutation_write_set_overlap_blocked",
            _scenario_dag_mutation_write_set_overlap_blocked,
        ),
        AgentBenchmarkScenario(
            "verifier_required_for_mutation_success",
            _scenario_verifier_required_for_mutation_success,
        ),
        AgentBenchmarkScenario(
            "conflict_record_for_overlapping_patch",
            _scenario_conflict_record_for_overlapping_patch,
        ),
        AgentBenchmarkScenario(
            "low_relevance_artifact_not_promoted",
            _scenario_low_relevance_artifact_not_promoted,
        ),
        AgentBenchmarkScenario("no_direct_subagent_subprocess_bypass", _scenario_no_bypass),
    )


def scan_subagent_process_bypass(paths: Sequence[Path] | None = None) -> list[str]:
    """Return process-bypass findings for targeted subagent source files."""
    findings: list[str] = []
    targets = paths or _DEFAULT_BYPASS_SCAN_TARGETS
    forbidden_attrs = {("subprocess", "run"), ("subprocess", "Popen"), ("os", "system")}
    forbidden_text = ("subprocess", "Popen", "os.system")
    for path in targets:
        source = path.read_text(encoding="utf-8")
        for text in forbidden_text:
            if text in source:
                findings.append(f"{path}: contains {text}")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            owner = node.func.value
            if isinstance(owner, ast.Name) and (owner.id, node.func.attr) in forbidden_attrs:
                findings.append(f"{path}: calls {owner.id}.{node.func.attr}")
    return findings


def _run_scenario(scenario: AgentBenchmarkScenario) -> AgentBenchmarkScenarioResult:
    started_at = time.perf_counter()
    try:
        metrics = scenario.run()
        return AgentBenchmarkScenarioResult(
            name=scenario.name,
            ok=metrics.verified_success,
            duration_ms=(time.perf_counter() - started_at) * 1000,
            failure_class="" if metrics.verified_success else "ScenarioAssertionFailed",
            message="" if metrics.verified_success else "scenario verification returned false",
            metrics=metrics,
        )
    except Exception as exc:
        return AgentBenchmarkScenarioResult(
            name=scenario.name,
            ok=False,
            duration_ms=(time.perf_counter() - started_at) * 1000,
            failure_class=type(exc).__name__,
            message=str(exc),
        )


def _scenario_typed_task_dispatch() -> AgentBenchmarkMetrics:
    class EchoAgent(BaseAgent):
        async def execute(self, task: str, context: dict[str, Any]) -> AgentResult:
            return AgentResult.success(findings=[task], agent_name=self.name)

    dispatcher = TaskDispatcher()
    spec = TaskSpec(
        task_id="typed_dispatch",
        kind="research",
        goal="check typed dispatch",
        agent_name="research_agent",
    )
    results = asyncio.run(dispatcher.distribute([spec], [EchoAgent("research_agent")]))
    record = dispatcher.run_records[0]
    ok = (
        len(results) == 1
        and results[0].status == AgentStatus.SUCCESS
        and record.status == "success"
        and bool(record.context_manifest_id)
    )
    return _metrics_from_record(record, verified_success=ok)


def _scenario_malformed_task() -> AgentBenchmarkMetrics:
    dispatcher = TaskDispatcher()
    results = asyncio.run(dispatcher.distribute([{"id": "", "task": "", "agent_name": ""}], []))
    record = dispatcher.run_records[0]
    ok = (
        results[0].status == AgentStatus.FAILURE
        and record.task_id == "_invalid"
        and record.error_class == "AgentNotFound"
    )
    return _metrics_from_record(record, verified_success=ok)


def _scenario_missing_agent() -> AgentBenchmarkMetrics:
    dispatcher = TaskDispatcher()
    spec = TaskSpec(
        task_id="missing_agent",
        kind="debug",
        goal="route to missing agent",
        agent_name="missing_agent",
    )
    results = asyncio.run(dispatcher.distribute([spec], []))
    record = dispatcher.run_records[0]
    ok = results[0].status == AgentStatus.FAILURE and record.error_class == "AgentNotFound"
    return _metrics_from_record(record, verified_success=ok)


def _scenario_permission_denied() -> AgentBenchmarkMetrics:
    record = _record("permission_denied", "git_agent", "git")
    broker = AgentToolBroker(TaskPermissions(allowed_tools=frozenset({"file_read"})))
    result = broker.git_status(record)
    ok = bool(
        result.status == AgentStatus.FAILURE
        and record.error_class == "PermissionDenied"
        and record.tool_calls
        and record.tool_calls[0]["status"] == "denied"
    )
    return _metrics_from_record(record, verified_success=ok, policy_denial_correct=ok)


def _scenario_git_status_broker() -> AgentBenchmarkMetrics:
    record = _record("git_status", "git_agent", "git")
    broker = AgentToolBroker(TaskPermissions(allowed_tools=frozenset({"git"})))
    result = broker.git_status(record)
    ok = result.status == AgentStatus.SUCCESS and _has_tool_call(record, "git_status", "success")
    return _metrics_from_record(record, verified_success=ok)


def _scenario_context_selection() -> AgentBenchmarkMetrics:
    with TemporaryDirectory(prefix="claude-bridge-agent-bench-") as tmp:
        source = Path(tmp) / "target.py"
        source.write_text("value = 1\n", encoding="utf-8")
        spec = TaskSpec(
            task_id="context_selection",
            kind="research",
            goal="select explicit context",
            agent_name="research_agent",
            read_set=(str(source),),
        )
        manifest = build_context_manifest(task=spec, run_id="run", session_id="bench")
        ok = (
            manifest.selected_files == (str(source),)
            and manifest.source_reason == "task_read_set"
            and manifest.file_signatures[0]["exists"] == "true"
        )
        return _metrics_from_manifest(manifest, verified_success=ok)


def _scenario_mission_brief_filters_irrelevant_context() -> AgentBenchmarkMetrics:
    with TemporaryDirectory(prefix="claude-bridge-agent-brief-bench-") as tmp:
        auth_file = Path(tmp) / "auth_login.py"
        notes_file = Path(tmp) / "billing_notes.md"
        auth_file.write_text("def login():\n    return True\n", encoding="utf-8")
        notes_file.write_text("billing notes\n", encoding="utf-8")
        spec = TaskSpec(
            task_id="brief_filter",
            kind="research",
            goal="inspect auth login behavior",
            agent_name="research_agent",
            question="What does auth login do?",
            acceptance_criteria=("cite auth behavior",),
            expected_artifacts=("findings",),
        )
        manifest = build_context_manifest(
            task=spec,
            run_id="run",
            session_id="bench",
            context={"selected_files": [str(auth_file), str(notes_file)]},
        )
        brief = ContextCurator().curate(spec, manifest)
        ok = (
            brief.context_manifest_id == manifest.manifest_id
            and brief.objective == spec.goal
            and brief.allowed_scope == (str(auth_file),)
            and str(notes_file) not in brief.allowed_scope
        )
        return AgentBenchmarkMetrics(
            verified_success=ok,
            trace_complete=True,
            context_manifest_present=bool(manifest.manifest_id),
            mission_brief_present=bool(brief.brief_id),
            estimated_tokens=brief.token_estimate,
        )


def _scenario_route_local_disabled() -> AgentBenchmarkMetrics:
    reset_route_telemetry()
    router = AIModelRouter(enabled=False, default_profile="fast")
    decision = router.select_profile("security review approval policy")
    telemetry = route_telemetry_summary()
    ok = (
        decision.profile_name == "local"
        and decision.reason == "AI routing disabled"
        and telemetry["total_route_decisions"] == 1
        and telemetry["fallback_count"] == 0
    )
    return AgentBenchmarkMetrics(
        verified_success=ok,
        route_decision_count=int(telemetry["total_route_decisions"]),
        fallback_count=int(telemetry["fallback_count"]),
    )


def _scenario_provider_fallback() -> AgentBenchmarkMetrics:
    previous = os.environ.pop(_MISSING_API_KEY_ENV, None)
    try:
        reset_route_telemetry()
        router = AIModelRouter(
            enabled=True,
            mode="manual",
            default_profile="missing",
            profiles={
                "local": AIModelProfile(name="local", provider="local"),
                "missing": AIModelProfile(
                    name="missing",
                    provider="openai",
                    model="gpt-test",
                    api_key_env=_MISSING_API_KEY_ENV,
                ),
            },
        )
        response = router.generate_text("Benchmark local fallback", profile_name="missing")
        telemetry = route_telemetry_summary()
        ok = (
            response.ok is False
            and response.decision.profile_name == "local"
            and response.decision.fallback_status == "used"
            and telemetry["fallback_count"] == 1
        )
        return AgentBenchmarkMetrics(
            verified_success=ok,
            route_decision_count=int(telemetry["total_route_decisions"]),
            fallback_count=int(telemetry["fallback_count"]),
        )
    finally:
        if previous is not None:
            os.environ[_MISSING_API_KEY_ENV] = previous


def _scenario_budget_overrun() -> AgentBenchmarkMetrics:
    with TemporaryDirectory(prefix="claude-bridge-agent-bench-") as tmp:
        source = Path(tmp) / "large.py"
        source.write_text("payload = '" + ("x" * 256) + "'\n", encoding="utf-8")
        spec = TaskSpec(
            task_id="budget_overrun",
            kind="research",
            goal="budget overrun",
            agent_name="research_agent",
            read_set=(str(source),),
        )
        manifest = build_context_manifest(
            task=spec,
            run_id="run",
            session_id="bench",
            context={"token_budget": 1},
        )
        ok = manifest.estimated_tokens > 1 and manifest.budget_ledger.within_budget is False
        return _metrics_from_manifest(manifest, verified_success=ok)


def _scenario_durable_dag_reconstruct() -> AgentBenchmarkMetrics:
    with TemporaryDirectory(prefix="claude-bridge-agent-dag-bench-") as tmp:
        store = AgentDagStore(Path(tmp) / "dag")
        node_id = make_node_id(
            run_id="run_bench",
            task_id="task_bench",
            agent_name="research_agent",
            kind="research",
            read_set=("src",),
            write_set=("docs",),
        )
        artifact_id = make_artifact_id(
            run_id="run_bench",
            node_id=node_id,
            kind="findings",
            digest="sha256:test",
        )
        store.append_run(
            AgentDagRunRecord(
                run_id="run_bench",
                goal="reconstruct durable records",
                status="completed",
                created_at=1.0,
                updated_at=2.0,
                root_node_ids=(node_id,),
            )
        )
        store.append_node(
            AgentDagNodeRecord(
                node_id=node_id,
                run_id="run_bench",
                task_id="task_bench",
                agent_name="research_agent",
                kind="research",
                status="completed",
                read_set=("src",),
                write_set=("docs",),
                artifact_ids=(artifact_id,),
                idempotency_key=make_node_idempotency_key(
                    run_id="run_bench",
                    task_id="task_bench",
                    agent_name="research_agent",
                    kind="research",
                    read_set=("src",),
                    write_set=("docs",),
                ),
                created_at=1.0,
                updated_at=2.0,
            )
        )
        store.append_artifact(
            AgentDagArtifactRecord(
                artifact_id=artifact_id,
                run_id="run_bench",
                node_id=node_id,
                kind="findings",
                digest="sha256:test",
                summary="bench",
                path="",
                created_at=2.0,
            )
        )
        view = store.reconstruct_run("run_bench")
        ok = (
            view.run.status == "completed"
            and len(view.nodes) == 1
            and view.nodes[0].artifact_ids == (artifact_id,)
            and len(view.artifacts) == 1
            and view.artifacts[0].node_id == node_id
        )
        return AgentBenchmarkMetrics(
            verified_success=ok,
            trace_complete=ok,
        )


def _scenario_dag_readonly_dependency_order() -> AgentBenchmarkMetrics:
    class EchoAgent(BaseAgent):
        def __init__(self) -> None:
            super().__init__("research_agent")
            self.calls: list[str] = []

        async def execute(self, task: str, context: dict[str, Any]) -> AgentResult:
            self.calls.append(task)
            return AgentResult.success(
                findings=[task],
                artifacts={"findings": {"task": task}},
                agent_name=self.name,
            )

    with TemporaryDirectory(prefix="claude-bridge-agent-dag-scheduler-bench-") as tmp:
        store = AgentDagStore(Path(tmp) / "dag")
        _append_benchmark_run(store, "run_scheduler")
        first = _benchmark_node(run_id="run_scheduler", task_id="first", task="first")
        second = _benchmark_node(
            run_id="run_scheduler",
            task_id="second",
            task="second",
            dependencies=(first.node_id,),
        )
        store.append_node_record(first)
        store.append_node_record(second)
        agent = EchoAgent()
        result = AgentDagScheduler(store, [agent]).run_until_blocked(
            "run_scheduler",
            max_steps=4,
        )
        nodes = {node.task_id: node for node in store.latest_node_records("run_scheduler")}
        ok = (
            result.ran == 2
            and agent.calls == ["first", "second"]
            and nodes["first"].status == "completed"
            and nodes["second"].status == "completed"
        )
        return AgentBenchmarkMetrics(verified_success=ok, trace_complete=ok)


def _scenario_dag_completed_node_not_rerun() -> AgentBenchmarkMetrics:
    class CountingAgent(BaseAgent):
        def __init__(self) -> None:
            super().__init__("research_agent")
            self.calls = 0

        async def execute(self, task: str, context: dict[str, Any]) -> AgentResult:
            self.calls += 1
            return AgentResult.success(findings=[task], agent_name=self.name)

    with TemporaryDirectory(prefix="claude-bridge-agent-dag-scheduler-bench-") as tmp:
        store = AgentDagStore(Path(tmp) / "dag")
        _append_benchmark_run(store, "run_restart")
        store.append_node_record(
            _benchmark_node(
                run_id="run_restart",
                task_id="already_done",
                task="already done",
                status="completed",
                artifact_ids=("findings",),
            )
        )
        agent = CountingAgent()
        result = AgentDagScheduler(store, [agent]).run_until_blocked("run_restart", max_steps=2)
        node = store.latest_node_records("run_restart")[0]
        ok = result.ran == 0 and agent.calls == 0 and node.status == "completed"
        return AgentBenchmarkMetrics(verified_success=ok, trace_complete=ok)


def _scenario_dag_retry_cap_same_failure() -> AgentBenchmarkMetrics:
    class FailingAgent(BaseAgent):
        def __init__(self) -> None:
            super().__init__("research_agent")
            self.calls = 0

        async def execute(self, task: str, context: dict[str, Any]) -> AgentResult:
            self.calls += 1
            return AgentResult.failure(error="same failure", agent_name=self.name)

    with TemporaryDirectory(prefix="claude-bridge-agent-dag-scheduler-bench-") as tmp:
        store = AgentDagStore(Path(tmp) / "dag")
        _append_benchmark_run(store, "run_retry")
        store.append_node_record(_benchmark_node(run_id="run_retry", task_id="retry", task="retry"))
        agent = FailingAgent()
        result = AgentDagScheduler(store, [agent], max_retries=1).run_until_blocked(
            "run_retry",
            max_steps=5,
        )
        node = store.latest_node_records("run_retry")[0]
        ok = (
            result.ran == 2
            and agent.calls == 2
            and node.status == "failed"
            and node.failure_class == "unknown_failure"
            and node.retry_count == 1
        )
        return AgentBenchmarkMetrics(
            verified_success=ok,
            trace_complete=ok,
            retry_count=node.retry_count,
        )


def _scenario_dag_mutation_write_set_overlap_blocked() -> AgentBenchmarkMetrics:
    class MutatingAgent(BaseAgent):
        def __init__(self) -> None:
            super().__init__("research_agent")
            self.calls: list[str] = []

        async def execute(self, task: str, context: dict[str, Any]) -> AgentResult:
            self.calls.append(task)
            return AgentResult.success(findings=[task], agent_name=self.name)

    with TemporaryDirectory(prefix="claude-bridge-agent-dag-scheduler-bench-") as tmp:
        store = AgentDagStore(Path(tmp) / "dag")
        _append_benchmark_run(store, "run_write_overlap")
        store.append_node_record(
            _benchmark_node(
                run_id="run_write_overlap",
                task_id="mutate_a",
                task="mutate a",
                write_set=("src/shared.py",),
                permissions={"allow_mutation": True, "allowed_tools": ["file_write"]},
            )
        )
        store.append_node_record(
            _benchmark_node(
                run_id="run_write_overlap",
                task_id="mutate_b",
                task="mutate b",
                write_set=("src/shared.py",),
                permissions={"allow_mutation": True, "allowed_tools": ["file_write"]},
            )
        )
        agent = MutatingAgent()
        result = AgentDagScheduler(store, [agent], concurrency=2).run_once("run_write_overlap")
        nodes = {node.task_id: node for node in store.latest_node_records("run_write_overlap")}
        conflicts = store.load_conflicts("run_write_overlap")
        ok = (
            result.ran == 1
            and result.blocked == 1
            and nodes["mutate_a"].status == "completed"
            and nodes["mutate_b"].status == "blocked"
            and len(conflicts) == 1
            and conflicts[0].type == "overlapping_write_set"
            and conflicts[0].files == ("src/shared.py",)
        )
        return AgentBenchmarkMetrics(verified_success=ok, trace_complete=ok)


def _scenario_verifier_required_for_mutation_success() -> AgentBenchmarkMetrics:
    class MutatingAgent(BaseAgent):
        async def execute(self, task: str, context: dict[str, Any]) -> AgentResult:
            return AgentResult.success(
                findings=[task],
                artifacts={"mutation": {"task": task}},
                agent_name=self.name,
            )

    with TemporaryDirectory(prefix="claude-bridge-agent-verifier-bench-") as tmp:
        store = AgentDagStore(Path(tmp) / "dag")
        _append_benchmark_run(store, "run_verifier")
        mutation = _benchmark_node(
            run_id="run_verifier",
            task_id="mutate",
            task="mutate",
            write_set=("src/app.py",),
            permissions={"allow_mutation": True, "allowed_tools": ["file_write"]},
        )
        store.append_node_record(mutation)
        scheduler = AgentDagScheduler(store, [MutatingAgent("research_agent")])
        scheduler.run_until_blocked("run_verifier", max_steps=2)
        completed_mutation = store.latest_node_records("run_verifier")[0]
        gated_before_verifier = store.load_run_view("run_verifier").run.status == "pending"
        artifact_id = completed_mutation.artifact_ids[0]
        store.append_artifact_record(
            AgentDagArtifactRecord(
                artifact_id=artifact_id,
                run_id="run_verifier",
                node_id=completed_mutation.node_id,
                kind="mutation",
                digest="sha256:test",
                summary="mutation artifact",
                path="",
                created_at=2.0,
            )
        )
        verifier = _benchmark_node(
            run_id="run_verifier",
            task_id="verify_mutation",
            task="verify mutation",
            kind="verifier",
            agent_name="verification_agent",
            dependencies=(completed_mutation.node_id,),
            artifact_ids=(artifact_id,),
            metadata={"verifies_node_id": completed_mutation.node_id},
        )
        store.append_node_record(verifier)
        scheduler.run_until_blocked("run_verifier", max_steps=3)
        view = store.load_run_view("run_verifier")
        nodes = {node.task_id: node for node in view.nodes}
        ok = (
            gated_before_verifier
            and nodes["mutate"].status == "completed"
            and nodes["verify_mutation"].status == "completed"
            and view.run.status == "completed"
            and nodes["verify_mutation"].metadata["verifier_output"]["verified"] is True
        )
        return AgentBenchmarkMetrics(verified_success=ok, trace_complete=ok)


def _scenario_conflict_record_for_overlapping_patch() -> AgentBenchmarkMetrics:
    conflicts = ConflictDetector().detect_patch_conflicts(
        "run_patch_conflict",
        (
            PatchHunk(
                node_id="node_a",
                file_path="src/app.py",
                start_line=10,
                end_line=20,
            ),
            PatchHunk(
                node_id="node_b",
                file_path="src/app.py",
                start_line=15,
                end_line=30,
            ),
        ),
        now=1.0,
    )
    ok = (
        len(conflicts) == 1
        and conflicts[0].run_id == "run_patch_conflict"
        and conflicts[0].type == "overlapping_patch"
        and conflicts[0].files == ("src/app.py",)
        and conflicts[0].signal == "patch hunks overlap"
    )
    return AgentBenchmarkMetrics(verified_success=ok, trace_complete=ok)


def _scenario_low_relevance_artifact_not_promoted() -> AgentBenchmarkMetrics:
    low = AgentDagArtifactRecord(
        artifact_id="artifact_low",
        run_id="run_relevance",
        node_id="node_low",
        kind="finding",
        digest="sha256:low",
        summary="low relevance finding",
        path="",
        created_at=1.0,
        metadata={"relevance_score": 0.1},
    )
    high = AgentDagArtifactRecord(
        artifact_id="artifact_high",
        run_id="run_relevance",
        node_id="node_high",
        kind="finding",
        digest="sha256:high",
        summary="high relevance finding",
        path="",
        created_at=1.0,
        metadata={"relevance_score": 0.9},
    )
    policy = EnforcementPolicy()
    promotable = policy.promotable_artifacts((low, high))
    audit_only = policy.audit_only_artifacts((low, high))
    ok = promotable == (high,) and audit_only == (low,)
    return AgentBenchmarkMetrics(verified_success=ok, trace_complete=ok)


def _scenario_no_bypass() -> AgentBenchmarkMetrics:
    findings = scan_subagent_process_bypass()
    return AgentBenchmarkMetrics(
        verified_success=not findings,
        trace_complete=True,
        tool_call_count=0,
    )


def _append_benchmark_run(store: AgentDagStore, run_id: str) -> None:
    store.append_run_record(
        AgentDagRunRecord(
            run_id=run_id,
            goal="benchmark scheduler",
            status="pending",
            created_at=1.0,
            updated_at=1.0,
        )
    )


def _benchmark_node(
    *,
    run_id: str,
    task_id: str,
    task: str,
    status: AgentDagStatus = "pending",
    dependencies: tuple[str, ...] = (),
    artifact_ids: tuple[str, ...] = (),
    write_set: tuple[str, ...] = (),
    permissions: dict[str, Any] | None = None,
    kind: str = "research",
    agent_name: str = "research_agent",
    metadata: dict[str, Any] | None = None,
) -> AgentDagNodeRecord:
    node_id = make_node_id(
        run_id=run_id,
        task_id=task_id,
        agent_name=agent_name,
        kind=kind,
        read_set=("src",),
        write_set=write_set,
    )
    return AgentDagNodeRecord(
        node_id=node_id,
        run_id=run_id,
        task_id=task_id,
        agent_name=agent_name,
        kind=kind,
        status=cast(AgentDagStatus, status),
        dependencies=dependencies,
        read_set=("src",),
        write_set=write_set,
        idempotency_key=make_node_idempotency_key(
            run_id=run_id,
            task_id=task_id,
            agent_name=agent_name,
            kind=kind,
            read_set=("src",),
            write_set=write_set,
        ),
        artifact_ids=artifact_ids,
        created_at=1.0,
        updated_at=1.0,
        metadata={
            "artifact_ids": list(artifact_ids),
            "permissions": permissions or {},
            "task": task,
            **(metadata or {}),
        },
    )


def _record(task_id: str, agent_name: str, task_kind: str) -> AgentRunRecord:
    return start_agent_run(task_id=task_id, agent_name=agent_name, task_kind=task_kind)


def _metrics_from_record(
    record: AgentRunRecord,
    *,
    verified_success: bool,
    policy_denial_correct: bool = False,
) -> AgentBenchmarkMetrics:
    return AgentBenchmarkMetrics(
        verified_success=verified_success,
        tool_call_count=len(record.tool_calls),
        trace_complete=_trace_complete(record),
        context_manifest_present=bool(record.context_manifest_id),
        mission_brief_present=bool(record.mission_brief_id),
        policy_denial_correct=policy_denial_correct,
    )


def _metrics_from_manifest(
    manifest: ContextManifest,
    *,
    verified_success: bool,
) -> AgentBenchmarkMetrics:
    return AgentBenchmarkMetrics(
        verified_success=verified_success,
        trace_complete=True,
        context_manifest_present=bool(manifest.manifest_id),
        mission_brief_present=False,
        estimated_tokens=manifest.estimated_tokens,
        duplicate_context_ratio=manifest.duplicate_ratio,
    )


def _trace_complete(record: AgentRunRecord) -> bool:
    return bool(record.run_id and record.task_id and record.agent_name and record.started_at)


def _has_tool_call(record: AgentRunRecord, tool: str, status: str) -> bool:
    return any(
        call.get("tool") == tool and call.get("status") == status for call in record.tool_calls
    )
