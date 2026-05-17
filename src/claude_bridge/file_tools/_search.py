"""Search-oriented file tools."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import concurrent.futures
import difflib
import fnmatch
import re
import time as _time
from pathlib import Path
from typing import Any

from claude_bridge.tool_utils import (
    find_secret_patterns,
    infer_project_root,
    is_within_root,
    json_response,
    path_outside_project_details,
    resolve_path,
    resolve_path_safe,
    safe_read_text,
    sensitive_file_blocked_details,
    sensitive_path_reason,
)

from claude_bridge.file_tools._helpers import (
    _MAX_SEARCH_RESULTS,
    _run_ripgrep_search,
)

DEFAULT_CONTEXT_BUDGET_TOKENS = 4000
_MAX_FIND_RESULTS = 500
_MAX_DIFF_BYTES = 512 * 1024
_MAX_DIFF_CHARS = 5000


async def find_files(
    pattern: str,
    path: str = ".",
    include_dirs: bool = True,
    max_results: int = 100,
) -> str:
    """Find workspace files whose names match a glob pattern."""
    if not pattern.strip():
        return json_response(
            False,
            "Pattern cannot be empty",
            code="empty_pattern",
            details={"pattern": pattern},
        )
    if max_results < 1 or max_results > _MAX_FIND_RESULTS:
        return json_response(
            False,
            f"max_results must be between 1 and {_MAX_FIND_RESULTS}",
            code="invalid_limit",
            details={"max_results": max_results, "max_limit": _MAX_FIND_RESULTS},
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
    try:
        from claude_bridge.indexing import iter_searchable_files

        files = list(iter_searchable_files(root, project_root, is_within_root=is_within_root))
    except OSError as exc:
        return json_response(
            False,
            f"Failed to find files: {exc}",
            code="find_error",
            details={"path": path},
        )

    results: list[dict[str, Any]] = []
    if include_dirs:
        candidates: list[Path] = [root, *[p for p in root.rglob("*") if p.is_dir()]]
    else:
        candidates = []
    candidates.extend(files)

    for candidate in candidates:
        if len(results) >= max_results:
            break
        if sensitive_path_reason(candidate) is not None:
            continue
        try:
            relative = candidate.relative_to(root).as_posix()
        except ValueError:
            continue
        name_matches = fnmatch.fnmatchcase(candidate.name, pattern)
        path_matches = fnmatch.fnmatchcase(relative, pattern)
        if not (name_matches or path_matches):
            continue
        is_dir = candidate.is_dir()
        if is_dir and not include_dirs:
            continue
        results.append(
            {
                "path": relative or ".",
                "type": "directory" if is_dir else "file",
                "size": candidate.stat().st_size if candidate.is_file() else None,
            }
        )

    return json_response(
        True,
        f"Found {len(results)} matches for: {pattern}",
        details={
            "pattern": pattern,
            "path": path,
            "results": results,
            "returned_count": len(results),
            "truncated": len(results) >= max_results,
        },
    )


async def diff_files(path1: str, path2: str) -> str:
    """Compare two workspace files and return a bounded unified diff."""
    try:
        target1 = resolve_path_safe(path1)
        target2 = resolve_path_safe(path2)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(path1),
        )

    for label, target in (("path1", target1), ("path2", target2)):
        if sensitive_path_reason(target) is not None:
            return json_response(
                False,
                "Sensitive files cannot be diffed",
                code="sensitive_file_blocked",
                details=sensitive_file_blocked_details(path1 if label == "path1" else path2),
            )
        if not target.exists():
            return json_response(
                False,
                f"File not found: {path1 if label == 'path1' else path2}",
                code="file_not_found",
                details={label: path1 if label == "path1" else path2},
            )
        if not target.is_file():
            return json_response(
                False,
                f"Not a file: {path1 if label == 'path1' else path2}",
                code="not_a_file",
                details={label: path1 if label == "path1" else path2},
            )
        if target.stat().st_size > _MAX_DIFF_BYTES:
            return json_response(
                False,
                "File is too large to diff",
                code="file_too_large",
                details={label: path1 if label == "path1" else path2},
            )

    content1 = safe_read_text(target1)
    content2 = safe_read_text(target2)
    diff = "".join(
        difflib.unified_diff(
            content1.splitlines(keepends=True),
            content2.splitlines(keepends=True),
            fromfile=path1,
            tofile=path2,
        )
    )
    return json_response(
        True,
        f"Compared: {path1} vs {path2}",
        details={
            "path1": path1,
            "path2": path2,
            "identical": content1 == content2,
            "diff": diff[:_MAX_DIFF_CHARS],
            "truncated": len(diff) > _MAX_DIFF_CHARS,
        },
    )


async def append_to_file(path: str, content: str, create_parents: bool = False) -> str:
    """Append UTF-8 text to a workspace file."""
    try:
        target = resolve_path_safe(path)
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
            "Sensitive files cannot be appended to",
            code="sensitive_file_blocked",
            details=sensitive_file_blocked_details(path),
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
        return json_response(False, f"Not a file: {path}", code="not_a_file")
    if not target.parent.exists() and not create_parents:
        return json_response(
            False,
            f"Parent directory does not exist: {target.parent}",
            code="parent_directory_missing",
            details={"path": path, "parent": str(target.parent)},
        )

    try:
        if create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(content)
    except OSError as exc:
        return json_response(
            False,
            f"Failed to append to file: {exc}",
            code="append_failed",
            details={"path": path, "error": str(exc)},
        )

    return json_response(
        True,
        f"Appended to: {path}",
        details={"path": path, "bytes_written": len(content.encode("utf-8"))},
    )


def _budget_metadata(
    *, estimated_tokens: int, budget_tokens: int, recommended_next_step: str
) -> dict[str, Any]:
    from claude_bridge.smart import budget_metadata

    return budget_metadata(
        estimated_tokens=estimated_tokens,
        budget_tokens=budget_tokens,
        recommended_next_step=recommended_next_step,
    )


def _estimate_token_count(text: str) -> int:
    from claude_bridge.smart import estimate_token_count

    return estimate_token_count(text)


async def search_in_files(
    query: str,
    path: str = ".",
    regex: bool = False,
    case_sensitive: bool = False,
    include_glob: str | None = None,
    offset: int = 0,
    limit: int = 20,
    budget_tokens: int = DEFAULT_CONTEXT_BUDGET_TOKENS,
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
    if include_glob is not None and len(include_glob) > 256:
        return json_response(
            False,
            "include_glob pattern exceeds 256 character limit",
            code="glob_too_long",
            details={"include_glob_length": len(include_glob), "max_length": 256},
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
        estimated_tokens = _estimate_token_count(
            "\n".join(
                f"{item['path']}:{item['line_number']}:{item['line']}"
                for item in rg_payload["results"]
            )
        )
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
                **_budget_metadata(
                    estimated_tokens=estimated_tokens,
                    budget_tokens=budget_tokens,
                    recommended_next_step="Use find_relevant_files or read_file on strongest match instead.",
                ),
            },
        )

    try:
        from claude_bridge.indexing import iter_searchable_files

        files = iter_searchable_files(
            target,
            project_root,
            is_within_root=is_within_root,
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
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(re.compile, query if regex else re.escape(query), flags)
        try:
            pattern = future.result(timeout=2)
        except concurrent.futures.TimeoutError:
            future.cancel()
            return json_response(
                False,
                "Regular expression compilation timed out (potential ReDoS)",
                code="regex_timeout",
                details={"query": query},
            )
        except re.error as exc:
            return json_response(
                False,
                f"Invalid regular expression: {exc}",
                code="invalid_regex",
                details={"query": query},
            )

        MAX_SEARCH_SCAN_MS = 5000
        results: list[dict[str, Any]] = []
        files_searched = 0
        truncated = False
        match_count = 0

        scan_deadline = _time.monotonic() + MAX_SEARCH_SCAN_MS / 1000.0
        for file_path in files:
            if _time.monotonic() > scan_deadline:
                truncated = True
                break
            if sensitive_path_reason(file_path) is not None:
                continue
            try:
                content = safe_read_text(file_path)
            except (OSError, UnicodeDecodeError):
                continue
            files_searched += 1
            try:
                relative_path = (
                    file_path.relative_to(root).as_posix() if target.is_dir() else file_path.name
                )
            except ValueError:
                continue
            for line_number, line in enumerate(content.splitlines(), start=1):
                search_future = executor.submit(pattern.search, line)
                try:
                    match = search_future.result(timeout=2)
                except concurrent.futures.TimeoutError:
                    search_future.cancel()
                    return json_response(
                        False,
                        "Regular expression search timed out (potential ReDoS)",
                        code="regex_timeout",
                        details={"query": query, "path": str(file_path)},
                    )
                if not match:
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
                truncated = True
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
                "next_offset": offset + len(results) if truncated else -1,
                "results": results,
                "truncated": truncated,
                "files_searched": files_searched,
                "search_backend": "python",
                **_budget_metadata(
                    estimated_tokens=_estimate_token_count(
                        "\n".join(
                            f"{item['path']}:{item['line_number']}:{item['line']}"
                            for item in results
                        )
                    ),
                    budget_tokens=budget_tokens,
                    recommended_next_step="Use find_relevant_files or read_file on strongest match instead.",
                ),
            },
        )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
