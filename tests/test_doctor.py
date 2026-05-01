"""Tests for doctor environment checks."""

from __future__ import annotations

from pathlib import Path

from claude_bridge.doctor import build_doctor_report


def test_build_doctor_report_marks_dev_and_optional_dependencies(tmp_path: Path) -> None:
    available_modules = {"claude_bridge", "pytest", "pytest_asyncio", "charset_normalizer"}
    available_commands = {"ruff", "black"}

    report = build_doctor_report(
        project_dir=tmp_path,
        config_snapshot={
            "approval_preset": "dev-safe",
            "auto_approve": False,
            "client_managed_approval": True,
            "onboarding_enabled": True,
        },
        desktop_config_path=tmp_path / "claude_desktop_config.json",
        python_executable="/missing/python",
        python_version=(3, 11, 5),
        module_checker=available_modules.__contains__,
        command_checker=available_commands.__contains__,
    )

    checks = {check.label: check for check in report.checks}

    assert report.project_dir == tmp_path.resolve()
    assert report.approval_preset == "dev-safe"
    assert report.client_managed_approval is True
    assert checks["Python version is supported"].ok is True
    assert checks["Python executable"].ok is False
    assert checks["pytest available"].ok is True
    assert checks["pytest-asyncio plugin available"].ok is True
    assert checks["ruff available"].ok is True
    assert checks["mypy available"].ok is False
    assert checks["tiktoken package available"].ok is False
    assert checks["charset-normalizer package available"].ok is True
    assert checks["Tree-sitter package available"].ok is False
