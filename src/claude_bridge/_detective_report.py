"""Report formatting for Bridge Detective."""

from __future__ import annotations

from typing import Any


def format_detective_report(report: dict[str, Any]) -> str:
    """Format a DetectiveReport into the human-readable report string."""
    error_msg = report.get("error_message", "Unknown error")
    file_path = report.get("file_path", "")
    line_num = report.get("line_number", "")
    _error_type = report.get("error_type", "UNKNOWN")
    likelihood = report.get("likelihood", "unknown")
    related = report.get("related_files", [])
    recent = report.get("recent_changes", [])
    diagnostics = report.get("diagnostics", [])
    similar = report.get("similar_lesson", None)
    suggested_fix = report.get("suggested_fix", "")

    lines: list[str] = [
        "\u2315 Bridge Detective Report",
        "\u2550" * 24,
        f"Error: {error_msg}",
    ]

    if file_path:
        location = f"{file_path}:{line_num}" if line_num else file_path
        lines.append(f"File: {location}")

    lines.append(f" likelihood: {likelihood}")
    lines.append("")

    if recent:
        lines.append("Recent changes:")
        for change in recent[:5]:
            msg = change.get("message", "")
            lines.append(f"  {msg}")
        lines.append("")

    if related:
        lines.append("Related files:")
        for fobj in related[:5]:
            lines.append(f"  - {fobj}")
        lines.append("")

    if diagnostics:
        lines.append("Diagnostics:")
        for diag in diagnostics:
            cmd = diag.get("command", "")
            rc = diag.get("returncode", -1)
            lines.append(f"  $ {cmd} -> {rc}")
        lines.append("")

    if similar:
        lines.append("Similar error found in lessons:")
        lines.append(f"  Pattern: {similar.get('pattern', '')}")
        fix = similar.get("solution", "")
        if fix:
            lines.append(f"  Previous fix: {fix}")
        lines.append("")

    if suggested_fix:
        lines.append("Suggested fix:")
        lines.append(f"  {suggested_fix}")

    return "\n".join(lines)
