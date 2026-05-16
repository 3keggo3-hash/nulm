"""Parallel environment health checks for .opencode/ and .claude-bridge/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def check_opencode_dir(path: Path | None = None) -> dict[str, Any]:
    """Check .opencode/ directory health."""
    if path is None:
        path = Path.cwd()
    opencode_dir = path / ".opencode"

    issues = []
    if not opencode_dir.exists():
        return {"ok": False, "error": ".opencode/ not found", "exists": False}

    config_file = opencode_dir / "opencode.json"
    dcp_file = opencode_dir / "dcp.jsonc"
    rules_dir = opencode_dir / "rules"

    if config_file.exists():
        try:
            json.loads(config_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            issues.append(f"Invalid JSON in opencode.json: {e}")

    if dcp_file.exists():
        try:
            content = dcp_file.read_text(encoding="utf-8")
            if "//" in content:
                pass
            else:
                json.loads(content)
        except json.JSONDecodeError as e:
            issues.append(f"Invalid JSON in dcp.jsonc: {e}")

    if rules_dir.exists() and rules_dir.is_dir():
        rule_files = list(rules_dir.glob("*.md"))
        if not rule_files:
            issues.append("No rule files found in .opencode/rules/")
    else:
        issues.append(".opencode/rules/ directory not found")

    return {
        "ok": len(issues) == 0,
        "exists": True,
        "issues": issues,
        "files": {
            "config": str(config_file) if config_file.exists() else None,
            "dcp": str(dcp_file) if dcp_file.exists() else None,
            "rules_dir": str(rules_dir) if rules_dir.exists() else None,
        },
    }


def check_claude_bridge_dir(path: Path | None = None) -> dict[str, Any]:
    """Check .claude-bridge/ directory health."""
    if path is None:
        path = Path.cwd()
    cb_dir = path / ".claude-bridge"

    issues = []
    if not cb_dir.exists():
        return {"ok": False, "error": ".claude-bridge/ not found", "exists": False}

    audit_dir = cb_dir / "audit"
    snapshots_dir = cb_dir / "snapshots"
    skills_dir = cb_dir / "skills"

    if not audit_dir.exists():
        issues.append("audit/ directory not found (may be created on first use)")
    if skills_dir.exists():
        skill_index = skills_dir / "index.json"
        if skill_index.exists():
            try:
                json.loads(skill_index.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                issues.append("Invalid skill index.json")

    guard_file = path / ".claude-bridge-guard.json"
    if guard_file.exists():
        try:
            content = json.loads(guard_file.read_text(encoding="utf-8"))
            if "blocked_shell_patterns" not in content and "default_deny" not in content:
                issues.append("Guard policy missing expected fields")
        except json.JSONDecodeError:
            issues.append("Invalid .claude-bridge-guard.json")

    return {
        "ok": len(issues) == 0,
        "exists": True,
        "issues": issues,
        "dirs": {
            "audit": str(audit_dir),
            "snapshots": str(snapshots_dir),
            "skills": str(skills_dir),
        },
    }


def check_environment_consistency(path: Path | None = None) -> dict[str, Any]:
    """Check for inconsistencies between .opencode/ and .claude-bridge/."""
    if path is None:
        path = Path.cwd()

    opencode = check_opencode_dir(path)
    claude_bridge = check_claude_bridge_dir(path)

    cross_issues = []

    cb_dir = path / ".claude-bridge"
    opencode_dir = path / ".opencode"

    if cb_dir.exists() and opencode_dir.exists():
        cb_files = set(f.name for f in cb_dir.iterdir() if f.is_file())
        opencode_files = set(f.name for f in opencode_dir.iterdir() if f.is_file())

        overlap = cb_files & opencode_files
        if overlap:
            cross_issues.append(f"Conflicting files: {overlap}")

    return {
        "opencode": opencode,
        "claude_bridge": claude_bridge,
        "cross_issues": cross_issues,
        "overall_ok": opencode.get("ok", False)
        and claude_bridge.get("ok", False)
        and len(cross_issues) == 0,
    }


def print_parallel_doctor_report(report: dict[str, Any]) -> None:
    """Print a human-readable parallel doctor report."""
    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    status = "[green]OK[/green]" if report["overall_ok"] else "[yellow]ISSUES[/yellow]"

    style = "green" if report["overall_ok"] else "yellow"
    console.print(
        Panel.fit(f"Environment Health: {status}", title="Doctor", border_style=style)
    )

    for label, section in [
        (".opencode/", report["opencode"]),
        (".claude-bridge/", report["claude_bridge"]),
    ]:
        section_status = "[green]OK[/green]" if section.get("ok") else "[red]FAIL[/red]"
        console.print(f"\n[bold]{label}[/bold] {section_status}")

        if "error" in section:
            console.print(f"  [red]Error:[/red] {section['error']}")
        elif "issues" in section and section["issues"]:
            for issue in section["issues"]:
                console.print(f"  [yellow]-[/yellow] {issue}")

    if report["cross_issues"]:
        console.print("\n[bold yellow]Cross-directory issues:[/bold yellow]")
        for issue in report["cross_issues"]:
            console.print(f"  [yellow]-[/yellow] {issue}")
