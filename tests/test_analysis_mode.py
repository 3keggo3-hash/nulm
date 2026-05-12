"""Tests for analysis_mode module."""

from __future__ import annotations

from pathlib import Path

from claude_bridge.analysis_mode import (
    AnalysisResult,
    OptionGenerator,
    ProjectScanner,
    analyze_project,
    format_analysis_report,
)


class TestProjectScanner:
    def test_detect_python_language(self, tmp_path: Path):
        (tmp_path / "main.py").touch()
        scanner = ProjectScanner(tmp_path)
        scanner._detect_language()
        assert scanner.language == "python"

    def test_detect_python_with_pyproject(self, tmp_path: Path):
        (tmp_path / "main.py").touch()
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        scanner = ProjectScanner(tmp_path)
        scanner.scan()
        assert scanner.language == "python"

    def test_detect_framework_fastapi(self, tmp_path: Path):
        (tmp_path / "main.py").touch()
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\ndependencies = ['fastapi']\n")
        scanner = ProjectScanner(tmp_path)
        scanner.scan()
        assert scanner.framework == "fastapi"

    def test_find_entry_points(self, tmp_path: Path):
        (tmp_path / "main.py").touch()
        (tmp_path / "app.py").touch()
        scanner = ProjectScanner(tmp_path)
        scanner._find_entry_points()
        assert len(scanner.entry_points) >= 1
        assert any("main.py" in ep for ep in scanner.entry_points)

    def test_scan_returns_dict(self, tmp_path: Path):
        (tmp_path / "main.py").touch()
        scanner = ProjectScanner(tmp_path)
        result = scanner.scan()
        assert isinstance(result, dict)
        assert "language" in result
        assert "framework" in result
        assert "entry_points" in result

    def test_find_performance_hotspots_nested_loop(self, tmp_path: Path):
        py_file = tmp_path / "slow.py"
        py_file.write_text(
            """
for i in range(10):
    for j in range(10):
        print(i, j)
"""
        )
        scanner = ProjectScanner(tmp_path)
        hotspots = scanner.find_performance_hotspots()
        nested_issues = [h for h in hotspots if h["issue"] == "nested_loop"]
        assert len(nested_issues) >= 1

    def test_find_security_issues_os_system(self, tmp_path: Path):
        py_file = tmp_path / "unsafe.py"
        py_file.write_text("import os\nos.system('ls')\n")
        scanner = ProjectScanner(tmp_path)
        issues = scanner.find_security_issues()
        shell_issues = [h for h in issues if h["issue"] == "shell_injection"]
        assert len(shell_issues) >= 1


class TestOptionGenerator:
    def test_generate_performance_options(self, tmp_path: Path):
        scanner = ProjectScanner(tmp_path)
        scanner.scan()
        gen = OptionGenerator(scanner.scan(), "sistem çok yavaş")
        options = gen.generate_options()
        assert len(options) >= 1
        assert any("performance" in str(opt).lower() or "optimiz" in str(opt).lower() for opt in options)

    def test_generate_security_options(self, tmp_path: Path):
        scanner = ProjectScanner(tmp_path)
        scanner.scan()
        gen = OptionGenerator(scanner.scan(), "bu güvenli mi?")
        options = gen.generate_options()
        assert len(options) >= 1

    def test_rank_options_sorted(self, tmp_path: Path):
        scanner = ProjectScanner(tmp_path)
        scanner.scan()
        gen = OptionGenerator(scanner.scan(), "karışık")
        options = gen.generate_options()
        if len(options) > 1:
            scores = [opt.get("score", 0) for opt in options]
            assert scores == sorted(scores, reverse=True)

    def test_options_have_required_fields(self, tmp_path: Path):
        scanner = ProjectScanner(tmp_path)
        scanner.scan()
        gen = OptionGenerator(scanner.scan(), "test")
        options = gen.generate_options()
        for opt in options:
            assert "id" in opt
            assert "title" in opt
            assert "impact" in opt
            assert "probability" in opt
            assert "effort_hours" in opt
            assert "score" in opt


class TestAnalysisResult:
    def test_analysis_result_dataclass(self):
        result = AnalysisResult(
            problem="test problem",
            root_causes=["cause 1", "cause 2"],
            options=[],
            recommended="A",
        )
        assert result.problem == "test problem"
        assert len(result.root_causes) == 2
        assert result.recommended == "A"


class TestAnalyzeProject:
    def test_analyze_project_returns_result(self, tmp_path: Path):
        (tmp_path / "main.py").touch()
        result = analyze_project(tmp_path, "test input")
        assert isinstance(result, AnalysisResult)
        assert result.problem == "test input"

    def test_analyze_project_fills_fields(self, tmp_path: Path):
        (tmp_path / "main.py").touch()
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        result = analyze_project(tmp_path, "performans sorunu")
        assert result.language == "python"
        assert result.options is not None
        assert len(result.options) >= 1


class TestFormatAnalysisReport:
    def test_format_report_basic(self):
        result = AnalysisResult(
            problem="test problem",
            root_causes=["cause 1", "cause 2"],
            options=[
                {
                    "id": "A",
                    "title": "Option A",
                    "probability": 60,
                    "estimated_improvement": "40%",
                    "risk": "low",
                    "effort_hours": 2,
                    "score": 50.0,
                    "rank": 1,
                }
            ],
            recommended="A",
        )
        report = format_analysis_report(result)
        assert "test problem" in report
        assert "cause 1" in report
        assert "Option A" in report
        assert "60%" in report

    def test_format_report_empty_options(self):
        result = AnalysisResult(
            problem="test",
            root_causes=[],
            options=[],
            recommended="",
        )
        report = format_analysis_report(result)
        assert "test" in report
