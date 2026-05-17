"""Registration helpers for indexing and relevance MCP tools."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

from typing import Any, Callable

from claude_bridge.tool_registration import ToolRegistrationContext


def register_indexing_tools(
    *,
    mcp: Any,
    tool_options: Callable[..., dict[str, Any]],
    audit_tool_call: Callable[..., str],
    json_response: Callable[..., str],
    build_index: Callable[[str], dict[str, Any]],
    path_outside_project_details: Callable[[str], dict[str, Any]],
    effective_budget_tokens: Callable[[], int],
    smart_budget_metadata: Callable[..., dict[str, Any]],
    smart_estimate_token_count: Callable[[str], int],
    enabled_names: set[str] | None = None,
) -> dict[str, Any]:
    ctx = ToolRegistrationContext(
        mcp=mcp,
        tool_options=tool_options,
        audit_tool_call=audit_tool_call,
        enabled_names=enabled_names,
    )

    if ctx.should_register("index_codebase"):

        async def index_codebase(path: str = ".", offset: int = 0, limit: int = 50) -> str:
            from claude_bridge.indexing import public_index_payload

            started_at = ctx.now_ms()
            safe_offset = max(0, offset)
            safe_limit = max(1, min(limit, 100))
            audit_params = {"path": path, "offset": safe_offset, "limit": safe_limit}
            try:
                payload = build_index(path)
            except PermissionError as exc:
                result = json_response(
                    False,
                    str(exc),
                    code="path_outside_project",
                    details=path_outside_project_details(path),
                )
                return audit_tool_call(
                    "index_codebase", audit_params, result, started_at=started_at
                )
            except FileNotFoundError:
                result = json_response(
                    False,
                    f"Directory not found: {path}",
                    code="directory_not_found",
                    details={"path": path},
                )
                return audit_tool_call(
                    "index_codebase", audit_params, result, started_at=started_at
                )
            except NotADirectoryError:
                result = json_response(
                    False,
                    f"Not a directory: {path}",
                    code="not_a_directory",
                    details={"path": path},
                )
                return audit_tool_call(
                    "index_codebase", audit_params, result, started_at=started_at
                )

            if not isinstance(payload, dict) or "files" not in payload:
                result = json_response(
                    False,
                    "Index build returned unexpected payload",
                    code="invalid_index_payload",
                    details={"path": path},
                )
                return audit_tool_call(
                    "index_codebase", audit_params, result, started_at=started_at
                )

            result = json_response(
                True,
                f"Indexed codebase: {path}",
                details=public_index_payload(payload, offset=safe_offset, limit=safe_limit),
            )
            return audit_tool_call(
                "index_codebase",
                audit_params,
                result,
                started_at=started_at,
            )

        ctx.register(
            "index_codebase",
            "Create a paginated lightweight symbol index for a codebase. Use this before "
            "relevance or architectural questions instead of reading many files blindly.",
            index_codebase,
            read_only=True,
        )

    if ctx.should_register("find_relevant_files"):

        async def find_relevant_files(
            query: str,
            path: str = ".",
            limit: int = 5,
            budget_tokens: int | None = None,
        ) -> str:
            from claude_bridge.relevance import query_terms, rank_indexed_files

            bt = budget_tokens if budget_tokens is not None else effective_budget_tokens()
            started_at = ctx.now_ms()
            audit_params = {
                "query": query,
                "path": path,
                "limit": limit,
                "budget_tokens": bt,
            }
            stripped = query.strip()
            if not stripped:
                result = json_response(
                    False,
                    "Query cannot be empty",
                    code="empty_query",
                    details={"query": query},
                )
                return audit_tool_call(
                    "find_relevant_files", audit_params, result, started_at=started_at
                )
            if limit < 1:
                result = json_response(
                    False,
                    "Limit must be at least 1",
                    code="invalid_limit",
                    details={"limit": limit},
                )
                return audit_tool_call(
                    "find_relevant_files", audit_params, result, started_at=started_at
                )

            try:
                index_payload = build_index(path)
            except PermissionError as exc:
                result = json_response(
                    False,
                    str(exc),
                    code="path_outside_project",
                    details=path_outside_project_details(path),
                )
                return audit_tool_call(
                    "find_relevant_files", audit_params, result, started_at=started_at
                )
            except FileNotFoundError:
                result = json_response(
                    False,
                    f"Directory not found: {path}",
                    code="directory_not_found",
                    details={"path": path},
                )
                return audit_tool_call(
                    "find_relevant_files", audit_params, result, started_at=started_at
                )
            except NotADirectoryError:
                result = json_response(
                    False,
                    f"Not a directory: {path}",
                    code="not_a_directory",
                    details={"path": path},
                )
                return audit_tool_call(
                    "find_relevant_files", audit_params, result, started_at=started_at
                )

            ranked = rank_indexed_files(index_payload, query=stripped, limit=limit)
            result = json_response(
                True,
                f"Relevant files found for query: {query}",
                details={
                    "query": query,
                    "terms": query_terms(stripped),
                    "results": ranked["results"],
                    "total_results": ranked["total_results"],
                    "cached": ranked.get("cached", False),
                    "strategy": ranked.get("strategy", "token_scoring"),
                    **smart_budget_metadata(
                        estimated_tokens=smart_estimate_token_count(
                            "\n".join(item["path"] for item in ranked["results"])
                        ),
                        budget_tokens=bt,
                        recommended_next_step=(
                            "Call read_file on the strongest result or use narrow_context "
                            "for a tighter budget-aware pack."
                        ),
                    ),
                },
            )
            return audit_tool_call(
                "find_relevant_files", audit_params, result, started_at=started_at
            )

        ctx.register(
            "find_relevant_files",
            "Find the most relevant files for a natural-language query using indexed "
            "scoring. Use this before reading files, and prefer specific queries over "
            "broad ones.",
            find_relevant_files,
            read_only=True,
        )

    return ctx.results
