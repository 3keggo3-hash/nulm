"""Tests for doctor environment checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claude_bridge.doctor import build_doctor_report, build_security_doctor_report


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


def test_build_security_doctor_report_audit_dir_writable(tmp_path: Path) -> None:
    report = build_security_doctor_report(
        project_dir=tmp_path,
        config_snapshot={
            "auto_approve": False,
            "client_managed_approval": True,
            "approval_preset": None,
            "onboarding_enabled": True,
        },
    )
    checks = {check.label: check for check in report.checks}
    assert checks["Audit directory writable"].ok is True


def test_build_security_doctor_report_default_safe_flags(tmp_path: Path) -> None:
    report = build_security_doctor_report(
        project_dir=tmp_path,
        config_snapshot={
            "auto_approve": False,
            "client_managed_approval": True,
            "approval_preset": "dev-safe",
            "onboarding_enabled": True,
        },
    )
    checks = {check.label: check for check in report.checks}
    assert checks["Safe config flags"].ok is True
    assert checks["Auto-approve warning"].ok is True


def test_build_security_doctor_report_unsafe_flags(tmp_path: Path) -> None:
    report = build_security_doctor_report(
        project_dir=tmp_path,
        config_snapshot={
            "auto_approve": True,
            "client_managed_approval": False,
            "approval_preset": "power-user",
            "onboarding_enabled": False,
        },
    )
    checks = {check.label: check for check in report.checks}
    assert checks["Safe config flags"].ok is False
    assert checks["Auto-approve warning"].ok is False


def test_build_security_doctor_report_invalid_policy(tmp_path: Path, monkeypatch: Any) -> None:
    from claude_bridge.guard_policy import _invalidate_policy_cache

    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps({"rules": [{"name": "", "action": "deny", "conditions": []}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_BRIDGE_GUARD_POLICY", str(policy_path))
    _invalidate_policy_cache()

    report = build_security_doctor_report(
        project_dir=tmp_path,
        config_snapshot={
            "auto_approve": False,
            "client_managed_approval": True,
            "approval_preset": None,
            "onboarding_enabled": True,
        },
    )
    checks = {check.label: check for check in report.checks}
    assert checks["Guard policy valid"].ok is False


def test_build_security_doctor_report_reports_preset_and_mode(tmp_path: Path) -> None:
    report = build_security_doctor_report(
        project_dir=tmp_path,
        config_snapshot={
            "auto_approve": True,
            "client_managed_approval": False,
            "approval_preset": "power-user",
            "onboarding_enabled": True,
        },
    )
    assert report.project_dir == tmp_path.resolve()
    assert report.approval_preset == "power-user"
    assert report.auto_approve is True
    assert report.client_managed_approval is False
    assert report.onboarding_enabled is True
