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
from typing import Any

from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.broker import AgentToolBroker
from claude_bridge.agents.context_manifest import build_context_manifest
from claude_bridge.agents.contracts import ContextManifest, TaskPermissions, TaskSpec
from claude_bridge.agents.dag_records import (
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
        AgentBenchmarkScenario("route_telemetry_local_disabled", _scenario_route_local_disabled),
        AgentBenchmarkScenario("route_telemetry_provider_fallback", _scenario_provider_fallback),
        AgentBenchmarkScenario("context_manifest_token_budget_overrun", _scenario_budget_overrun),
        AgentBenchmarkScenario("durable_dag_reconstruct_run", _scenario_durable_dag_reconstruct),
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


def _scenario_no_bypass() -> AgentBenchmarkMetrics:
    findings = scan_subagent_process_bypass()
    return AgentBenchmarkMetrics(
        verified_success=not findings,
        trace_complete=True,
        tool_call_count=0,
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
        estimated_tokens=manifest.estimated_tokens,
        duplicate_context_ratio=manifest.duplicate_ratio,
    )


def _trace_complete(record: AgentRunRecord) -> bool:
    return bool(record.run_id and record.task_id and record.agent_name and record.started_at)


def _has_tool_call(record: AgentRunRecord, tool: str, status: str) -> bool:
    return any(
        call.get("tool") == tool and call.get("status") == status
        for call in record.tool_calls
    )
