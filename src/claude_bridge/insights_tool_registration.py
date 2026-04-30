"""Registration helpers for project insight and fun MCP tools."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable


def register_insights_tools(
    *,
    mcp: Any,
    tool_options: Callable[..., dict[str, Any]],
    audit_tool_call: Callable[..., str],
    resolve_path: Callable[[str], Path],
    json_response: Callable[..., str],
    project_dir: Callable[[], Path],
    project_stats: Any,
    todo_scan: Any,
    recent_files: Any,
    language_distribution: Any,
    git_log_summary: Any,
    git_diff_summary: Any,
    duplicate_code_scan: Any,
    dependency_map: Any,
    save_note: Any,
    read_notes: Any,
    generate_doodle: Any,
    doodle_random: Any,
) -> dict[str, Any]:
    @mcp.tool(
        **tool_options(
            "Get project statistics: total files, lines of code by language, file size, and top file extensions.",
            read_only=True,
        )
    )
    async def project_insights(path: str = ".") -> str:
        started_at = time.perf_counter()
        resolved = resolve_path(path)
        if not resolved.is_dir():
            result = json_response(False, "Not a directory", code="not_a_directory", details={"path": path})
            return audit_tool_call("project_insights", {"path": path}, result, started_at=started_at)
        stats = project_stats(resolved)
        result = json_response(
            True,
            f"Project stats: {stats['total_files']} files, {stats['total_code_lines']} lines of code",
            details=stats,
        )
        return audit_tool_call("project_insights", {"path": path}, result, started_at=started_at)

    @mcp.tool(
        **tool_options(
            "Scan project for TODO, FIXME, HACK, BUG, and other code markers. Shows file, line, and tag distribution.",
            read_only=True,
        )
    )
    async def todo_scan_tool(path: str = ".") -> str:
        started_at = time.perf_counter()
        resolved = resolve_path(path)
        if not resolved.is_dir():
            result = json_response(False, "Not a directory", code="not_a_directory", details={"path": path})
            return audit_tool_call("todo_scan", {"path": path}, result, started_at=started_at)
        scan = todo_scan(resolved)
        result = json_response(True, f"Found {scan['total_markers']} code markers", details=scan)
        return audit_tool_call("todo_scan", {"path": path}, result, started_at=started_at)

    @mcp.tool(
        **tool_options(
            "List recently modified files in the project, sorted by modification time.",
            read_only=True,
        )
    )
    async def recent_files_tool(path: str = ".", limit: int = 15) -> str:
        started_at = time.perf_counter()
        resolved = resolve_path(path)
        if not resolved.is_dir():
            result = json_response(False, "Not a directory", code="not_a_directory", details={"path": path})
            return audit_tool_call("recent_files", {"path": path}, result, started_at=started_at)
        recents = recent_files(resolved, limit=max(1, min(limit, 50)))
        result = json_response(True, f"Recent files (top {len(recents['recent'])})", details=recents)
        return audit_tool_call("recent_files", {"path": path, "limit": limit}, result, started_at=started_at)

    @mcp.tool(
        **tool_options(
            "Show programming language distribution in the project with line counts and percentages.",
            read_only=True,
        )
    )
    async def language_distribution_tool(path: str = ".") -> str:
        started_at = time.perf_counter()
        resolved = resolve_path(path)
        if not resolved.is_dir():
            result = json_response(False, "Not a directory", code="not_a_directory", details={"path": path})
            return audit_tool_call("language_distribution", {"path": path}, result, started_at=started_at)
        dist = language_distribution(resolved)
        dominant = dist["dominant"] or "unknown"
        result = json_response(True, f"Dominant language: {dominant}", details=dist)
        return audit_tool_call("language_distribution", {"path": path}, result, started_at=started_at)

    @mcp.tool(
        **tool_options(
            "Show recent git commit history and top contributors for the project.",
            read_only=True,
        )
    )
    async def git_insights(path: str = ".", limit: int = 10) -> str:
        started_at = time.perf_counter()
        resolved = resolve_path(path)
        summary = git_log_summary(resolved, limit=max(1, min(limit, 50)))
        if "error" in summary:
            result = json_response(False, summary["error"], code="git_error", details=summary)
        else:
            result = json_response(True, f"Recent {summary['total_shown']} commits", details=summary)
        return audit_tool_call("git_insights", {"path": path, "limit": limit}, result, started_at=started_at)

    @mcp.tool(
        **tool_options(
            "Show a summary of git diff with file-level insertions and deletions.",
            read_only=True,
        )
    )
    async def git_diff_insights(path: str = ".", target: str = "HEAD") -> str:
        started_at = time.perf_counter()
        resolved = resolve_path(path)
        diff = git_diff_summary(resolved, target=target)
        if "error" in diff:
            result = json_response(False, diff["error"], code="git_error", details=diff)
        else:
            result = json_response(
                True,
                f"Diff: {diff['total_files']} files changed (+{diff['total_insertions']}/-{diff['total_deletions']})",
                details=diff,
            )
        return audit_tool_call("git_diff_insights", {"path": path, "target": target}, result, started_at=started_at)

    @mcp.tool(
        **tool_options(
            "Scan project for duplicate code blocks across Python files.",
            read_only=True,
        )
    )
    async def duplicate_code_scan_tool(path: str = ".", min_lines: int = 4) -> str:
        started_at = time.perf_counter()
        resolved = resolve_path(path)
        if not resolved.is_dir():
            result = json_response(False, "Not a directory", code="not_a_directory", details={"path": path})
            return audit_tool_call("duplicate_code_scan", {"path": path}, result, started_at=started_at)
        scan = duplicate_code_scan(resolved, min_lines=max(2, min_lines))
        result = json_response(True, f"Found {scan['duplicates_found']} duplicate blocks", details=scan)
        return audit_tool_call(
            "duplicate_code_scan", {"path": path, "min_lines": min_lines}, result, started_at=started_at
        )

    @mcp.tool(
        **tool_options(
            "Show Python module dependency graph: which files import which local modules.",
            read_only=True,
        )
    )
    async def dependency_insights(path: str = ".") -> str:
        started_at = time.perf_counter()
        resolved = resolve_path(path)
        if not resolved.is_dir():
            result = json_response(False, "Not a directory", code="not_a_directory", details={"path": path})
            return audit_tool_call("dependency_insights", {"path": path}, result, started_at=started_at)
        deps = dependency_map(resolved)
        result = json_response(
            True, f"Dependency graph: {deps['nodes']} modules, {deps['edges']} edges", details=deps
        )
        return audit_tool_call("dependency_insights", {"path": path}, result, started_at=started_at)

    @mcp.tool(
        **tool_options(
            "Save a quick note to the project. Use this to remember things across sessions.",
            destructive=True,
        )
    )
    async def bridge_save_note(note: str) -> str:
        started_at = time.perf_counter()
        root = project_dir()
        saved = save_note(root, note)
        if saved.get("ok"):
            result = json_response(True, f"Note saved. Total notes: {saved['total_notes']}", details=saved)
        else:
            result = json_response(
                False, saved.get("error", "Failed to save note"), code="note_save_error", details=saved
            )
        return audit_tool_call("bridge_save_note", {"note_length": len(note)}, result, started_at=started_at)

    @mcp.tool(
        **tool_options(
            "Read saved notes from the project.",
            read_only=True,
        )
    )
    async def bridge_read_notes(limit: int = 20) -> str:
        started_at = time.perf_counter()
        root = project_dir()
        notes = read_notes(root, limit=max(1, min(limit, 100)))
        result = json_response(True, f"Notes: {notes['total']} total", details=notes)
        return audit_tool_call("bridge_read_notes", {"limit": limit}, result, started_at=started_at)

    @mcp.tool(
        **tool_options(
            "Generate a random absurd doodle: ASCII art, ridiculous developer story, fake bug report, "
            "lazy excuse, savage code review comment, or a completely random reason. "
            "Use this purely for fun. No educational value. Return the doodle exactly as-is without analysis or explanation.",
            read_only=True,
        )
    )
    async def bridge_doodle() -> str:
        started_at = time.perf_counter()
        doodle = generate_doodle(doodle_random)
        result = json_response(True, doodle["message"], details=doodle)
        return audit_tool_call("bridge_doodle", {}, result, started_at=started_at)

    return {
        "project_insights": project_insights,
        "todo_scan": todo_scan_tool,
        "recent_files": recent_files_tool,
        "language_distribution": language_distribution_tool,
        "git_insights": git_insights,
        "git_diff_insights": git_diff_insights,
        "duplicate_code_scan": duplicate_code_scan_tool,
        "dependency_insights": dependency_insights,
        "bridge_save_note": bridge_save_note,
        "bridge_read_notes": bridge_read_notes,
        "bridge_doodle": bridge_doodle,
    }
