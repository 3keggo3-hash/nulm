"""Registration helpers for smart-related MCP tools."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable


def register_smart_tools(
    *,
    mcp: Any,
    tool_options: Callable[..., dict[str, Any]],
    audit_tool_call: Callable[..., str],
    resolve_path: Callable[[str], Path],
    json_response: Callable[..., str],
    count_tokens_for_path: Any,
    context_fit_check: Any,
    smart_available: Any,
    get_tool_recommendation: Any,
    estimate_context_savings: Any,
    enabled_names: set[str] | None = None,
) -> dict[str, Any]:
    _enabled = enabled_names
    results: dict[str, Any] = {}

    if _enabled is None or "count_file_tokens" in _enabled:

        @mcp.tool(**tool_options("Count approximate tokens for a file.", read_only=True))
        async def count_file_tokens(path: str) -> str:
            started_at = time.perf_counter()
            resolved = resolve_path(path)
            info = count_tokens_for_path(resolved)
            if "error" in info:
                result = json_response(False, info["error"], code="token_count_error", details=info)
            else:
                result = json_response(
                    True,
                    f"Token count for {path}: {info['tokens']} tokens ({info['lines']} lines)",
                    details=info,
                )
            return audit_tool_call(
                "count_file_tokens", {"path": path}, result, started_at=started_at
            )

        results["count_file_tokens"] = count_file_tokens

    if _enabled is None or "context_fit" in _enabled:

        @mcp.tool(**tool_options("Check if text fits within a context window.", read_only=True))
        async def context_fit(text: str, model: str = "gpt-4", context_limit: int = 200000) -> str:
            started_at = time.perf_counter()
            check = context_fit_check(text, model=model, context_limit=context_limit)
            if check["tokens"] is None:
                result = json_response(
                    False,
                    "tiktoken not available. Install with: pip install nulm[smart]",
                    code="smart_not_available",
                    details=check,
                )
            else:
                status = "fits" if check["fit"] else "does NOT fit"
                pct = check["usage_percent"]
                result = json_response(
                    True,
                    f"Text {status}: {check['tokens']}/{context_limit} tokens ({pct}%)",
                    details=check,
                )
            return audit_tool_call(
                "context_fit",
                {"text_length": len(text), "model": model, "context_limit": context_limit},
                result,
                started_at=started_at,
            )

        results["context_fit"] = context_fit

    if _enabled is None or "smart_status" in _enabled:

        @mcp.tool(
            **tool_options(
                "Check if smart features (tiktoken, charset detection) are available.",
                read_only=True,
            )
        )
        async def smart_status() -> str:
            started_at = time.perf_counter()
            available = smart_available()
            result = json_response(
                True,
                "Smart feature status",
                details={
                    "tiktoken": available["tiktoken"],
                    "charset_normalizer": available["charset_normalizer"],
                },
            )
            return audit_tool_call("smart_status", {}, result, started_at=started_at)

        results["smart_status"] = smart_status

    if _enabled is None or "tool_recommendation" in _enabled:

        @mcp.tool(
            **tool_options(
                "Get adaptive tool recommendations based on query analysis.",
                read_only=True,
            )
        )
        async def tool_recommendation(query: str, context_budget: int = 4000) -> str:
            started_at = time.perf_counter()
            available_tools = [
                "count_file_tokens",
                "context_fit",
                "smart_status",
                "batch_token_estimate",
                "compact_intent",
                "budget_metadata",
            ]
            rec = get_tool_recommendation(query, available_tools, context_budget)
            result = json_response(
                True,
                f"Tool recommendation for query: {rec['primary_tool'] or 'no recommendation'}",
                details=rec,
            )
            return audit_tool_call(
                "tool_recommendation", {"query": query}, result, started_at=started_at
            )

        results["tool_recommendation"] = tool_recommendation

    if _enabled is None or "context_savings" in _enabled:

        @mcp.tool(
            **tool_options(
                "Estimate token savings from compacting text.",
                read_only=True,
            )
        )
        async def context_savings(
            original_tokens: int, compact_tokens: int, overhead_tokens: int
        ) -> str:
            started_at = time.perf_counter()
            savings = estimate_context_savings(original_tokens, compact_tokens, overhead_tokens)
            if "error" in savings:
                result = json_response(
                    False, savings["error"], code="context_savings_error", details=savings
                )
            else:
                result = json_response(
                    True,
                    f"Context savings: {savings['savings_percent']}% "
                    f"({savings['total_savings_tokens']} tokens saved)",
                    details=savings,
                )
            return audit_tool_call(
                "context_savings",
                {"original_tokens": original_tokens, "compact_tokens": compact_tokens},
                result,
                started_at=started_at,
            )

        results["context_savings"] = context_savings

    return results
