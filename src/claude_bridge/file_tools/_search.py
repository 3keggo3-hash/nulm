"""Search-oriented file tools."""

from __future__ import annotations

import concurrent.futures
import re
import time as _time
from typing import Any

from claude_bridge.tool_utils import (
    infer_project_root,
    is_within_root,
    json_response,
    path_outside_project_details,
    resolve_path,
    safe_read_text,
    sensitive_path_reason,
)

from claude_bridge.file_tools._helpers import (
    _MAX_SEARCH_RESULTS,
    _run_ripgrep_search,
)

DEFAULT_CONTEXT_BUDGET_TOKENS = 4000


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
                    recommended_next_step="Use find_relevant_files or read_file on the strongest match instead of broad follow-up reads.",
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
                    recommended_next_step="Use find_relevant_files or read_file on the strongest match instead of broad follow-up reads.",
                ),
            },
        )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
