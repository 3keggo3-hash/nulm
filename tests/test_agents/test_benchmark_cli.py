"""CLI tests for deterministic agent benchmark release gates."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json

from typer.testing import CliRunner

from claude_bridge import cli
from claude_bridge.agents.benchmark_gates import evaluate_agent_benchmark_gates
from claude_bridge.agents.benchmark_harness import (
    AgentBenchmarkMetrics,
    AgentBenchmarkRun,
    AgentBenchmarkScenarioResult,
)

runner = CliRunner()


def test_agent_benchmark_cli_emits_benchmark_and_gate_json() -> None:
    result = runner.invoke(cli.app, ["agent-benchmark"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "agent_benchmark_cli.v1"
    assert payload["ok"] is True
    assert payload["benchmark"]["schema_version"] == "agent_benchmark_run.v1"
    assert payload["gates"]["schema_version"] == "agent_benchmark_gates.v1"


def test_agent_benchmark_cli_gates_only_can_save_json(tmp_path) -> None:
    output = tmp_path / "agent-gates.json"

    result = runner.invoke(cli.app, ["agent-benchmark", "--gates-only", "--save", str(output)])

    assert result.exit_code == 0
    stdout_payload = json.loads(result.stdout)
    saved_payload = json.loads(output.read_text(encoding="utf-8"))
    assert stdout_payload == saved_payload
    assert saved_payload["schema_version"] == "agent_benchmark_gates.v1"
    assert saved_payload["ok"] is True


def test_agent_benchmark_cli_exits_nonzero_when_gates_fail(monkeypatch) -> None:
    run = AgentBenchmarkRun(
        started_at=1.0,
        ended_at=2.0,
        results=(
            AgentBenchmarkScenarioResult(
                name="typed_task_dispatch",
                ok=False,
                duration_ms=1.0,
                failure_class="ScenarioAssertionFailed",
                metrics=AgentBenchmarkMetrics(verified_success=False),
            ),
        ),
    )

    def fake_run_agent_benchmark() -> AgentBenchmarkRun:
        return run

    def fake_evaluate_agent_benchmark_gates(
        benchmark_run: AgentBenchmarkRun,
    ) -> object:
        assert benchmark_run is run
        return evaluate_agent_benchmark_gates(benchmark_run)

    monkeypatch.setattr(
        cli,
        "_agent_benchmark_runtime",
        lambda: (fake_run_agent_benchmark, fake_evaluate_agent_benchmark_gates),
    )

    result = runner.invoke(cli.app, ["agent-benchmark", "--gates-only"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["failed"] > 0
