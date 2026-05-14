"""Analysis Mode - Architectural analysis for vague user inputs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AnalysisResult:
    problem: str
    root_causes: list[str]
    options: list[dict[str, Any]]
    recommended: str
    language: str = ""
    framework: str = ""
    entry_points: list[str] = field(default_factory=list)
    hotspots: list[dict[str, Any]] = field(default_factory=list)


class ProjectScanner:
    def __init__(self, project_path: str | Path) -> None:
        self.project_path = Path(project_path)
        self.language = ""
        self.framework = ""
        self.entry_points: list[str] = []
        self.hotspots: list[dict[str, Any]] = []

    def scan(self) -> dict[str, Any]:
        self._detect_language()
        self._detect_framework()
        self._find_entry_points()
        self.find_performance_hotspots()
        self.find_security_issues()

        return {
            "language": self.language,
            "framework": self.framework,
            "entry_points": self.entry_points,
            "hotspots": self.hotspots,
        }

    def _detect_language(self) -> None:
        py_files = list(self.project_path.rglob("*.py"))
        js_files = list(self.project_path.rglob("*.js")) + list(self.project_path.rglob("*.ts"))
        go_files = list(self.project_path.rglob("*.go"))
        rust_files = list(self.project_path.rglob("*.rs"))

        if py_files:
            self.language = "python"
            if (self.project_path / "pyproject.toml").exists():
                self.framework = "python"
            elif (self.project_path / "requirements.txt").exists():
                self.framework = "python"
        elif js_files:
            self.language = "javascript"
            if (self.project_path / "package.json").exists():
                self.framework = "node"
        elif go_files:
            self.language = "go"
            self.framework = "go"
        elif rust_files:
            self.language = "rust"
            self.framework = "rust"

    def _detect_framework(self) -> None:
        pyproject = self.project_path / "pyproject.toml"
        if pyproject.exists():
            content = pyproject.read_text().lower()
            if "fastapi" in content:
                self.framework = "fastapi"
            elif "django" in content:
                self.framework = "django"
            elif "flask" in content:
                self.framework = "flask"

        package_json = self.project_path / "package.json"
        if package_json.exists():
            content = package_json.read_text().lower()
            if "next" in content:
                self.framework = "nextjs"
            elif "express" in content:
                self.framework = "express"

    def _find_entry_points(self) -> None:
        candidates = [
            "main.py",
            "app.py",
            "index.py",
            "src/main.py",
            "src/app.py",
            "cli.py",
            "run.py",
            "server.py",
            "main.js",
            "index.js",
            "app.js",
            "server.js",
        ]
        for candidate in candidates:
            path = self.project_path / candidate
            if path.exists() and path.is_file():
                self.entry_points.append(str(path))

        if not self.entry_points:
            py_files = list(self.project_path.rglob("*.py"))
            for f in py_files[:5]:
                if "test" not in f.name and "__pycache__" not in str(f):
                    self.entry_points.append(str(f))

    def find_performance_hotspots(self) -> list[dict[str, Any]]:
        hotspots: list[dict[str, Any]] = []
        py_files = list(self.project_path.rglob("*.py"))

        for f in py_files:
            if "test" in f.name or "__pycache__" in str(f):
                continue
            try:
                content = f.read_text(errors="ignore")
                if len(content) > 100_000:
                    hotspots.append(
                        {
                            "file": str(f),
                            "issue": "large_file",
                            "severity": "medium",
                            "description": f"File size: {len(content)} bytes",
                        }
                    )
                if re.search(r"for\s+.*\s+in\s+.*\s+for\s+", content):
                    hotspots.append(
                        {
                            "file": str(f),
                            "issue": "nested_loop",
                            "severity": "high",
                            "description": "Nested loop detected - potential O(n²) complexity",
                        }
                    )
                if re.search(r"\.join\(", content) and content.count(".") > 50:
                    hotspots.append(
                        {
                            "file": str(f),
                            "issue": "string_concatenation",
                            "severity": "low",
                            "description": "Many string operations - consider list join",
                        }
                    )
            except OSError:
                continue

        self.hotspots.extend(hotspots)
        return hotspots

    def find_security_issues(self) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        py_files = list(self.project_path.rglob("*.py"))

        for f in py_files:
            if "test" in f.name or "__pycache__" in str(f):
                continue
            try:
                content = f.read_text(errors="ignore")
                if re.search(r"os\.system\(", content):
                    issues.append(
                        {
                            "file": str(f),
                            "issue": "shell_injection",
                            "severity": "high",
                            "description": "os.system() usage - potential shell injection",
                        }
                    )
                if re.search(r"eval\s*\(", content):
                    issues.append(
                        {
                            "file": str(f),
                            "issue": "code_injection",
                            "severity": "critical",
                            "description": "eval() usage - potential code injection",
                        }
                    )
                if re.search(r"password\s*=\s*['\"][^'\"]+['\"]", content, re.IGNORECASE):
                    issues.append(
                        {
                            "file": str(f),
                            "issue": "hardcoded_password",
                            "severity": "high",
                            "description": "Hardcoded password detected",
                        }
                    )
                if re.search(r"cursor\.execute\([^,]+%", content):
                    issues.append(
                        {
                            "file": str(f),
                            "issue": "sql_injection",
                            "severity": "critical",
                            "description": "SQL query with string formatting - potential SQL injection",
                        }
                    )
            except OSError:
                continue

        self.hotspots.extend(issues)
        return issues


class OptionGenerator:
    def __init__(self, scan_result: dict[str, Any], user_input: str) -> None:
        self.scan_result = scan_result
        self.user_input = user_input
        self.language = scan_result.get("language", "")
        self.framework = scan_result.get("framework", "")
        self.hotspots = scan_result.get("hotspots", [])

    def generate_options(self) -> list[dict[str, Any]]:
        options: list[dict[str, Any]] = []
        user_lower = self.user_input.lower()

        if any(word in user_lower for word in ["yavaş", "performance", "hız", "slow", "optimiz"]):
            options.extend(self._performance_options())
        elif any(word in user_lower for word in ["güvenli", "security", "hack", "risk"]):
            options.extend(self._security_options())
        elif any(word in user_lower for word in ["eksik", "missing", "yok", "çalışmıyor"]):
            options.extend(self._feature_options())
        else:
            options.extend(self._general_options())

        return self.rank_options(options)

    def _performance_options(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "A",
                "title": "Code optimization",
                "description": "Optimize inefficient code patterns",
                "impact": 40,
                "probability": 60,
                "effort_hours": 2,
                "risk": "low",
            },
            {
                "id": "B",
                "title": "Caching layer",
                "description": "Add caching to reduce repeated computations",
                "impact": 35,
                "probability": 50,
                "effort_hours": 3,
                "risk": "low",
            },
            {
                "id": "C",
                "title": "Database query optimization",
                "description": "Optimize slow queries and add indexes",
                "impact": 45,
                "probability": 40,
                "effort_hours": 4,
                "risk": "medium",
            },
        ]

    def _security_options(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "A",
                "title": "Dependency audit",
                "description": "Check for vulnerable dependencies",
                "impact": 50,
                "probability": 70,
                "effort_hours": 1,
                "risk": "very_low",
            },
            {
                "id": "B",
                "title": "Input validation",
                "description": "Add comprehensive input validation",
                "impact": 40,
                "probability": 55,
                "effort_hours": 3,
                "risk": "low",
            },
            {
                "id": "C",
                "title": "Authentication review",
                "description": "Audit authentication and authorization",
                "impact": 45,
                "probability": 45,
                "effort_hours": 4,
                "risk": "medium",
            },
        ]

    def _feature_options(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "A",
                "title": "Dependency check",
                "description": "Verify all dependencies are installed",
                "impact": 30,
                "probability": 70,
                "effort_hours": 0.5,
                "risk": "very_low",
            },
            {
                "id": "B",
                "title": "Configuration review",
                "description": "Check configuration files for issues",
                "impact": 35,
                "probability": 50,
                "effort_hours": 1,
                "risk": "low",
            },
            {
                "id": "C",
                "title": "Module verification",
                "description": "Verify module imports and paths",
                "impact": 40,
                "probability": 60,
                "effort_hours": 1.5,
                "risk": "low",
            },
        ]

    def _general_options(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "A",
                "title": "Project analysis",
                "description": "Perform full project structure analysis",
                "impact": 40,
                "probability": 80,
                "effort_hours": 1,
                "risk": "very_low",
            },
            {
                "id": "B",
                "title": "Best practices review",
                "description": "Review code against best practices",
                "impact": 35,
                "probability": 65,
                "effort_hours": 2,
                "risk": "very_low",
            },
            {
                "id": "C",
                "title": "Incremental approach",
                "description": "Start with smallest change and iterate",
                "impact": 30,
                "probability": 75,
                "effort_hours": 1,
                "risk": "low",
            },
        ]

    def rank_options(self, options: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for opt in options:
            impact = opt.get("impact", 0)
            probability = opt.get("probability", 0)
            effort = opt.get("effort_hours", 1)
            effort_score = max(0, 30 - (effort * 10))
            score = impact * 0.4 + probability * 0.3 + effort_score * 0.3
            opt["score"] = round(score, 1)
            opt["estimated_improvement"] = f"{impact}%"

        options.sort(key=lambda x: x.get("score", 0), reverse=True)

        for i, opt in enumerate(options):
            opt["rank"] = i + 1

        return options


def format_analysis_report(result: AnalysisResult) -> str:
    lines = [
        "🎯 Architectural Analysis Complete",
        "═" * 40,
        f"Problem: {result.problem}",
        f"Root causes found: {len(result.root_causes)}",
    ]

    for i, cause in enumerate(result.root_causes, 1):
        lines.append(f"  {i}. {cause}")

    if result.options:
        lines.append("")
        lines.append("Possible approaches (ranked by impact):")
        for opt in result.options:
            prob = opt.get("probability", 0)
            lines.append("")
            lines.append(f"{opt.get('id', '?')}. [{prob}%] {opt.get('title', 'Unknown')}")
            lines.append(f"   • Est. improvement: {opt.get('estimated_improvement', 'N/A')}")
            lines.append(f"   • Risk: {opt.get('risk', 'unknown')}")
            lines.append(f"   • Effort: {opt.get('effort_hours', '?')} hours")

    if result.recommended:
        lines.append("")
        lines.append(f"Recommended approach: {result.recommended}")

    return "\n".join(lines)


def analyze_project(project_path: str | Path, user_input: str) -> AnalysisResult:
    scanner = ProjectScanner(project_path)
    scan_data = scanner.scan()

    generator = OptionGenerator(scan_data, user_input)
    options = generator.generate_options()

    root_causes: list[str] = []
    for hotspot in scanner.hotspots[:3]:
        root_causes.append(
            f"{hotspot.get('issue', 'unknown')}: {hotspot.get('description', 'No description')}"
        )

    recommended = ""
    if options:
        recommended = f"{options[0].get('id', '?')} ({options[0].get('title', 'Unknown')})"

    return AnalysisResult(
        problem=user_input,
        root_causes=root_causes,
        options=options,
        recommended=recommended,
        language=scanner.language,
        framework=scanner.framework,
        entry_points=scanner.entry_points,
        hotspots=scanner.hotspots,
    )
