"""File-oriented tool implementations for Claude Bridge."""

from __future__ import annotations

import ast
import difflib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from claude_bridge.git_ops import git_commit
from claude_bridge.indexing import iter_searchable_files
from claude_bridge.tool_utils import (
    find_secret_patterns,
    infer_project_root,
    is_binary_bytes,
    is_within_root,
    json_response,
    path_outside_project_details,
    request_approval,
    require_approval,
    resolve_path,
    safe_read_text,
    sensitive_path_reason,
)

_MAX_SEARCH_RESULTS = 200
_MAX_READ_FILE_LINES = 200
_MAX_LIST_DIRECTORY_ENTRIES = 200
_WRITE_FILE_WARNING_LINES = 50
_MAX_MULTI_FILE_READS = 20
_git_commit = git_commit
_LAST_BRIDGE_CHANGE_LOCK = threading.Lock()
_LAST_BRIDGE_CHANGE: dict[str, Any] | None = None


def _remember_bridge_change(
    *,
    target: Path,
    project_dir: Path,
    previous_exists: bool,
    previous_content: str | None,
    new_content: str,
    operation: str,
    git_result: dict[str, Any],
) -> None:
    global _LAST_BRIDGE_CHANGE
    with _LAST_BRIDGE_CHANGE_LOCK:
        _LAST_BRIDGE_CHANGE = {
            "target": str(target),
            "project_dir": str(project_dir),
            "path": target.relative_to(project_dir).as_posix(),
            "previous_exists": previous_exists,
            "previous_content": previous_content,
            "new_content": new_content,
            "operation": operation,
            "git_result": git_result,
        }


def _last_bridge_change() -> dict[str, Any] | None:
    with _LAST_BRIDGE_CHANGE_LOCK:
        return dict(_LAST_BRIDGE_CHANGE) if _LAST_BRIDGE_CHANGE is not None else None


def clear_last_bridge_change() -> None:
    global _LAST_BRIDGE_CHANGE
    with _LAST_BRIDGE_CHANGE_LOCK:
        _LAST_BRIDGE_CHANGE = None


def _estimate_patch_risk(file_path: str, original: str, updated: str) -> dict[str, Any]:
    added = max(0, len(updated.splitlines()) - len(original.splitlines()))
    removed = max(0, len(original.splitlines()) - len(updated.splitlines()))
    lowered_path = file_path.lower()
    touches_tests = any(part in lowered_path for part in ("test", "tests"))
    touches_config = any(
        lowered_path.endswith(suffix)
        for suffix in (".json", ".toml", ".yaml", ".yml", ".ini", ".cfg")
    )
    touches_secrets = any(
        lowered_path.endswith(suffix) for suffix in (".env", ".pem", ".key", ".p12", ".pfx")
    )
    public_api_change_possible = "def " in original or "class " in original
    large_deletion = removed >= 25
    reasons: list[str] = []
    if touches_config:
        reasons.append("touches configuration")
    if touches_secrets:
        reasons.append("touches sensitive file types")
    if large_deletion:
        reasons.append("large deletion")
    if added + removed > 50:
        reasons.append("large diff")
    if public_api_change_possible and (added + removed) > 15:
        reasons.append("possible public API impact")

    if touches_secrets or large_deletion or (added + removed) > 100:
        risk_level = "high"
    elif touches_config or (added + removed) > 20:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "risk_level": risk_level,
        "risk_reasons": reasons,
        "lines_added": added,
        "lines_removed": removed,
        "files_touched": 1,
        "touches_tests": touches_tests,
        "touches_config": touches_config,
        "touches_secrets": touches_secrets,
        "large_deletion": large_deletion,
        "public_api_change_possible": public_api_change_possible,
    }


def _paginate_text_preview(content: str, *, line_limit: int) -> dict[str, Any]:
    lines = content.splitlines(keepends=True)
    preview_lines = lines[:line_limit]
    truncated = len(lines) > line_limit
    return {
        "content": "".join(preview_lines),
        "line_count": len(lines),
        "returned_line_count": len(preview_lines),
        "truncated": truncated,
        "line_limit": line_limit,
    }


def _line_ending_for_content(content: str) -> str:
    if "\r\n" in content:
        return "\r\n"
    if "\r" in content:
        return "\r"
    return "\n"


def _normalize_line_endings(value: str, *, line_ending: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.replace("\n", line_ending)


def _slice_text_lines(content: str, *, offset: int, limit: int) -> dict[str, Any]:
    safe_limit = max(1, limit)
    lines = content.splitlines(keepends=True)
    total_lines = len(lines)
    if offset < 0:
        start = max(0, total_lines + offset)
    else:
        start = min(offset, total_lines)
    page = lines[start : start + safe_limit]
    return {
        "content": "".join(page),
        "line_count": total_lines,
        "returned_line_count": len(page),
        "truncated": (start + safe_limit) < total_lines,
        "line_limit": safe_limit,
        "offset": start,
        "has_more": (start + safe_limit) < total_lines,
    }


def _fuzzy_log_path() -> Path:
    override = os.environ.get("CLAUDE_BRIDGE_AUDIT_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve() / "fuzzy-search.log"
    return (Path.home() / ".claude-bridge" / "fuzzy-search.log").resolve()


def _log_fuzzy_match_attempt(*, file: str, search: str, suggestions: list[str]) -> None:
    path = _fuzzy_log_path()
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "path": file,
        "search_preview": search[:120],
        "search_length": len(search),
        "suggestions": suggestions[:3],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json_response(True, "fuzzy", details=entry) + "\n")
    except OSError:
        return


def _write_text_exact(target: Path, content: str) -> None:
    with target.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def _read_text_preserve_line_endings(target: Path) -> str:
    return target.read_bytes().decode("utf-8")


def _rg_binary() -> str | None:
    return shutil.which("rg")


def _run_ripgrep_search(
    *,
    query: str,
    target: Path,
    root: Path,
    display_root: Path,
    regex: bool,
    case_sensitive: bool,
    include_glob: str | None,
    offset: int,
    limit: int,
) -> dict[str, Any] | None:
    rg = _rg_binary()
    if rg is None:
        return None

    command = [rg, "--json", "--line-number", "--with-filename", "--color", "never"]
    if not case_sensitive:
        command.append("--ignore-case")
    if not regex:
        command.append("--fixed-strings")
    if include_glob:
        command.extend(["-g", include_glob])
    command.extend([query, str(target)])

    try:
        completed = subprocess.run(
            command,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=root,
            check=False,
        )
    except OSError:
        return None

    if completed.returncode not in {0, 1}:
        return None

    results: list[dict[str, Any]] = []
    unique_files: set[str] = set()
    truncated = False
    match_count = 0
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "match":
            continue
        data = event.get("data", {})
        path_text = str(data.get("path", {}).get("text", ""))
        absolute_path = Path(path_text)
        if not absolute_path.is_absolute():
            absolute_path = (root / absolute_path).resolve()
        if sensitive_path_reason(absolute_path) is not None:
            continue
        line_number = int(data.get("line_number", 0) or 0)
        line_text = str(data.get("lines", {}).get("text", ""))
        relative_path = (
            absolute_path.relative_to(display_root).as_posix()
            if target.is_dir()
            else absolute_path.name
        )
        unique_files.add(relative_path)
        if match_count < offset:
            match_count += 1
            continue
        if len(results) >= limit:
            truncated = True
            break
        results.append(
            {
                "path": relative_path,
                "line_number": line_number,
                "line": line_text.rstrip("\n")[:300],
            }
        )
        match_count += 1

    return {
        "results": results,
        "truncated": truncated,
        "files_searched": max(len(unique_files), 1 if results else 0),
        "search_backend": "ripgrep",
        "offset": offset,
        "next_offset": offset + len(results) if truncated else None,
    }


def _build_preview_patch_result(
    target: Path,
    original: str,
    file: str,
    search: str,
    replace: str,
) -> dict[str, Any]:
    line_ending = _line_ending_for_content(original)
    original_norm = original.replace("\r\n", "\n").replace("\r", "\n")
    search_norm = search.replace("\r\n", "\n").replace("\r", "\n")
    replace_norm = replace.replace("\r\n", "\n").replace("\r", "\n")
    matches = original_norm.count(search_norm)
    if matches == 0:
        suggestions = difflib.get_close_matches(
            search_norm.strip(),
            [line.strip() for line in original_norm.splitlines() if line.strip()],
            n=3,
            cutoff=0.7,
        )
        if suggestions:
            _log_fuzzy_match_attempt(file=file, search=search_norm, suggestions=suggestions)
            return {
                "ok": False,
                "message": "SEARCH text not found exactly, but similar lines were found",
                "code": "search_fuzzy_match_available",
                "details": {"path": file, "suggestions": suggestions},
            }
        return {
            "ok": False,
            "message": "SEARCH text not found in file",
            "code": "search_not_found",
            "details": {"path": file},
        }
    if matches > 1:
        return {
            "ok": False,
            "message": f"SEARCH text is ambiguous (found {matches} times)",
            "code": "search_ambiguous",
            "details": {"path": file, "matches": matches},
        }

    new_content_norm = original_norm.replace(search_norm, replace_norm, 1)
    new_content_with_original_endings = _normalize_line_endings(
        new_content_norm, line_ending=line_ending
    )
    if target.suffix == ".py":
        try:
            ast.parse(new_content_norm)
        except SyntaxError as exc:
            return {
                "ok": False,
                "message": f"Python syntax error after patch: {exc}",
                "code": "python_syntax_error",
                "details": {"path": file, "error": str(exc)},
            }

    secret_patterns = find_secret_patterns(new_content_with_original_endings)
    if secret_patterns:
        return {
            "ok": False,
            "message": "Patch introduces content that looks sensitive",
            "code": "secret_pattern_detected",
            "details": {"path": file, "patterns": secret_patterns},
        }

    diff = "\n".join(
        difflib.unified_diff(
            original_norm.splitlines(),
            new_content_norm.splitlines(),
            fromfile=file,
            tofile=file,
            lineterm="",
        )
    )
    risk = _estimate_patch_risk(file, original_norm, new_content_norm)
    return {
        "ok": True,
        "message": f"Previewed patch for {file}",
        "details": {
            "path": file,
            "resolved_path": str(target),
            "matches": matches,
            "diff": diff,
            "risk": risk,
            "line_ending": repr(line_ending),
        },
    }


async def read_file(path: str, offset: int = 0, limit: int = _MAX_READ_FILE_LINES) -> str:
    try:
        target = resolve_path(path)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(path),
        )

    if not target.exists():
        return json_response(
            False,
            f"File not found: {path}",
            code="file_not_found",
            details={"path": path},
        )
    if not target.is_file():
        return json_response(
            False,
            f"Not a file: {path}",
            code="not_a_file",
            details={"path": path},
        )
    sensitive_reason = sensitive_path_reason(target)
    if sensitive_reason is not None:
        return json_response(
            False,
            "Sensitive files are blocked from direct reading",
            code="sensitive_file_blocked",
            details={"path": path, "resolved_path": str(target), "reason": sensitive_reason},
        )

    try:
        content = safe_read_text(target)
    except (OSError, UnicodeDecodeError) as exc:
        return json_response(
            False,
            f"Failed to read file: {exc}",
            code="file_read_error",
            details={"path": path},
        )

    preview = _slice_text_lines(content, offset=offset, limit=min(max(1, limit), _MAX_READ_FILE_LINES))
    return json_response(
        True,
        f"Read file: {path}",
        details={
            "path": path,
            "resolved_path": str(target),
            "content": preview["content"],
            "line_count": preview["line_count"],
            "returned_line_count": preview["returned_line_count"],
            "truncated": preview["truncated"],
            "line_limit": preview["line_limit"],
            "offset": preview["offset"],
            "has_more": preview["has_more"],
        },
    )


async def read_multiple_files(
    paths: list[str],
    offset: int = 0,
    limit: int = _MAX_READ_FILE_LINES,
) -> str:
    if not paths:
        return json_response(
            False,
            "At least one path is required",
            code="empty_paths",
            details={"paths": paths},
        )
    if len(paths) > _MAX_MULTI_FILE_READS:
        return json_response(
            False,
            f"At most {_MAX_MULTI_FILE_READS} files can be read at once",
            code="too_many_paths",
            details={"max_paths": _MAX_MULTI_FILE_READS, "requested_paths": len(paths)},
        )

    files: list[dict[str, Any]] = []
    for path in paths:
        try:
            target = resolve_path(path)
        except PermissionError:
            files.append(
                {
                    "path": path,
                    "ok": False,
                    "code": "path_outside_project",
                    "details": path_outside_project_details(path),
                }
            )
            continue
        if not target.exists():
            files.append({"path": path, "ok": False, "code": "file_not_found"})
            continue
        if not target.is_file():
            files.append({"path": path, "ok": False, "code": "not_a_file"})
            continue
        sensitive_reason = sensitive_path_reason(target)
        if sensitive_reason is not None:
            files.append(
                {
                    "path": path,
                    "ok": False,
                    "code": "sensitive_file_blocked",
                    "reason": sensitive_reason,
                }
            )
            continue
        try:
            content = safe_read_text(target)
        except (OSError, UnicodeDecodeError) as exc:
            files.append({"path": path, "ok": False, "code": "file_read_error", "error": str(exc)})
            continue
        preview = _slice_text_lines(
            content,
            offset=offset,
            limit=min(max(1, limit), _MAX_READ_FILE_LINES),
        )
        files.append(
            {
                "path": path,
                "resolved_path": str(target),
                "ok": True,
                **preview,
            }
        )
    return json_response(
        True,
        f"Read {len(files)} files",
        details={"files": files, "requested_paths": len(paths)},
    )


async def list_directory(path: str = ".") -> str:
    try:
        target = resolve_path(path)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(path),
        )

    if not target.exists():
        return json_response(
            False,
            f"Directory not found: {path}",
            code="directory_not_found",
            details={"path": path},
        )
    if not target.is_dir():
        return json_response(
            False,
            f"Not a directory: {path}",
            code="not_a_directory",
            details={"path": path},
        )

    try:
        entries = [
            {
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
                "size": entry.stat().st_size if entry.is_file() else None,
            }
            for entry in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name))
        ]
    except OSError as exc:
        return json_response(
            False,
            f"Failed to list directory: {exc}",
            code="directory_read_error",
            details={"path": path},
        )

    return json_response(
        True,
        f"Listed directory: {path}",
        details={
            "path": path,
            "resolved_path": str(target),
            "entries": entries[:_MAX_LIST_DIRECTORY_ENTRIES],
            "entry_count": len(entries),
            "returned_entry_count": min(len(entries), _MAX_LIST_DIRECTORY_ENTRIES),
            "truncated": len(entries) > _MAX_LIST_DIRECTORY_ENTRIES,
            "entry_limit": _MAX_LIST_DIRECTORY_ENTRIES,
        },
    )


async def write_file(
    path: str,
    content: str,
    overwrite: bool = False,
    create_parents: bool = False,
    *,
    git_commit_fn: Callable[..., dict[str, Any]] = _git_commit,
) -> str:
    try:
        target = resolve_path(path)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(path),
        )

    sensitive_reason = sensitive_path_reason(target)
    if sensitive_reason is not None:
        return json_response(
            False,
            "Sensitive file types cannot be written through this tool",
            code="sensitive_file_blocked",
            details={"path": path, "resolved_path": str(target), "reason": sensitive_reason},
        )

    secret_patterns = find_secret_patterns(content)
    if secret_patterns:
        return json_response(
            False,
            "Content looks sensitive and was blocked",
            code="secret_pattern_detected",
            details={"path": path, "patterns": secret_patterns},
        )

    if target.exists() and target.is_dir():
        return json_response(
            False,
            f"Not a file: {path}",
            code="not_a_file",
            details={"path": path},
        )
    if target.exists() and not overwrite:
        return json_response(
            False,
            f"File already exists: {path}",
            code="file_exists",
            details={"path": path},
        )
    if not target.parent.exists() and not create_parents:
        return json_response(
            False,
            f"Parent directory does not exist: {target.parent}",
            code="parent_directory_missing",
            details={"path": path, "parent": str(target.parent)},
        )

    if target.suffix == ".py":
        try:
            ast.parse(content)
        except SyntaxError as exc:
            return json_response(
                False,
                f"Python syntax error in file content: {exc}",
                code="python_syntax_error",
                details={"path": path, "error": str(exc)},
            )

    rejection = await require_approval(
        "write_file",
        {"file": path, "overwrite": overwrite},
        rejection_message="Write rejected by user",
        rejection_details={"path": path},
    )
    if rejection is not None:
        return rejection

    if create_parents:
        target.parent.mkdir(parents=True, exist_ok=True)
    previous_exists = target.exists()
    previous_content = None
    if previous_exists:
        try:
            previous_content = safe_read_text(target)
        except (OSError, UnicodeDecodeError):
            previous_content = None
    try:
        _write_text_exact(target, content)
    except OSError as exc:
        return json_response(
            False,
            f"Failed to write file: {exc}",
            code="file_write_error",
            details={"path": path},
        )

    try:
        target_project_dir = infer_project_root(target)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(path),
        )
    git_result = git_commit_fn(
        target.relative_to(target_project_dir).as_posix(),
        project_dir=target_project_dir,
    )
    _remember_bridge_change(
        target=target,
        project_dir=target_project_dir,
        previous_exists=previous_exists,
        previous_content=previous_content,
        new_content=content,
        operation="write_file",
        git_result=git_result,
    )
    warning = None
    if previous_exists:
        warning = (
            "Prefer patch_file for existing files when making targeted edits so the model can keep changes small and reviewable."
        )
    elif len(content.splitlines()) > _WRITE_FILE_WARNING_LINES:
        warning = (
            f"Content is {len(content.splitlines())} lines. For large changes, prefer smaller patch_file edits when possible."
        )

    return json_response(
        True,
        f"Wrote file: {path}",
        details={
            "path": path,
            "resolved_path": str(target),
            "bytes_written": len(content.encode("utf-8")),
            "created": not previous_exists,
            "overwritten": previous_exists and overwrite,
            "git": git_result,
            "warning": warning,
        },
    )


async def search_in_files(
    query: str,
    path: str = ".",
    regex: bool = False,
    case_sensitive: bool = False,
    include_glob: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> str:
    stripped = query.strip()
    if not stripped:
        return json_response(
            False,
            "Query cannot be empty",
            code="empty_query",
            details={"query": query},
        )
    if offset < 0:
        return json_response(
            False,
            "Offset must be 0 or greater",
            code="invalid_offset",
            details={"offset": offset},
        )
    if limit < 1 or limit > _MAX_SEARCH_RESULTS:
        return json_response(
            False,
            f"Limit must be between 1 and {_MAX_SEARCH_RESULTS}",
            code="invalid_limit",
            details={"limit": limit, "max_limit": _MAX_SEARCH_RESULTS},
        )

    try:
        target = resolve_path(path)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(path),
        )

    if not target.exists():
        return json_response(
            False,
            f"Path not found: {path}",
            code="path_not_found",
            details={"path": path},
        )

    project_root = infer_project_root(target)
    root = target if target.is_dir() else target.parent
    rg_payload = _run_ripgrep_search(
        query=query,
        target=target,
        root=project_root,
        display_root=root,
        regex=regex,
        case_sensitive=case_sensitive,
        include_glob=include_glob,
        offset=offset,
        limit=limit,
    )
    if rg_payload is not None:
        return json_response(
            True,
            f"Search completed for query: {query}",
            details={
                "query": query,
                "path": path,
                "regex": regex,
                "case_sensitive": case_sensitive,
                "include_glob": include_glob,
                "offset": rg_payload["offset"],
                "next_offset": rg_payload["next_offset"],
                "results": rg_payload["results"],
                "truncated": rg_payload["truncated"],
                "files_searched": rg_payload["files_searched"],
                "search_backend": rg_payload["search_backend"],
            },
        )

    try:
        files = iter_searchable_files(
            target if target.is_dir() else target,
            project_root,
            is_within_root=is_within_root,
            is_binary_bytes=is_binary_bytes,
            include_glob=include_glob,
        )
    except OSError as exc:
        return json_response(
            False,
            f"Failed to search files: {exc}",
            code="search_error",
            details={"path": path},
        )

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(query if regex else re.escape(query), flags)
    except re.error as exc:
        return json_response(
            False,
            f"Invalid regular expression: {exc}",
            code="invalid_regex",
            details={"query": query},
        )

    results: list[dict[str, Any]] = []
    files_searched = 0
    truncated = False
    match_count = 0
    for file_path in files:
        if sensitive_path_reason(file_path) is not None:
            continue
        try:
            content = safe_read_text(file_path)
        except (OSError, UnicodeDecodeError):
            continue
        files_searched += 1
        relative_path = file_path.relative_to(root).as_posix() if target.is_dir() else file_path.name
        for line_number, line in enumerate(content.splitlines(), start=1):
            if not pattern.search(line):
                continue
            if match_count < offset:
                match_count += 1
                continue
            if len(results) >= limit:
                truncated = True
                break
            results.append(
                {
                    "path": relative_path,
                    "line_number": line_number,
                    "line": line[:300],
                }
            )
            match_count += 1
        if len(results) >= limit:
            break

    return json_response(
        True,
        f"Search completed for query: {query}",
        details={
            "query": query,
            "path": path,
            "regex": regex,
            "case_sensitive": case_sensitive,
            "include_glob": include_glob,
            "offset": offset,
            "next_offset": offset + len(results) if truncated else None,
            "results": results,
            "truncated": truncated,
            "files_searched": files_searched,
            "search_backend": "python",
        },
    )


async def patch_file(
    file: str,
    search: str,
    replace: str,
    *,
    git_commit_fn: Callable[..., dict[str, Any]] = _git_commit,
) -> str:
    try:
        target = resolve_path(file)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(file),
        )

    try:
        target_project_dir = infer_project_root(target)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(file),
        )
    if not target.exists():
        return json_response(
            False,
            f"File not found: {file}",
            code="file_not_found",
            details={"path": file},
        )
    if not target.is_file():
        return json_response(
            False,
            f"Not a file: {file}",
            code="not_a_file",
            details={"path": file},
        )

    sensitive_reason = sensitive_path_reason(target)
    if sensitive_reason is not None:
        return json_response(
            False,
            "Sensitive files are blocked from direct patching",
            code="sensitive_file_blocked",
            details={"path": file, "resolved_path": str(target), "reason": sensitive_reason},
        )

    try:
        original = _read_text_preserve_line_endings(target)
    except (OSError, UnicodeDecodeError) as exc:
        return json_response(
            False,
            f"Failed to read file: {exc}",
            code="file_read_error",
            details={"path": file},
        )

    preview_payload = _build_preview_patch_result(target, original, file, search, replace)
    if not preview_payload["ok"]:
        return json_response(
            False,
            preview_payload["message"],
            code=preview_payload["code"],
            details=preview_payload["details"],
        )

    rejection = await require_approval(
        "patch_file",
        {"file": file},
        rejection_message="Patch rejected by user",
        rejection_details={"path": file},
    )
    if rejection is not None:
        return rejection

    line_ending = _line_ending_for_content(original)
    original_norm = original.replace("\r\n", "\n").replace("\r", "\n")
    search_norm = search.replace("\r\n", "\n").replace("\r", "\n")
    replace_norm = replace.replace("\r\n", "\n").replace("\r", "\n")
    new_content_norm = original_norm.replace(search_norm, replace_norm, 1)
    new_content = _normalize_line_endings(new_content_norm, line_ending=line_ending)
    try:
        _write_text_exact(target, new_content)
    except OSError as exc:
        return json_response(
            False,
            f"Failed to write file: {exc}",
            code="file_write_error",
            details={"path": file},
        )

    git_result = git_commit_fn(
        target.relative_to(target_project_dir).as_posix(),
        project_dir=target_project_dir,
    )
    _remember_bridge_change(
        target=target,
        project_dir=target_project_dir,
        previous_exists=True,
        previous_content=original,
        new_content=new_content,
        operation="patch_file",
        git_result=git_result,
    )
    message = f"Patched {file}"
    if not git_result["commit"]:
        message += f" (git commit failed: {git_result['output'].strip() or 'unknown error'})"

    return json_response(
        True,
        message,
        details={
            "path": file,
            "resolved_path": str(target),
            "git": git_result,
            "risk": preview_payload["details"]["risk"],
            "diff": preview_payload["details"]["diff"],
        },
    )


async def preview_patch(file: str, search: str, replace: str) -> str:
    try:
        target = resolve_path(file)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(file),
        )

    if not target.exists():
        return json_response(
            False,
            f"File not found: {file}",
            code="file_not_found",
            details={"path": file},
        )
    if not target.is_file():
        return json_response(
            False,
            f"Not a file: {file}",
            code="not_a_file",
            details={"path": file},
        )
    sensitive_reason = sensitive_path_reason(target)
    if sensitive_reason is not None:
        return json_response(
            False,
            "Sensitive files are blocked from direct previewing",
            code="sensitive_file_blocked",
            details={"path": file, "resolved_path": str(target), "reason": sensitive_reason},
        )

    try:
        original = _read_text_preserve_line_endings(target)
    except (OSError, UnicodeDecodeError) as exc:
        return json_response(
            False,
            f"Failed to read file: {exc}",
            code="file_read_error",
            details={"path": file},
        )

    preview_payload = _build_preview_patch_result(target, original, file, search, replace)
    return json_response(
        preview_payload["ok"],
        preview_payload["message"],
        code=preview_payload.get("code"),
        details=preview_payload["details"],
    )


async def undo_last_patch(
    confirm: bool = False,
    *,
    request_approval_fn: Callable[[str, dict[str, Any]], Awaitable[bool]] = request_approval,
    git_commit_fn: Callable[..., dict[str, Any]] = _git_commit,
) -> str:
    change = _last_bridge_change()
    if change is None:
        return json_response(
            False,
            "No Bridge-managed change is available to undo",
            code="no_undo_state",
            details={},
        )

    target = Path(change["target"])
    project_dir = Path(change["project_dir"])
    previous_exists = bool(change["previous_exists"])
    previous_content = change["previous_content"]
    details = {
        "path": change["path"],
        "resolved_path": str(target),
        "project_dir": str(project_dir),
        "operation": change["operation"],
        "git": change["git_result"],
        "previous_exists": previous_exists,
        "current_exists": target.exists(),
    }

    if not confirm:
        return json_response(
            False,
            "Undo requires explicit confirmation",
            code="confirmation_required",
            details=details,
        )

    rejection = await require_approval(
        "undo_last_patch",
        {
            "path": change["path"],
            "operation": change["operation"],
            "previous_exists": previous_exists,
        },
        rejection_message="Undo rejected by user",
        rejection_details=details,
        request_approval_fn=request_approval_fn,
    )
    if rejection is not None:
        return rejection

    if previous_exists:
        if previous_content is None:
            return json_response(
                False,
                "Original file content is unavailable; cannot undo safely",
                code="undo_snapshot_unavailable",
                details=details,
            )
        try:
            _write_text_exact(target, previous_content)
        except OSError as exc:
            return json_response(
                False,
                f"Failed to restore previous file content: {exc}",
                code="file_write_error",
                details=details,
            )
    else:
        try:
            if target.exists():
                target.unlink()
        except OSError as exc:
            return json_response(
                False,
                f"Failed to remove file created by the last Bridge change: {exc}",
                code="file_write_error",
                details=details,
            )

    git_result = git_commit_fn(
        change["path"],
        project_dir=project_dir,
        message=f"bridge: undo {change['path']}",
    )
    details["undo_git"] = git_result
    details["restored_to_exists"] = previous_exists
    details["restored_bytes"] = len(previous_content.encode("utf-8")) if previous_content is not None else 0

    global _LAST_BRIDGE_CHANGE
    with _LAST_BRIDGE_CHANGE_LOCK:
        _LAST_BRIDGE_CHANGE = None

    return json_response(
        True,
        f"Undid last Bridge change for {change['path']}",
        details=details,
    )
