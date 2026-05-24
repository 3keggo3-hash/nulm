"""Tests for deterministic agent benchmark release gates."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json

from claude_bridge.agents.benchmark_gates import (
    AGENT_BENCHMARK_GATES_SCHEMA_VERSION,
    AgentBenchmarkGateResult,
    evaluate_agent_benchmark_gates,
)
from claude_bridge.agents.benchmark_harness import (
    AgentBenchmarkMetrics,
    AgentBenchmarkRun,
    AgentBenchmarkScenarioResult,
)


def test_default_benchmark_gates_pass() -> None:
    result = evaluate_agent_benchmark_gates()

    assert result.schema_version == AGENT_BENCHMARK_GATES_SCHEMA_VERSION
    assert result.ok is True
    assert result.passed == 8
    assert result.failed == 0


def test_failed_benchmark_scenario_makes_benchmark_success_fail() -> None:
    run = _benchmark_run(
        _scenario("typed_task_dispatch", ok=False, verified_success=False),
    )

    result = evaluate_agent_benchmark_gates(run)
    check = _check(result, "benchmark_success")

    assert check["ok"] is False
    assert check["details"]["failed_scenarios"] == ["typed_task_dispatch"]


def test_trace_completeness_below_threshold_fails() -> None:
    run = _benchmark_run(
        _scenario("typed_task_dispatch", trace_complete=False),
    )

    result = evaluate_agent_benchmark_gates(run)
    check = _check(result, "trace_completeness")

    assert check["ok"] is False
    assert "typed_task_dispatch" in check["details"]["incomplete_scenarios"]


def test_missing_route_telemetry_fails() -> None:
    run = _benchmark_run(
        _scenario("route_telemetry_provider_fallback", route_decision_count=0),
    )

    result = evaluate_agent_benchmark_gates(run)
    check = _check(result, "route_telemetry_presence")

    assert check["ok"] is False
    assert "route_telemetry_provider_fallback" in check["details"]["missing_or_zero_scenarios"]


def test_unexpected_fallback_fails() -> None:
    run = _benchmark_run(
        _scenario("typed_task_dispatch", fallback_count=1),
    )

    result = evaluate_agent_benchmark_gates(run)
    check = _check(result, "fallback_expected_only")

    assert check["ok"] is False
    assert check["details"]["mismatches"] == [
        {"scenario": "typed_task_dispatch", "expected": 0, "actual": 1}
    ]


def test_broker_denial_missing_fails() -> None:
    run = _benchmark_run(
        _scenario("permission_denied_broker_tool", policy_denial_correct=False),
    )

    result = evaluate_agent_benchmark_gates(run)
    check = _check(result, "broker_denial_correct")

    assert check["ok"] is False
    assert check["details"]["policy_denial_correct"] is False


def test_bypass_scenario_failure_fails() -> None:
    run = _benchmark_run(
        _scenario("no_direct_subagent_subprocess_bypass", ok=False, verified_success=False),
    )

    result = evaluate_agent_benchmark_gates(run)
    check = _check(result, "direct_subagent_bypass_absent")

    assert check["ok"] is False
    assert check["details"]["scenario_ok"] is False


def test_duplicate_context_ratio_over_threshold_fails() -> None:
    run = _benchmark_run(
        _scenario("research_context_manifest_selection", duplicate_context_ratio=0.5),
    )

    result = evaluate_agent_benchmark_gates(run)
    check = _check(result, "duplicate_context_ratio_not_worse_than_threshold")

    assert check["ok"] is False
    assert check["details"]["violations"] == [
        {
            "scenario": "research_context_manifest_selection",
            "threshold": 0.25,
            "actual": 0.5,
        }
    ]


def test_result_payload_is_json_serializable() -> None:
    result = evaluate_agent_benchmark_gates(_benchmark_run())

    encoded = json.dumps(result.to_dict(), sort_keys=True)
    decoded = json.loads(encoded)

    assert decoded["schema_version"] == "agent_benchmark_gates.v1"
    assert decoded["ok"] is True
    assert isinstance(decoded["checks"], list)


def test_save_json_writes_only_when_explicitly_requested(tmp_path) -> None:
    output = tmp_path / "agent-benchmark-gates.json"
    result = evaluate_agent_benchmark_gates(_benchmark_run())

    result.to_json()

    assert not output.exists()

    result.save_json(output)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "agent_benchmark_gates.v1"
    assert payload["passed"] == 8


def _check(result: AgentBenchmarkGateResult, name: str) -> dict[str, object]:
    checks = result.to_dict()["checks"]
    return next(check for check in checks if check["name"] == name)


def _benchmark_run(
    *overrides: AgentBenchmarkScenarioResult,
) -> AgentBenchmarkRun:
    scenarios = {
        "typed_task_dispatch": _scenario("typed_task_dispatch"),
        "malformed_legacy_task_fail_closed": _scenario("malformed_legacy_task_fail_closed"),
        "missing_agent_typed_failure": _scenario("missing_agent_typed_failure"),
        "permission_denied_broker_tool": _scenario(
            "permission_denied_broker_tool",
            policy_denial_correct=True,
        ),
        "git_status_agent_tool_broker": _scenario("git_status_agent_tool_broker"),
        "research_context_manifest_selection": _scenario(
            "research_context_manifest_selection",
            context_manifest_present=True,
        ),
        "route_telemetry_local_disabled": _scenario(
            "route_telemetry_local_disabled",
            trace_complete=False,
            route_decision_count=1,
        ),
        "route_telemetry_provider_fallback": _scenario(
            "route_telemetry_provider_fallback",
            trace_complete=False,
            route_decision_count=1,
            fallback_count=1,
        ),
        "context_manifest_token_budget_overrun": _scenario(
            "context_manifest_token_budget_overrun",
            context_manifest_present=True,
        ),
        "no_direct_subagent_subprocess_bypass": _scenario("no_direct_subagent_subprocess_bypass"),
    }
    for override in overrides:
        scenarios[override.name] = override
    return AgentBenchmarkRun(
        started_at=1.0,
        ended_at=2.0,
        results=tuple(scenarios.values()),
    )


def _scenario(
    name: str,
    *,
    ok: bool = True,
    verified_success: bool = True,
    trace_complete: bool = True,
    context_manifest_present: bool = False,
    policy_denial_correct: bool = False,
    route_decision_count: int = 0,
    fallback_count: int = 0,
    duplicate_context_ratio: float = 0.0,
) -> AgentBenchmarkScenarioResult:
    metrics = AgentBenchmarkMetrics(
        verified_success=verified_success,
        trace_complete=trace_complete,
        context_manifest_present=context_manifest_present,
        policy_denial_correct=policy_denial_correct,
        route_decision_count=route_decision_count,
        fallback_count=fallback_count,
        duplicate_context_ratio=duplicate_context_ratio,
    )
    return AgentBenchmarkScenarioResult(
        name=name,
        ok=ok,
        duration_ms=1.0,
        failure_class="" if ok else "ScenarioAssertionFailed",
        metrics=metrics,
    )
