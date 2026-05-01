"""Environment checks for Claude Bridge developer setup."""

from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence


@dataclass(frozen=True)
class DoctorCheck:
    label: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class DoctorReport:
    project_dir: Path
    approval_preset: str | None
    auto_approve: bool
    client_managed_approval: bool
    onboarding_enabled: bool
    checks: list[DoctorCheck]


ModuleChecker = Callable[[str], bool]
CommandChecker = Callable[[str], bool]


def module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def command_available(command_name: str) -> bool:
    return shutil.which(command_name) is not None


def build_doctor_report(
    *,
    project_dir: Path,
    config_snapshot: Mapping[str, object],
    desktop_config_path: Path,
    python_executable: str,
    python_version: Sequence[int],
    module_checker: ModuleChecker = module_available,
    command_checker: CommandChecker = command_available,
) -> DoctorReport:
    resolved_project_dir = project_dir.resolve()
    version_text = ".".join(str(part) for part in python_version[:3])
    checks = [
        DoctorCheck(
            "Project directory exists", resolved_project_dir.exists(), str(resolved_project_dir)
        ),
        DoctorCheck(
            "Project directory is a folder",
            resolved_project_dir.is_dir(),
            str(resolved_project_dir),
        ),
        DoctorCheck("Python executable", Path(python_executable).exists(), python_executable),
        DoctorCheck(
            "Python version is supported",
            tuple(python_version[:2]) >= (3, 8),
            version_text,
        ),
        DoctorCheck(
            "claude_bridge package importable",
            module_checker("claude_bridge"),
            "Install with: pip install -e .",
        ),
        DoctorCheck(
            "pytest available",
            module_checker("pytest") or command_checker("pytest"),
            "Install dev dependencies with: pip install -e .[dev]",
        ),
        DoctorCheck(
            "pytest-asyncio plugin available",
            module_checker("pytest_asyncio"),
            "Install dev dependencies with: pip install -e .[dev]",
        ),
        DoctorCheck(
            "ruff available",
            module_checker("ruff") or command_checker("ruff"),
            "Install dev dependencies with: pip install -e .[dev]",
        ),
        DoctorCheck(
            "black available",
            module_checker("black") or command_checker("black"),
            "Install dev dependencies with: pip install -e .[dev]",
        ),
        DoctorCheck(
            "mypy available",
            module_checker("mypy") or command_checker("mypy"),
            "Install dev dependencies with: pip install -e .[dev]",
        ),
        DoctorCheck(
            "tiktoken package available",
            module_checker("tiktoken"),
            "Optional smart extra: pip install -e .[smart]",
        ),
        DoctorCheck(
            "charset-normalizer package available",
            module_checker("charset_normalizer"),
            "Optional smart extra: pip install -e .[smart]",
        ),
        DoctorCheck(
            "Tree-sitter package available",
            module_checker("tree_sitter_language_pack"),
            "Optional indexing extra: pip install -e .[treesitter]",
        ),
        DoctorCheck(
            "Claude Desktop config present",
            desktop_config_path.exists(),
            str(desktop_config_path),
        ),
        DoctorCheck(
            "Git repository detected",
            (resolved_project_dir / ".git").exists(),
            "Useful for auto-commit and history-aware workflows",
        ),
    ]
    return DoctorReport(
        project_dir=resolved_project_dir,
        approval_preset=_optional_str(config_snapshot.get("approval_preset")),
        auto_approve=bool(config_snapshot.get("auto_approve", False)),
        client_managed_approval=bool(config_snapshot.get("client_managed_approval", False)),
        onboarding_enabled=bool(config_snapshot.get("onboarding_enabled", False)),
        checks=checks,
    )


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
