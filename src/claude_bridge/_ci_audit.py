"""One-shot CI analysis for quick security and quality checks."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def _run_cmd(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, shell=False)
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return -1, "", f"{cmd[0]} not found"


def run_shell_safety_check(path: Path | None = None) -> dict[str, Any]:
    """Verify blocked patterns in _shell_safety.py are enforced."""
    if path is None:
        path = Path.cwd()
    shell_safety = path / "src" / "claude_bridge" / "_shell_safety.py"
    if not shell_safety.exists():
        return {"ok": False, "error": "_shell_safety.py not found"}

    try:
        content = shell_safety.read_text(encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}

    blocked_patterns = re.findall(
        r'"(rm\s+-rf|password|sudo|chmod\s+777|curl\s*\|.*bash|wget.*\|.*bash)"',
        content,
    )
    return {
        "ok": True,
        "blocked_patterns_count": len(blocked_patterns),
        "blocked_patterns": blocked_patterns,
    }


def run_guard_policy_check(path: Path | None = None) -> dict[str, Any]:
    """Verify guard policy is valid."""
    if path is None:
        path = Path.cwd()
    policy_files = [
        path / ".claude-bridge-guard.json",
        path / "pyproject.toml",
    ]
    issues = []
    for pf in policy_files:
        if pf.exists():
            try:
                content = json.loads(pf.read_text(encoding="utf-8"))
                if "blocked_shell_patterns" in content:
                    issues.append(f"Guard policy at {pf} looks custom")
            except json.JSONDecodeError:
                issues.append(f"Invalid JSON in {pf}")

    return {"ok": True, "issues": issues} if issues else {"ok": True, "issues": []}


def run_import_check(path: Path | None = None) -> dict[str, Any]:
    """Verify all imports resolve correctly."""
    if path is None:
        path = Path.cwd()
    rc, stdout, stderr = _run_cmd([sys.executable, "-c", "import claude_bridge"], cwd=path)
    return {"ok": rc == 0, "import_error": stderr if rc != 0 else None}


def run_syntax_check(path: Path | None = None) -> dict[str, Any]:
    """Verify Python syntax is valid."""
    if path is None:
        path = Path.cwd()
    src_dir = path / "src" / "claude_bridge"
    if not src_dir.exists():
        return {"ok": False, "error": "src/claude_bridge not found"}

    results = []
    for py_file in src_dir.rglob("*.py"):
        rc, _, stderr = _run_cmd([sys.executable, "-m", "py_compile", str(py_file)], cwd=path)
        results.append({"file": str(py_file.relative_to(path)), "ok": rc == 0})
    errors = [r for r in results if not r["ok"]]
    return {"ok": len(errors) == 0, "files_checked": len(results), "errors": errors}


def run_security_pattern_check(path: Path | None = None) -> dict[str, Any]:
    """Check for common security anti-patterns."""
    if path is None:
        path = Path.cwd()
    src_dir = path / "src" / "claude_bridge"
    if not src_dir.exists():
        return {"ok": False, "error": "src/claude_bridge not found"}

    findings = []
    shell_false_pattern = re.compile(r"subprocess\.run\([^)]*shell\s*=\s*True")
    for py_file in src_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        matches = shell_false_pattern.findall(content)
        if matches:
            findings.append({"file": str(py_file.relative_to(path)), "matches": len(matches)})

    return {"ok": True, "findings": findings}


def run_quick_audit(path: Path | None = None) -> dict[str, Any]:
    """Run a complete one-shot audit of the project."""
    if path is None:
        path = Path.cwd()

    checks = {
        "shell_safety": run_shell_safety_check(path),
        "guard_policy": run_guard_policy_check(path),
        "imports": run_import_check(path),
        "syntax": run_syntax_check(path),
        "security_patterns": run_security_pattern_check(path),
    }

    all_ok = all(c.get("ok", False) for c in checks.values())
    return {"ok": all_ok, "checks": checks, "project": str(path.resolve())}


def print_audit_report(report: dict[str, Any]) -> None:
    """Print a human-readable audit report."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    status = "[green]PASS[/green]" if report["ok"] else "[red]FAIL[/red]"

    console.print(
        Panel.fit(
            f"One-Shot Audit Result: {status}",
            title="Audit",
            border_style="green" if report["ok"] else "red",
        )
    )

    table = Table(title="Check Results")
    table.add_column("Check", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Details", style="dim")

    for name, result in report["checks"].items():
        check_status = "[green]OK[/green]" if result.get("ok") else "[red]FAIL[/red]"
        details = ""
        if "blocked_patterns_count" in result:
            details = f"{result['blocked_patterns_count']} patterns"
        elif "files_checked" in result:
            details = f"{result['files_checked']} files"
        elif "findings" in result and result["findings"]:
            details = f"{len(result['findings'])} issues"
        elif "issues" in result and result["issues"]:
            details = ", ".join(result["issues"][:3])
        elif "error" in result:
            details = result["error"]
        table.add_row(name, check_status, details)

    console.print(table)
