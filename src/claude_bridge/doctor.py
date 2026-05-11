"""Environment checks for Claude Bridge developer setup."""

from __future__ import annotations

import importlib.util
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from claude_bridge.guard_policy import load_guard_policy


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
            tuple(python_version[:2]) >= (3, 10),
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


def build_security_doctor_report(
    *,
    project_dir: Path,
    config_snapshot: Mapping[str, object],
) -> DoctorReport:
    """Build a doctor report focused on security posture checks."""
    resolved_project_dir = project_dir.resolve()
    checks: list[DoctorCheck] = []

    # 1. Audit directory writable
    audit_dir = _resolve_audit_dir()
    writable = _check_dir_writable(audit_dir)
    if writable:
        checks.append(DoctorCheck("Audit directory writable", True, str(audit_dir)))
    else:
        checks.append(
            DoctorCheck(
                "Audit directory writable",
                False,
                f"{audit_dir} (not writable or missing)",
            )
        )

    # 2. Guard policy valid
    policy = load_guard_policy()
    policy_path = str(policy.get("path", "unknown"))
    if not policy.get("exists", False):
        checks.append(DoctorCheck("Guard policy valid", True, "No policy file configured"))
    else:
        validation_errors: list[dict[str, str]] = list(policy.get("rules_validation", []))
        if not validation_errors:
            checks.append(DoctorCheck("Guard policy valid", True, policy_path))
        else:
            detail = f"{policy_path} ({len(validation_errors)} validation error(s))"
            checks.append(DoctorCheck("Guard policy valid", False, detail))

    # 3. Unsafe config flags
    auto_approve = bool(config_snapshot.get("auto_approve", False))
    client_managed = bool(config_snapshot.get("client_managed_approval", False))
    unsafe = auto_approve and not client_managed
    if unsafe:
        checks.append(
            DoctorCheck(
                "Safe config flags",
                False,
                "auto_approve enabled without client_managed_approval",
            )
        )
    else:
        checks.append(DoctorCheck("Safe config flags", True, "No unsafe flag combinations"))

    # 4. Auto-approve warning
    if auto_approve:
        checks.append(
            DoctorCheck(
                "Auto-approve warning",
                False,
                "Auto-approve is enabled — all operations approved automatically",
            )
        )
    else:
        checks.append(
            DoctorCheck(
                "Auto-approve warning",
                True,
                "Auto-approve is disabled",
            )
        )

    return DoctorReport(
        project_dir=resolved_project_dir,
        approval_preset=_optional_str(config_snapshot.get("approval_preset")),
        auto_approve=auto_approve,
        client_managed_approval=client_managed,
        onboarding_enabled=bool(config_snapshot.get("onboarding_enabled", False)),
        checks=checks,
    )
