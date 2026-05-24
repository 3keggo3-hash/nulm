"""Release gates for deterministic agent benchmark runs."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_bridge.agents.benchmark_harness import (
    AgentBenchmarkRun,
    AgentBenchmarkScenarioResult,
    run_agent_benchmark,
)

AGENT_BENCHMARK_GATES_SCHEMA_VERSION = "agent_benchmark_gates.v1"
TRACE_COMPLETENESS_THRESHOLD = 0.95
DUPLICATE_CONTEXT_RATIO_THRESHOLD = 0.25

_CONTEXT_MANIFEST_SCENARIOS = frozenset(
    {
        "research_context_manifest_selection",
        "context_manifest_token_budget_overrun",
    }
)
_ROUTE_TELEMETRY_SCENARIOS = frozenset(
    {
        "route_telemetry_local_disabled",
        "route_telemetry_provider_fallback",
    }
)
_TRACE_EXCLUDED_SCENARIOS = _ROUTE_TELEMETRY_SCENARIOS
_EXPECTED_FALLBACK_COUNTS = {
    "route_telemetry_provider_fallback": 1,
    "route_telemetry_local_disabled": 0,
}
_EXPECTED_DUPLICATION_SCENARIOS: frozenset[str] = frozenset()


@dataclass(frozen=True)
class AgentBenchmarkGateCheck:
    """One pass/fail benchmark gate decision."""

    name: str
    ok: bool
    severity: str = "critical"
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "name": self.name,
            "ok": self.ok,
            "severity": self.severity,
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True)
class AgentBenchmarkGateResult:
    """Structured release gate result for an agent benchmark run."""

    checks: tuple[AgentBenchmarkGateCheck, ...]
    benchmark: dict[str, Any]
    schema_version: str = AGENT_BENCHMARK_GATES_SCHEMA_VERSION

    @property
    def ok(self) -> bool:
        return self.failed == 0

    @property
    def passed(self) -> int:
        return sum(1 for check in self.checks if check.ok)

    @property
    def failed(self) -> int:
        return len(self.checks) - self.passed

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "passed": self.passed,
            "failed": self.failed,
            "checks": [check.to_dict() for check in self.checks],
            "benchmark": self.benchmark,
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize the gate result as stable-key JSON."""
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    def save_json(self, path: str | Path, *, indent: int | None = 2) -> None:
        """Persist gate results only when a caller explicitly provides a path."""
        Path(path).write_text(self.to_json(indent=indent) + "\n", encoding="utf-8")


def evaluate_agent_benchmark_gates(
    run: AgentBenchmarkRun | None = None,
) -> AgentBenchmarkGateResult:
    """Evaluate deterministic Phase 6 release gates against an agent benchmark run."""
    benchmark_run = run or run_agent_benchmark()
    results_by_name = {result.name: result for result in benchmark_run.results}
    checks = (
        _benchmark_success(benchmark_run),
        _trace_completeness(benchmark_run),
        _context_manifest_presence(results_by_name),
        _route_telemetry_presence(results_by_name),
        _fallback_expected_only(benchmark_run),
        _broker_denial_correct(results_by_name),
        _direct_subagent_bypass_absent(results_by_name),
        _duplicate_context_ratio_not_worse_than_threshold(benchmark_run),
    )
    return AgentBenchmarkGateResult(
        checks=checks,
        benchmark=_compact_benchmark_summary(benchmark_run),
    )


def _benchmark_success(run: AgentBenchmarkRun) -> AgentBenchmarkGateCheck:
    failures = [result.name for result in run.results if not result.ok]
    ok = not failures
    return AgentBenchmarkGateCheck(
        name="benchmark_success",
        ok=ok,
        message="" if ok else "One or more benchmark scenarios failed.",
        details={
            "scenario_count": len(run.results),
            "passed": run.passed,
            "failed": run.failed,
            "failed_scenarios": failures,
        },
    )


def _trace_completeness(run: AgentBenchmarkRun) -> AgentBenchmarkGateCheck:
    trace_results = [
        result for result in run.results if result.name not in _TRACE_EXCLUDED_SCENARIOS
    ]
    complete = [result.name for result in trace_results if result.metrics.trace_complete]
    incomplete = [result.name for result in trace_results if not result.metrics.trace_complete]
    ratio = len(complete) / len(trace_results) if trace_results else 1.0
    ok = ratio >= TRACE_COMPLETENESS_THRESHOLD
    return AgentBenchmarkGateCheck(
        name="trace_completeness",
        ok=ok,
        message="" if ok else "Trace completeness fell below the release threshold.",
        details={
            "threshold": TRACE_COMPLETENESS_THRESHOLD,
            "trace_scenario_count": len(trace_results),
            "complete_count": len(complete),
            "ratio": round(ratio, 6),
            "incomplete_scenarios": incomplete,
            "excluded_scenarios": sorted(_TRACE_EXCLUDED_SCENARIOS),
        },
    )


def _context_manifest_presence(
    results_by_name: dict[str, AgentBenchmarkScenarioResult],
) -> AgentBenchmarkGateCheck:
    missing = [
        name
        for name in sorted(_CONTEXT_MANIFEST_SCENARIOS)
        if not _scenario_metric(results_by_name, name, "context_manifest_present")
    ]
    ok = not missing
    return AgentBenchmarkGateCheck(
        name="context_manifest_presence",
        ok=ok,
        message="" if ok else "Context benchmark scenarios did not report manifests.",
        details={
            "required_scenarios": sorted(_CONTEXT_MANIFEST_SCENARIOS),
            "missing_or_false_scenarios": missing,
        },
    )


def _route_telemetry_presence(
    results_by_name: dict[str, AgentBenchmarkScenarioResult],
) -> AgentBenchmarkGateCheck:
    missing = [
        name
        for name in sorted(_ROUTE_TELEMETRY_SCENARIOS)
        if _scenario_metric_int(results_by_name, name, "route_decision_count") <= 0
    ]
    ok = not missing
    return AgentBenchmarkGateCheck(
        name="route_telemetry_presence",
        ok=ok,
        message="" if ok else "Route telemetry scenarios did not report route decisions.",
        details={
            "required_scenarios": sorted(_ROUTE_TELEMETRY_SCENARIOS),
            "missing_or_zero_scenarios": missing,
        },
    )


def _fallback_expected_only(run: AgentBenchmarkRun) -> AgentBenchmarkGateCheck:
    mismatches: list[dict[str, Any]] = []
    for result in run.results:
        actual = result.metrics.fallback_count
        expected = _EXPECTED_FALLBACK_COUNTS.get(result.name, 0)
        if actual != expected:
            mismatches.append(
                {
                    "scenario": result.name,
                    "expected": expected,
                    "actual": actual,
                }
            )
    ok = not mismatches
    return AgentBenchmarkGateCheck(
        name="fallback_expected_only",
        ok=ok,
        message="" if ok else "Fallback counts differed from benchmark expectations.",
        details={
            "expected_counts": dict(_EXPECTED_FALLBACK_COUNTS),
            "mismatches": mismatches,
        },
    )


def _broker_denial_correct(
    results_by_name: dict[str, AgentBenchmarkScenarioResult],
) -> AgentBenchmarkGateCheck:
    scenario = "permission_denied_broker_tool"
    result = results_by_name.get(scenario)
    ok = bool(result and result.metrics.policy_denial_correct)
    return AgentBenchmarkGateCheck(
        name="broker_denial_correct",
        ok=ok,
        message="" if ok else "Broker permission-denial scenario was not marked correct.",
        details={
            "scenario": scenario,
            "present": result is not None,
            "policy_denial_correct": bool(result and result.metrics.policy_denial_correct),
        },
    )


def _direct_subagent_bypass_absent(
    results_by_name: dict[str, AgentBenchmarkScenarioResult],
) -> AgentBenchmarkGateCheck:
    scenario = "no_direct_subagent_subprocess_bypass"
    result = results_by_name.get(scenario)
    ok = bool(result and result.ok and result.metrics.verified_success)
    return AgentBenchmarkGateCheck(
        name="direct_subagent_bypass_absent",
        ok=ok,
        message="" if ok else "Direct subagent subprocess bypass scenario failed.",
        details={
            "scenario": scenario,
            "present": result is not None,
            "scenario_ok": bool(result and result.ok),
            "verified_success": bool(result and result.metrics.verified_success),
        },
    )


def _duplicate_context_ratio_not_worse_than_threshold(
    run: AgentBenchmarkRun,
) -> AgentBenchmarkGateCheck:
    violations = []
    for result in run.results:
        if result.name in _EXPECTED_DUPLICATION_SCENARIOS:
            continue
        ratio = result.metrics.duplicate_context_ratio
        if ratio > DUPLICATE_CONTEXT_RATIO_THRESHOLD:
            violations.append(
                {
                    "scenario": result.name,
                    "threshold": DUPLICATE_CONTEXT_RATIO_THRESHOLD,
                    "actual": ratio,
                }
            )
    ok = not violations
    return AgentBenchmarkGateCheck(
        name="duplicate_context_ratio_not_worse_than_threshold",
        ok=ok,
        message="" if ok else "Duplicate context ratio exceeded the release threshold.",
        details={
            "threshold": DUPLICATE_CONTEXT_RATIO_THRESHOLD,
            "expected_duplication_scenarios": sorted(_EXPECTED_DUPLICATION_SCENARIOS),
            "violations": violations,
        },
    )


def _scenario_metric(
    results_by_name: dict[str, AgentBenchmarkScenarioResult],
    name: str,
    metric: str,
) -> Any:
    result = results_by_name.get(name)
    if result is None:
        return None
    return getattr(result.metrics, metric)


def _scenario_metric_int(
    results_by_name: dict[str, AgentBenchmarkScenarioResult],
    name: str,
    metric: str,
) -> int:
    value = _scenario_metric(results_by_name, name, metric)
    return int(value) if value is not None else 0


def _compact_benchmark_summary(run: AgentBenchmarkRun) -> dict[str, Any]:
    return {
        "schema_version": run.schema_version,
        "duration_ms": round(run.duration_ms, 3),
        "scenario_count": len(run.results),
        "passed": run.passed,
        "failed": run.failed,
        "results": [
            {
                "name": result.name,
                "ok": result.ok,
                "failure_class": result.failure_class,
            }
            for result in run.results
        ],
    }
