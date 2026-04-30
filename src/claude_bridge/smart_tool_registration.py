"""Registration helpers for smart-related MCP tools."""

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
) -> dict[str, Any]:
    @mcp.tool(
        **tool_options(
            "Count the approximate token count for a file. Use this to check if a file or set of files fits in the context window before reading them.",
            read_only=True,
        )
    )
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
        return audit_tool_call("count_file_tokens", {"path": path}, result, started_at=started_at)

    @mcp.tool(
        **tool_options(
            "Check if text fits within a model's context window. Provide text and get token usage with fit/overflow status.",
            read_only=True,
        )
    )
    async def context_fit(text: str, model: str = "gpt-4", context_limit: int = 200000) -> str:
        started_at = time.perf_counter()
        check = context_fit_check(text, model=model, context_limit=context_limit)
        if check["tokens"] is None:
            result = json_response(
                False,
                "tiktoken not available. Install with: pip install claude-bridge[smart]",
                code="smart_not_available",
                details=check,
            )
        else:
            status = "fits" if check["fit"] else "does NOT fit"
            result = json_response(
                True,
                f"Text {status}: {check['tokens']}/{context_limit} tokens ({check['usage_percent']}%)",
                details=check,
            )
        return audit_tool_call(
            "context_fit",
            {"text_length": len(text), "model": model, "context_limit": context_limit},
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Check if smart features (tiktoken, charset detection) are available in this Claude Bridge installation.",
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
                "install_hint": "pip install claude-bridge[smart]"
                if not all(available.values())
                else "All smart features active",
            },
        )
        return audit_tool_call("smart_status", {}, result, started_at=started_at)

    return {
        "count_file_tokens": count_file_tokens,
        "context_fit": context_fit,
        "smart_status": smart_status,
    }
