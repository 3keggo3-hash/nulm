"""Environment checks for Nulm developer setup."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import importlib.util
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from claude_bridge.guard_policy import load_guard_policy
from claude_bridge.memory import MemoryStore, ProjectMemory


@dataclass(frozen=True)
class DoctorCheck:
    label: str
    ok: bool
    detail: str
    fix_suggestion: str | None = None


@dataclass(frozen=True)
class DoctorReport:
    project_dir: Path
    approval_preset: str | None
    auto_approve: bool
    client_managed_approval: bool
    onboarding_enabled: bool
    checks: list[DoctorCheck]
    quick_fixes: tuple[str, ...] = ()


ModuleChecker = Callable[[str], bool]
CommandChecker = Callable[[str], bool]


def module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def command_available(command_name: str) -> bool:
    return shutil.which(command_name) is not None


def _update_check(
    checks: list[DoctorCheck], label: str, ok: bool, detail: str, fix: str | None
) -> None:
    checks.append(
        DoctorCheck(label=label, ok=ok, detail=detail, fix_suggestion=fix if not ok else None)
    )


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
    checks: list[DoctorCheck] = []
    quick_fixes: list[str] = []

    _update_check(
        checks,
        "Project directory exists",
        resolved_project_dir.exists(),
        str(resolved_project_dir),
        None,
    )
    _update_check(
        checks,
        "Project directory is a folder",
        resolved_project_dir.is_dir(),
        str(resolved_project_dir),
        None,
    )
    _update_check(
        checks,
        "Python executable",
        Path(python_executable).exists(),
        python_executable,
        None,
    )
    _update_check(
        checks,
        "Python version is supported",
        tuple(python_version[:2]) >= (3, 10),
        version_text,
        None,
    )

    package_importable = module_checker("claude_bridge")
    _update_check(
        checks,
        "claude_bridge package importable",
        package_importable,
        "Install with: pip install -e .",
        None if package_importable else "pip install -e .",
    )

    pytest_ok = module_checker("pytest") or command_checker("pytest")
    _update_check(
        checks,
        "pytest available",
        pytest_ok,
        "Install dev dependencies with: pip install -e .[dev]",
        None if pytest_ok else "pip install -e .[dev]",
    )

    pytest_asyncio_ok = module_checker("pytest_asyncio")
    _update_check(
        checks,
        "pytest-asyncio plugin available",
        pytest_asyncio_ok,
        "Install dev dependencies with: pip install -e .[dev]",
        None if pytest_asyncio_ok else "pip install -e .[dev]",
    )

    ruff_ok = module_checker("ruff") or command_checker("ruff")
    _update_check(
        checks,
        "ruff available",
        ruff_ok,
        "Install dev dependencies with: pip install -e .[dev]",
        None if ruff_ok else "pip install -e .[dev]",
    )

    black_ok = module_checker("black") or command_checker("black")
    _update_check(
        checks,
        "black available",
        black_ok,
        "Install dev dependencies with: pip install -e .[dev]",
        None if black_ok else "pip install -e .[dev]",
    )

    mypy_ok = module_checker("mypy") or command_checker("mypy")
    _update_check(
        checks,
        "mypy available",
        mypy_ok,
        "Install dev dependencies with: pip install -e .[dev]",
        None if mypy_ok else "pip install -e .[dev]",
    )

    tiktoken_ok = module_checker("tiktoken")
    _update_check(
        checks,
        "tiktoken package available",
        tiktoken_ok,
        "Optional smart extra: pip install -e .[smart]",
        None if tiktoken_ok else "pip install -e .[smart]",
    )

    charset_ok = module_checker("charset_normalizer")
    _update_check(
        checks,
        "charset-normalizer package available",
        charset_ok,
        "Optional smart extra: pip install -e .[smart]",
        None if charset_ok else "pip install -e .[smart]",
    )

    treesitter_ok = module_checker("tree_sitter_language_pack")
    _update_check(
        checks,
        "Tree-sitter package available",
        treesitter_ok,
        "Optional indexing extra: pip install -e .[treesitter]",
        None if treesitter_ok else "pip install -e .[treesitter]",
    )

    desktop_config_ok = desktop_config_path.exists()
    _update_check(
        checks,
        "Claude Desktop config present",
        desktop_config_ok,
        str(desktop_config_path),
        None,
    )

    git_ok = (resolved_project_dir / ".git").exists()
    _update_check(
        checks,
        "Git repository detected",
        git_ok,
        "Useful for auto-commit and history-aware workflows",
        None,
    )

    _update_project_memory(resolved_project_dir)

    for check in checks:
        if not check.ok and check.fix_suggestion:
            quick_fixes.append(check.fix_suggestion)

    return DoctorReport(
        project_dir=resolved_project_dir,
        approval_preset=_optional_str(config_snapshot.get("approval_preset")),
        auto_approve=bool(config_snapshot.get("auto_approve", False)),
        client_managed_approval=bool(config_snapshot.get("client_managed_approval", False)),
        onboarding_enabled=bool(config_snapshot.get("onboarding_enabled", False)),
        checks=checks,
        quick_fixes=tuple(quick_fixes),
    )


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _resolve_audit_dir() -> Path:
    override = os.environ.get("CLAUDE_BRIDGE_AUDIT_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".claude-bridge" / "audit").resolve()


def _check_dir_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=str(path), delete=True):
            pass
        return True
    except (OSError, PermissionError):
        return False


def _update_project_memory(project_dir: Path) -> None:
    try:
        store = MemoryStore()
        existing = store.get_project_memory()
        if not existing.path or existing.path != str(project_dir.resolve()):
            proj_mem = ProjectMemory()
            proj_mem.populate_from_project(project_dir)
            store.update_project_memory(proj_mem)
    except Exception:
        pass


def build_security_doctor_report(
    *,
    project_dir: Path,
    config_snapshot: Mapping[str, object],
) -> DoctorReport:
    """Build a doctor report focused on security posture checks."""
    resolved_project_dir = project_dir.resolve()
    checks: list[DoctorCheck] = []
    quick_fixes: list[str] = []

    audit_dir = _resolve_audit_dir()
    writable = _check_dir_writable(audit_dir)
    _update_check(
        checks,
        "Audit directory writable",
        writable,
        str(audit_dir) if writable else f"{audit_dir} (not writable or missing)",
        None,
    )

    policy = load_guard_policy()
    policy_path = str(policy.get("path", "unknown"))
    if not policy.get("exists", False):
        _update_check(checks, "Guard policy valid", True, "No policy file configured", None)
    else:
        validation_errors: list[dict[str, str]] = list(policy.get("rules_validation", []))
        if not validation_errors:
            _update_check(checks, "Guard policy valid", True, policy_path, None)
        else:
            detail = f"{policy_path} ({len(validation_errors)} validation error(s))"
            _update_check(
                checks,
                "Guard policy valid",
                False,
                detail,
                f"Fix validation errors in {policy_path}",
            )

    auto_approve = bool(config_snapshot.get("auto_approve", False))
    client_managed = bool(config_snapshot.get("client_managed_approval", False))
    unsafe = auto_approve and not client_managed
    if unsafe:
        _update_check(
            checks,
            "Safe config flags",
            False,
            "auto_approve enabled without client_managed_approval",
            "Add client_managed_approval=true or set auto_approve=false",
        )
    else:
        _update_check(checks, "Safe config flags", True, "No unsafe flag combinations", None)

    if auto_approve:
        _update_check(
            checks,
            "Auto-approve warning",
            False,
            "Auto-approve is enabled — all operations approved automatically",
            "Disable with: nulm config set auto_approve false",
        )
    else:
        _update_check(
            checks,
            "Auto-approve warning",
            True,
            "Auto-approve is disabled",
            None,
        )

    for check in checks:
        if not check.ok and check.fix_suggestion:
            quick_fixes.append(check.fix_suggestion)

    return DoctorReport(
        project_dir=resolved_project_dir,
        approval_preset=_optional_str(config_snapshot.get("approval_preset")),
        auto_approve=auto_approve,
        client_managed_approval=client_managed,
        onboarding_enabled=bool(config_snapshot.get("onboarding_enabled", False)),
        checks=checks,
        quick_fixes=tuple(quick_fixes),
    )
