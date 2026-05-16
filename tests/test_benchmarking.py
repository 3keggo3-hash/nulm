"""Tests for repo-scale benchmark helpers."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from claude_bridge import cli
from claude_bridge.benchmarking import compare_benchmark_to_baseline
from claude_bridge.benchmarking import load_benchmark_profile
from claude_bridge.benchmarking import run_index_and_relevance_benchmark
from claude_bridge.benchmarking import run_multi_query_benchmark

runner = CliRunner()


def _seed_benchmark_project(project: Path, *, files_per_group: int = 20) -> None:
    src = project / "src"
    auth_dir = src / "auth"
    session_dir = src / "session"
    billing_dir = src / "billing"
    auth_dir.mkdir(parents=True)
    session_dir.mkdir(parents=True)
    billing_dir.mkdir(parents=True)
    for index in range(files_per_group):
        (auth_dir / f"auth_service_{index:02d}.py").write_text(
            "class AuthService:\n"
            "    pass\n\n"
            "def login_user(email: str) -> bool:\n"
            '    """Create a session for a login."""\n'
            "    return True\n",
            encoding="utf-8",
        )
        (session_dir / f"session_store_{index:02d}.py").write_text(
            "def create_session(user_id: str) -> str:\n" "    return user_id\n",
            encoding="utf-8",
        )
        (billing_dir / f"payments_{index:02d}.py").write_text(
            "def charge_card() -> bool:\n" "    return True\n",
            encoding="utf-8",
        )


def _load_baseline() -> dict:
    fixture_path = Path(__file__).parent / "fixtures" / "benchmark_baseline.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


class TestBenchmarking:
    def test_load_benchmark_profile_reads_json_object(self, temp_project):
        profile_path = temp_project / "profile.json"
        profile_path.write_text(
            json.dumps({"path": "src", "query": "login auth session", "limit": 2}),
            encoding="utf-8",
        )

        profile = load_benchmark_profile(profile_path)
        assert profile["path"] == "src"
        assert profile["query"] == "login auth session"

    def test_run_index_and_relevance_benchmark_returns_timing_and_hits(self, temp_project):
        _seed_benchmark_project(temp_project)

        payload = run_index_and_relevance_benchmark(
            project_dir=temp_project,
            path="src",
            query="login auth session",
            limit=2,
            repeats=2,
        )

        assert payload["index_summary"]["source_files"] == 60
        assert payload["index_duration_ms"] >= 0
        assert len(payload["query_durations_ms"]) == 2
        assert payload["query_avg_duration_ms"] >= 0
        assert payload["top_results"][0]["path"] == "auth/auth_service_00.py"

    def test_compare_benchmark_to_baseline_passes_for_seeded_repo(self, temp_project):
        _seed_benchmark_project(temp_project)
        baseline = _load_baseline()

        payload = run_index_and_relevance_benchmark(
            project_dir=temp_project,
            path="src",
            query="login auth session",
            limit=2,
            repeats=2,
        )

        comparison = compare_benchmark_to_baseline(payload, baseline)
        assert comparison["ok"] is True
        assert comparison["failures"] == []

    def test_compare_benchmark_to_baseline_rejects_template_baseline(self):
        comparison = compare_benchmark_to_baseline(
            {
                "index_summary": {"source_files": 1},
                "index_duration_ms": 1,
                "query_avg_duration_ms": 1,
                "top_results": [{"path": "a.py"}],
            },
            {"name": "template", "status": "template", "instructions": "fill me"},
        )
        assert comparison["ok"] is False
        assert "not marked ready" in comparison["failures"][0]

    def test_benchmark_cli_can_emit_json(self, temp_project):
        _seed_benchmark_project(temp_project)

        result = runner.invoke(
            cli.app,
            [
                "benchmark",
                "--project-dir",
                str(temp_project),
                "--path",
                "src",
                "--query",
                "login auth session",
                "--repeats",
                "2",
                "--json",
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["top_results"][0]["path"] == "auth/auth_service_00.py"

    def test_benchmark_cli_can_compare_against_baseline(self, temp_project):
        _seed_benchmark_project(temp_project)
        baseline_path = Path(__file__).parent / "fixtures" / "benchmark_baseline.json"

        result = runner.invoke(
            cli.app,
            [
                "benchmark",
                "--project-dir",
                str(temp_project),
                "--path",
                "src",
                "--query",
                "login auth session",
                "--repeats",
                "2",
                "--baseline-file",
                str(baseline_path),
                "--json",
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["baseline_comparison"]["ok"] is True

    def test_benchmark_cli_can_use_profile_file(self, temp_project):
        _seed_benchmark_project(temp_project)
        fixture_dir = Path(__file__).parent / "fixtures"
        profile_path = temp_project / "profile.json"
        profile_path.write_text(
            json.dumps(
                {
                    "path": "src",
                    "query": "login auth session",
                    "limit": 2,
                    "repeats": 2,
                    "baseline_file": str(fixture_dir / "benchmark_baseline.json"),
                }
            ),
            encoding="utf-8",
        )

        result = runner.invoke(
            cli.app,
            [
                "benchmark",
                "--project-dir",
                str(temp_project),
                "--profile-file",
                str(profile_path),
                "--json",
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["query"] == "login auth session"
        assert payload["baseline_comparison"]["ok"] is True

    def test_benchmark_cli_rejects_invalid_numeric_profile_fields(self, temp_project):
        _seed_benchmark_project(temp_project)
        profile_path = temp_project / "bad_profile.json"
        profile_path.write_text(
            json.dumps({"path": "src", "query": "login auth session", "limit": "oops"}),
            encoding="utf-8",
        )

        result = runner.invoke(
            cli.app,
            [
                "benchmark",
                "--project-dir",
                str(temp_project),
                "--profile-file",
                str(profile_path),
            ],
        )

        assert result.exit_code == 1
        assert "Benchmark failed" in result.stdout


class TestMultiQueryBenchmark:
    def test_run_multi_query_benchmark_returns_per_query_results(self, temp_project):
        _seed_benchmark_project(temp_project)

        payload = run_multi_query_benchmark(
            project_dir=temp_project,
            path="src",
            queries=["login auth", "session", "billing payment"],
            limit=2,
            repeats_per_query=2,
        )

        assert payload["index_duration_ms"] >= 0
        assert len(payload["per_query_results"]) == 3
        assert payload["queries"] == ["login auth", "session", "billing payment"]
        assert all(r["query_avg_duration_ms"] >= 0 for r in payload["per_query_results"])

    def test_run_multi_query_benchmark_validates_empty_queries(self, temp_project):
        _seed_benchmark_project(temp_project)

        try:
            run_multi_query_benchmark(
                project_dir=temp_project,
                path="src",
                queries=[],
                limit=2,
                repeats_per_query=2,
            )
            raise AssertionError("Expected ValueError")
        except ValueError as exc:
            assert "queries list cannot be empty" in str(exc)

    def test_run_multi_query_benchmark_validates_whitespace_query(self, temp_project):
        _seed_benchmark_project(temp_project)

        try:
            run_multi_query_benchmark(
                project_dir=temp_project,
                path="src",
                queries=["login auth", "   ", "billing"],
                limit=2,
                repeats_per_query=2,
            )
            raise AssertionError("Expected ValueError")
        except ValueError as exc:
            assert "query cannot be empty or whitespace only" in str(exc)

    def test_run_multi_query_benchmark_with_warmup(self, temp_project):
        _seed_benchmark_project(temp_project)

        payload = run_multi_query_benchmark(
            project_dir=temp_project,
            path="src",
            queries=["login auth session"],
            limit=2,
            repeats_per_query=2,
            warmup_repeats=1,
        )

        assert payload["warmup_repeats"] == 1
        assert len(payload["per_query_results"]) == 1


class TestMemoryMetrics:
    def test_run_index_and_relevance_benchmark_reports_memory_delta(self, temp_project):
        _seed_benchmark_project(temp_project)

        payload = run_index_and_relevance_benchmark(
            project_dir=temp_project,
            path="src",
            query="login auth session",
            limit=2,
            repeats=2,
        )

        assert "index_memory_delta_mb" in payload
        assert "query_memory_delta_mb" in payload

    def test_run_index_and_relevance_benchmark_reports_stddev(self, temp_project):
        _seed_benchmark_project(temp_project)

        payload = run_index_and_relevance_benchmark(
            project_dir=temp_project,
            path="src",
            query="login auth session",
            limit=2,
            repeats=5,
        )

        assert "query_stddev_ms" in payload
        assert payload["query_stddev_ms"] >= 0

    def test_run_index_and_relevance_benchmark_with_warmup(self, temp_project):
        _seed_benchmark_project(temp_project)

        payload = run_index_and_relevance_benchmark(
            project_dir=temp_project,
            path="src",
            query="login auth session",
            limit=2,
            repeats=2,
            warmup_repeats=2,
        )

        assert payload["warmup_repeats"] == 2

    def test_run_index_and_relevance_benchmark_clear_cache(self, temp_project):
        _seed_benchmark_project(temp_project)

        payload = run_index_and_relevance_benchmark(
            project_dir=temp_project,
            path="src",
            query="login auth session",
            limit=2,
            repeats=1,
            clear_cache=True,
        )

        assert payload["clear_cache"] is True


class TestBaselineComparison:
    def test_compare_benchmark_to_baseline_checks_stddev_if_present(self, temp_project):
        _seed_benchmark_project(temp_project)
        baseline = _load_baseline()
        baseline["max_query_stddev_ms"] = 1000

        payload = run_index_and_relevance_benchmark(
            project_dir=temp_project,
            path="src",
            query="login auth session",
            limit=2,
            repeats=5,
        )

        comparison = compare_benchmark_to_baseline(payload, baseline)
        assert comparison["ok"] is True
