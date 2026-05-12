"""Auto-generated project understanding stored at .claude-bridge/project-map.md.

Generated on:
- First `bridge doctor` run
- `bridge init` completion
- Manual trigger: `bridge map --refresh`
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_bridge.guard_policy import load_guard_policy
from claude_bridge.skill_registry import get_registry

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ProjectInfo:
    """Structured project information for the project map."""

    name: str = ""
    language: str = ""
    framework: str = ""
    test_framework: str = ""
    entry_points: list[str] = field(default_factory=list)
    risk_areas: list[str] = field(default_factory=list)
    custom_guards: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    last_updated: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "language": self.language,
            "framework": self.framework,
            "test_framework": self.test_framework,
            "entry_points": list(self.entry_points),
            "risk_areas": list(self.risk_areas),
            "custom_guards": list(self.custom_guards),
            "skills": list(self.skills),
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectInfo:
        return cls(
            name=str(data.get("name", "")),
            language=str(data.get("language", "")),
            framework=str(data.get("framework", "")),
            test_framework=str(data.get("test_framework", "")),
            entry_points=list(data.get("entry_points", [])),
            risk_areas=list(data.get("risk_areas", [])),
            custom_guards=list(data.get("custom_guards", [])),
            skills=list(data.get("skills", [])),
            last_updated=str(data.get("last_updated", "")),
        )


# ---------------------------------------------------------------------------
# Language and framework detection
# ---------------------------------------------------------------------------

_LANGUAGE_SIGNALS: dict[str, list[tuple[Path, str]]] = {
    "Python": [
        (Path("requirements.txt"), ""),
        (Path("pyproject.toml"), ""),
        (Path("setup.py"), ""),
        (Path("setup.cfg"), ""),
        (Path("Pipfile"), ""),
        (Path("poetry.lock"), ""),
    ],
    "JavaScript": [
        (Path("package.json"), ""),
        (Path("yarn.lock"), ""),
        (Path("pnpm-lock.yaml"), ""),
    ],
    "TypeScript": [
        (Path("tsconfig.json"), ""),
        (Path("package.json"), ""),
    ],
    "Go": [
        (Path("go.mod"), ""),
    ],
    "Rust": [
        (Path("Cargo.toml"), ""),
        (Path("Cargo.lock"), ""),
    ],
    "Ruby": [
        (Path("Gemfile"), ""),
        (Path("Gemfile.lock"), ""),
    ],
    "Java": [
        (Path("pom.xml"), ""),
        (Path("build.gradle"), ""),
    ],
    "C#": [
        (Path("*.csproj"), ""),
    ],
}

_FRAMEWORK_SIGNALS: dict[str, list[str]] = {
    "FastAPI": ["fastapi", "uvicorn"],
    "Django": ["django"],
    "Flask": ["flask"],
    "Streamlit": ["streamlit"],
    "React": ["react", "react-dom"],
    "Vue": ["vue"],
    "Next.js": ["next"],
    "Express": ["express"],
    "NestJS": ["@nestjs"],
    "Spring": ["spring"],
    "Axum": ["axum"],
    "Actix": ["actix"],
}

_TEST_FRAMEWORK_SIGNALS: dict[str, list[str]] = {
    "pytest": ["pytest", "pytest-asyncio"],
    "unittest": ["unittest", "unittest.mock"],
    "Jest": ["jest"],
    "Mocha": ["mocha"],
    "Playwright": ["playwright"],
    "Cypress": ["cypress"],
}


def _detect_language(project_dir: Path) -> str:
    """Detect primary language from project files."""
    py_indicator = project_dir / "requirements.txt"
    if py_indicator.exists():
        try:
            content = py_indicator.read_text(encoding="utf-8").lower()
            if "fastapi" in content:
                return "Python"
            if "django" in content:
                return "Python"
            if "flask" in content:
                return "Python"
        except OSError:
            pass

    pyproject = project_dir / "pyproject.toml"
    if pyproject.exists():
        return "Python"

    pkg_json = project_dir / "package.json"
    if pkg_json.exists():
        try:
            content = pkg_json.read_text(encoding="utf-8").lower()
            if "typescript" in content or '"ts' in content:
                return "TypeScript"
            return "JavaScript"
        except OSError:
            pass

    for lang, signals in _LANGUAGE_SIGNALS.items():
        for file_path, _ in signals:
            if (project_dir / file_path.name).exists():
                return lang

    return "Unknown"


def _detect_framework(project_dir: Path, language: str) -> str:
    """Detect framework from dependencies or project structure."""
    if language == "Python":
        req_file = project_dir / "requirements.txt"
        if req_file.exists():
            try:
                content = req_file.read_text(encoding="utf-8").lower()
                for fw, signals in _FRAMEWORK_SIGNALS.items():
                    if any(s in content for s in signals):
                        return fw
            except OSError:
                pass

        pyproject = project_dir / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8").lower()
                for fw, signals in _FRAMEWORK_SIGNALS.items():
                    if any(s in content for s in signals):
                        return fw
            except OSError:
                pass

    elif language in ("JavaScript", "TypeScript"):
        pkg_json = project_dir / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                deps = {}
                deps.update(data.get("dependencies", {}))
                deps.update(data.get("devDependencies", {}))
                deps_str = " ".join(deps.keys()).lower()
                for fw, signals in _FRAMEWORK_SIGNALS.items():
                    if any(s in deps_str for s in signals):
                        return fw
            except (OSError, json.JSONDecodeError):
                pass

    return "Unknown"


def _detect_test_framework(project_dir: Path, language: str) -> str:
    """Detect test framework from project files."""
    if language == "Python":
        req_file = project_dir / "requirements.txt"
        if req_file.exists():
            try:
                content = req_file.read_text(encoding="utf-8").lower()
                for fw, signals in _TEST_FRAMEWORK_SIGNALS.items():
                    if any(s in content for s in signals):
                        return fw
            except OSError:
                pass

        pyproject = project_dir / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8").lower()
                for fw, signals in _TEST_FRAMEWORK_SIGNALS.items():
                    if any(s in content for s in signals):
                        return fw
            except OSError:
                pass

    elif language in ("JavaScript", "TypeScript"):
        pkg_json = project_dir / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                deps = {}
                deps.update(data.get("dependencies", {}))
                deps.update(data.get("devDependencies", {}))
                deps_str = " ".join(deps.keys()).lower()
                for fw, signals in _TEST_FRAMEWORK_SIGNALS.items():
                    if any(s in deps_str for s in signals):
                        return fw
            except (OSError, json.JSONDecodeError):
                pass

    return "Unknown"


# ---------------------------------------------------------------------------
# Entry points detection
# ---------------------------------------------------------------------------


def _find_entry_points(project_dir: Path, language: str) -> list[str]:
    """Find likely entry points for the project."""
    candidates: list[tuple[Path, str]] = []

    if language == "Python":
        for pattern in [
            "src/main.py",
            "src/app.py",
            "src/__main__.py",
            "main.py",
            "app.py",
            "cli.py",
            "__main__.py",
            "run.py",
            "serve.py",
        ]:
            path = project_dir / pattern
            if path.exists() and path.is_file():
                candidates.append((path, pattern))
    else:
        for pattern in [
            "src/index.js",
            "src/index.ts",
            "index.js",
            "index.ts",
            "src/main.js",
            "src/main.ts",
            "main.js",
            "main.ts",
        ]:
            path = project_dir / pattern
            if path.exists() and path.is_file():
                candidates.append((path, pattern))

    # Sort by priority (earlier in list = higher priority)
    result: list[str] = []
    for _, label in candidates:
        if label not in result:
            result.append(label)
    return result


# ---------------------------------------------------------------------------
# Risk areas detection
# ---------------------------------------------------------------------------


def _find_risk_areas(project_dir: Path) -> list[str]:
    """Find directories or files that represent risk areas."""
    risk_patterns = [
        ".env",
        ".env.local",
        ".env.production",
        ".env*",
        "*.key",
        "*.pem",
        "*.p12",
        "*.pfx",
        "credentials.json",
        "secrets.json",
        "service-account.json",
    ]

    risk_dirs = [
        "src/security",
        "security",
        "secrets",
        ".secrets",
    ]

    found: list[str] = []

    # Exclude common dependency directories
    exclude_dirs = {"venv", ".venv", "node_modules", ".git", "__pycache__", ".pytest_cache"}

    def _is_excluded(path: Path) -> bool:
        """Check if path is inside an excluded directory."""
        parts = path.parts
        return any(excluded in parts for excluded in exclude_dirs)

    # Check for sensitive files
    for pattern in risk_patterns:
        if "*" in pattern:
            for item in project_dir.rglob(pattern):
                if item.is_file() and not _is_excluded(item):
                    rel = item.relative_to(project_dir).as_posix()
                    if rel not in found:
                        found.append(rel)
        else:
            path = project_dir / pattern
            if path.exists() and not _is_excluded(path):
                rel = path.relative_to(project_dir).as_posix()
                if rel not in found:
                    found.append(rel)

    # Check for sensitive directories
    for d in risk_dirs:
        path = project_dir / d
        if path.exists() and path.is_dir():
            rel = path.relative_to(project_dir).as_posix()
            if rel not in found:
                found.append(rel)

    return found


# ---------------------------------------------------------------------------
# Custom guards loading
# ---------------------------------------------------------------------------


def _load_custom_guards() -> list[str]:
    """Load custom guard rule names from the guard policy."""
    guards: list[str] = []
    try:
        policy = load_guard_policy()
        rules = policy.get("rules", [])
        for rule in rules:
            if isinstance(rule, dict) and rule.get("name"):
                guards.append(str(rule["name"]))
    except Exception:
        pass
    return guards


# ---------------------------------------------------------------------------
# Skills loading
# ---------------------------------------------------------------------------


def _load_skills() -> list[str]:
    """Load skill names from the skill registry."""
    registry = get_registry()
    loaded = registry.get_loaded()
    return sorted(loaded.keys())


# ---------------------------------------------------------------------------
# Project Mapper
# ---------------------------------------------------------------------------


class ProjectMapper:
    """Generates and manages the project map markdown file."""

    PROJECT_MAP_FILE = Path(".claude-bridge/project-map.md")

    def generate(self, project_dir: Path) -> ProjectInfo:
        """Scan the project directory and build a ProjectInfo."""
        resolved = project_dir.resolve()

        language = _detect_language(resolved)
        framework = _detect_framework(resolved, language)
        test_framework = _detect_test_framework(resolved, language)
        entry_points = _find_entry_points(resolved, language)
        risk_areas = _find_risk_areas(resolved)
        custom_guards = _load_custom_guards()
        skills = _load_skills()

        # Project name from directory
        name = resolved.name

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        return ProjectInfo(
            name=name,
            language=language,
            framework=framework,
            test_framework=test_framework,
            entry_points=entry_points,
            risk_areas=risk_areas,
            custom_guards=custom_guards,
            skills=skills,
            last_updated=timestamp,
        )

    def save_map(self, info: ProjectInfo) -> None:
        """Save the project map as a markdown file."""
        markdown = self.format_markdown(info)
        self.PROJECT_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.PROJECT_MAP_FILE.write_text(markdown, encoding="utf-8")

    def load_map(self) -> ProjectInfo | None:
        """Load an existing project map from disk.

        Returns None if the file does not exist or cannot be parsed.
        """
        if not self.PROJECT_MAP_FILE.exists():
            return None

        try:
            # Simple parsing: extract last_updated from the file
            # For full round-trip, we use a sidecar JSON
            json_path = self.PROJECT_MAP_FILE.with_suffix(".json")
            if json_path.exists():
                data = json.loads(json_path.read_text(encoding="utf-8"))
                return ProjectInfo.from_dict(data)
        except (OSError, json.JSONDecodeError):
            pass

        return None

    def format_markdown(self, info: ProjectInfo) -> str:
        """Format a ProjectInfo as a markdown document."""
        lines = [
            f"# Project Map: {info.name}",
            "",
            "## Overview",
            f"- Language: {info.language}",
            f"- Framework: {info.framework}",
            f"- Test Framework: {info.test_framework}",
            "",
            "## Entry Points",
        ]

        if info.entry_points:
            for ep in info.entry_points:
                lines.append(f"- `{ep}`")
        else:
            lines.append("- _None detected_")

        lines.extend(["", "## Risk Areas"])

        if info.risk_areas:
            for area in info.risk_areas:
                lines.append(f"- `{area}`")
        else:
            lines.append("- _None detected_")

        lines.extend(["", "## Custom Guards"])

        if info.custom_guards:
            for guard in info.custom_guards:
                lines.append(f"- {guard}")
        else:
            lines.append("- _No custom guard rules configured_")

        lines.extend(["", "## Skills"])

        if info.skills:
            for skill in info.skills:
                lines.append(f"- `{skill}` (loaded)")
        else:
            lines.append("- _No skills loaded_")

        lines.extend(["", "## Last Updated", info.last_updated])

        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Convenience API
# ---------------------------------------------------------------------------

_mapper: ProjectMapper | None = None


def get_mapper() -> ProjectMapper:
    """Return the shared ProjectMapper instance."""
    global _mapper
    if _mapper is None:
        _mapper = ProjectMapper()
    return _mapper
