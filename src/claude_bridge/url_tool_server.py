"""Registration helpers for URL-oriented MCP tools."""

from __future__ import annotations

from typing import Any, Callable

from claude_bridge.tool_registration import ToolRegistrationContext


def register_url_tools(
    *,
    mcp: Any,
    tool_options: Callable[..., dict[str, Any]],
    audit_tool_call: Callable[..., str],
    enabled_names: set[str] | None = None,
) -> dict[str, Any]:
    ctx = ToolRegistrationContext(
        mcp=mcp,
        tool_options=tool_options,
        audit_tool_call=audit_tool_call,
        enabled_names=enabled_names,
    )

    if ctx.should_register("read_url"):

        async def read_url(url: str) -> str:
            from claude_bridge.url_tools import _url_hash, read_url as _read_url

            started_at = ctx.now_ms()
            result = await _read_url(url)
            return audit_tool_call(
                "read_url",
                {"url_hash": _url_hash(url)},
                result,
                started_at=started_at,
            )

        ctx.register(
            "read_url",
            "Read content from an http/https URL. Only text/* content-types are allowed. "
            "Response is truncated to 100KB and the URL is stored as a sha256 hash in "
            "audit logs (the URL itself is never logged). Max 1MB response, 10s timeout, "
            "5 redirects.",
            read_url,
            read_only=True,
        )

    return ctx.results
