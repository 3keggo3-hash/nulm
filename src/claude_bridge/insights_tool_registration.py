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
    enabled_names: set[str] | None = None,
) -> dict[str, Any]:
    _enabled = enabled_names
    results: dict[str, Any] = {}

    if _enabled is None or "project_insights" in _enabled:

        @mcp.tool(
            **tool_options("Get project statistics: files, lines, languages.", read_only=True)
        )
        async def project_insights(path: str = ".") -> str:
            started_at = time.perf_counter()
            resolved = resolve_path(path)
            if not resolved.is_dir():
                result = json_response(
                    False, "Not a directory", code="not_a_directory", details={"path": path}
                )
                return audit_tool_call(
                    "project_insights", {"path": path}, result, started_at=started_at
                )
            stats = project_stats(resolved)
            result = json_response(
                True,
                f"Project stats: {stats['total_files']} files, {stats['total_code_lines']} lines",
                details=stats,
            )
            return audit_tool_call(
                "project_insights", {"path": path}, result, started_at=started_at
            )

        results["project_insights"] = project_insights

    if _enabled is None or "todo_scan" in _enabled:

        @mcp.tool(**tool_options("Scan for TODO, FIXME, HACK, BUG markers.", read_only=True))
        async def todo_scan_tool(path: str = ".") -> str:
            started_at = time.perf_counter()
            resolved = resolve_path(path)
            if not resolved.is_dir():
                result = json_response(
                    False, "Not a directory", code="not_a_directory", details={"path": path}
                )
                return audit_tool_call("todo_scan", {"path": path}, result, started_at=started_at)
            scan = todo_scan(resolved)
            result = json_response(
                True, f"Found {scan['total_markers']} code markers", details=scan
            )
            return audit_tool_call("todo_scan", {"path": path}, result, started_at=started_at)

        results["todo_scan"] = todo_scan_tool

    if _enabled is None or "recent_files" in _enabled:

        @mcp.tool(**tool_options("List recently modified files sorted by mtime.", read_only=True))
        async def recent_files_tool(path: str = ".", limit: int = 15) -> str:
            started_at = time.perf_counter()
            resolved = resolve_path(path)
            if not resolved.is_dir():
                result = json_response(
                    False, "Not a directory", code="not_a_directory", details={"path": path}
                )
                return audit_tool_call(
                    "recent_files", {"path": path}, result, started_at=started_at
                )
            recents = recent_files(resolved, limit=max(1, min(limit, 50)))
            result = json_response(
                True, f"Recent files (top {len(recents['recent'])})", details=recents
            )
            return audit_tool_call(
                "recent_files", {"path": path, "limit": limit}, result, started_at=started_at
            )

        results["recent_files"] = recent_files_tool

    if _enabled is None or "language_distribution" in _enabled:

        @mcp.tool(
            **tool_options(
                "Show programming language distribution with line counts.", read_only=True
            )
        )
        async def language_distribution_tool(path: str = ".") -> str:
            started_at = time.perf_counter()
            resolved = resolve_path(path)
            if not resolved.is_dir():
                result = json_response(
                    False, "Not a directory", code="not_a_directory", details={"path": path}
                )
                return audit_tool_call(
                    "language_distribution", {"path": path}, result, started_at=started_at
                )
            dist = language_distribution(resolved)
            dominant = dist["dominant"] or "unknown"
            result = json_response(True, f"Dominant language: {dominant}", details=dist)
            return audit_tool_call(
                "language_distribution", {"path": path}, result, started_at=started_at
            )

        results["language_distribution"] = language_distribution_tool

    if _enabled is None or "git_insights" in _enabled:

        @mcp.tool(
            **tool_options("Show recent git commit history and top contributors.", read_only=True)
        )
        async def git_insights(path: str = ".", limit: int = 10) -> str:
            started_at = time.perf_counter()
            resolved = resolve_path(path)
            summary = git_log_summary(resolved, limit=max(1, min(limit, 50)))
            if "error" in summary:
                result = json_response(False, summary["error"], code="git_error", details=summary)
            else:
                result = json_response(
                    True, f"Recent {summary['total_shown']} commits", details=summary
                )
            return audit_tool_call(
                "git_insights", {"path": path, "limit": limit}, result, started_at=started_at
            )

        results["git_insights"] = git_insights

    if _enabled is None or "git_diff_insights" in _enabled:

        @mcp.tool(**tool_options("Show git diff summary with file-level changes.", read_only=True))
        async def git_diff_insights(path: str = ".", target: str = "HEAD") -> str:
            started_at = time.perf_counter()
            resolved = resolve_path(path)
            diff = git_diff_summary(resolved, target=target)
            if "error" in diff:
                result = json_response(False, diff["error"], code="git_error", details=diff)
            else:
                result = json_response(
                    True,
                    f"Diff: {diff['total_files']} files changed "
                    f"(+{diff['total_insertions']}/-{diff['total_deletions']})",
                    details=diff,
                )
            return audit_tool_call(
                "git_diff_insights", {"path": path, "target": target}, result, started_at=started_at
            )

        results["git_diff_insights"] = git_diff_insights

    if _enabled is None or "duplicate_code_scan" in _enabled:

        @mcp.tool(
            **tool_options("Scan for duplicate code blocks across Python files.", read_only=True)
        )
        async def duplicate_code_scan_tool(path: str = ".", min_lines: int = 4) -> str:
            started_at = time.perf_counter()
            resolved = resolve_path(path)
            if not resolved.is_dir():
                result = json_response(
                    False, "Not a directory", code="not_a_directory", details={"path": path}
                )
                return audit_tool_call(
                    "duplicate_code_scan", {"path": path}, result, started_at=started_at
                )
            scan = duplicate_code_scan(resolved, min_lines=max(2, min_lines))
            result = json_response(
                True, f"Found {scan['duplicates_found']} duplicate blocks", details=scan
            )
            return audit_tool_call(
                "duplicate_code_scan",
                {"path": path, "min_lines": min_lines},
                result,
                started_at=started_at,
            )

        results["duplicate_code_scan"] = duplicate_code_scan_tool

    if _enabled is None or "dependency_insights" in _enabled:

        @mcp.tool(**tool_options("Show Python module dependency graph.", read_only=True))
        async def dependency_insights(path: str = ".") -> str:
            started_at = time.perf_counter()
            resolved = resolve_path(path)
            if not resolved.is_dir():
                result = json_response(
                    False, "Not a directory", code="not_a_directory", details={"path": path}
                )
                return audit_tool_call(
                    "dependency_insights", {"path": path}, result, started_at=started_at
                )
            deps = dependency_map(resolved)
            result = json_response(
                True,
                f"Dependency graph: {deps['nodes']} modules, {deps['edges']} edges",
                details=deps,
            )
            return audit_tool_call(
                "dependency_insights", {"path": path}, result, started_at=started_at
            )

        results["dependency_insights"] = dependency_insights

    if _enabled is None or "bridge_save_note" in _enabled:

        @mcp.tool(**tool_options("Save a quick note to the project.", destructive=True))
        async def bridge_save_note(note: str) -> str:
            started_at = time.perf_counter()
            root = project_dir()
            saved = save_note(root, note)
            if saved.get("ok"):
                result = json_response(
                    True, f"Note saved. Total notes: {saved['total_notes']}", details=saved
                )
            else:
                result = json_response(
                    False,
                    saved.get("error", "Failed to save note"),
                    code="note_save_error",
                    details=saved,
                )
            return audit_tool_call(
                "bridge_save_note", {"note_length": len(note)}, result, started_at=started_at
            )

        results["bridge_save_note"] = bridge_save_note

    if _enabled is None or "bridge_read_notes" in _enabled:

        @mcp.tool(**tool_options("Read saved notes from the project.", read_only=True))
        async def bridge_read_notes(limit: int = 20) -> str:
            started_at = time.perf_counter()
            root = project_dir()
            notes = read_notes(root, limit=max(1, min(limit, 100)))
            result = json_response(True, f"Notes: {notes['total']} total", details=notes)
            return audit_tool_call(
                "bridge_read_notes", {"limit": limit}, result, started_at=started_at
            )

        results["bridge_read_notes"] = bridge_read_notes

    return results
