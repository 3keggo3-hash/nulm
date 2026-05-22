"""Tests for the deterministic agent benchmark harness."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import subprocess

from claude_bridge.agents.benchmark_harness import (
    AGENT_BENCHMARK_SCHEMA_VERSION,
    AgentBenchmarkMetrics,
    AgentBenchmarkScenario,
    run_agent_benchmark,
    scan_subagent_process_bypass,
)


def test_benchmark_run_returns_schema_version() -> None:
    run = run_agent_benchmark()

    assert run.schema_version == AGENT_BENCHMARK_SCHEMA_VERSION
    assert run.to_dict()["schema_version"] == "agent_benchmark_run.v1"


def test_all_default_scenarios_pass() -> None:
    run = run_agent_benchmark()

    assert run.failed == 0
    assert run.passed == 11
    assert run.to_dict()["scenario_count"] == 11


def test_result_payload_is_json_serializable() -> None:
    run = run_agent_benchmark()

    encoded = json.dumps(run.to_dict(), sort_keys=True)
    decoded = json.loads(encoded)

    assert decoded["schema_version"] == "agent_benchmark_run.v1"
    assert isinstance(decoded["results"], list)


def test_scenario_failures_are_captured_not_raised() -> None:
    def boom() -> AgentBenchmarkMetrics:
        raise RuntimeError("scenario exploded")

    run = run_agent_benchmark([AgentBenchmarkScenario("boom", boom)])
    result = run.results[0]

    assert run.failed == 1
    assert result.ok is False
    assert result.failure_class == "RuntimeError"
    assert result.message == "scenario exploded"


def test_metrics_include_manifest_and_route_fields() -> None:
    run = run_agent_benchmark()
    payload = run.to_dict()
    metrics = {result["name"]: result["metrics"] for result in payload["results"]}

    assert metrics["research_context_manifest_selection"]["context_manifest_present"] is True
    assert metrics["research_context_manifest_selection"]["estimated_tokens"] > 0
    assert "duplicate_context_ratio" in metrics["research_context_manifest_selection"]
    assert metrics["route_telemetry_local_disabled"]["route_decision_count"] == 1
    assert metrics["route_telemetry_provider_fallback"]["fallback_count"] == 1
    assert metrics["permission_denied_broker_tool"]["policy_denial_correct"] is True


def test_no_cloud_provider_keys_are_required(monkeypatch) -> None:
    monkeypatch.setenv("__CLAUDE_BRIDGE_AGENT_BENCHMARK_MISSING_API_KEY__", "should-be-removed")

    run = run_agent_benchmark()

    assert run.failed == 0
    fallback = next(
        result for result in run.results if result.name == "route_telemetry_provider_fallback"
    )
    assert fallback.metrics.fallback_count == 1


def test_benchmark_does_not_mutate_repository() -> None:
    before = _git_status()

    run = run_agent_benchmark()

    after = _git_status()
    assert run.failed == 0
    assert after == before


def test_source_scan_bypass_scenario_fails_on_process_api(tmp_path) -> None:
    target = tmp_path / "bad_agent.py"
    target.write_text(
        "import subprocess\n\n"
        "def run() -> None:\n"
        "    subprocess.Popen(['echo', 'bad'])\n",
        encoding="utf-8",
    )

    findings = scan_subagent_process_bypass([target])

    assert findings
    assert any("subprocess" in finding or "Popen" in finding for finding in findings)


def test_save_json_only_when_path_is_explicit(tmp_path) -> None:
    output = tmp_path / "agent-benchmark.json"

    run = run_agent_benchmark(save_path=output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "agent_benchmark_run.v1"
    assert payload["scenario_count"] == len(run.results)


def _git_status() -> str:
    result = subprocess.run(
        ["git", "status", "--short"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout
