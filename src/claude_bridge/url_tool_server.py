"""Registration helpers for URL-oriented MCP tools."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

from typing import Any, Callable

from claude_bridge.tool_utils import json_response
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

    if ctx.should_register("validate_url"):

        def validate_url(url: str) -> str:
            from claude_bridge.url_tools import validate_url as _validate_url

            return _validate_url(url)

        ctx.register(
            "validate_url",
            "Validate a URL without fetching it. Checks scheme, hostname syntax, "
            "SSRF protections, path traversal, and internationalized domain names. "
            "Returns validation result with details.",
            validate_url,
            read_only=True,
        )

    if ctx.should_register("extract_url_parts"):

        def extract_url_parts(url: str) -> str:
            from claude_bridge.url_tools import extract_url_parts as _extract_url_parts

            return json_response(
                True,
                "URL parts extracted",
                details=_extract_url_parts(url),
            )

        ctx.register(
            "extract_url_parts",
            "Extract components from a URL (scheme, host, port, path, query, fragment). "
            "Returns structured URL part information.",
            extract_url_parts,
            read_only=True,
        )

    if ctx.should_register("normalize_url"):

        def normalize_url(url: str) -> str:
            from claude_bridge.url_tools import normalize_url as _normalize_url

            return json_response(
                True,
                "URL normalized",
                details={"normalized_url": _normalize_url(url)},
            )

        ctx.register(
            "normalize_url",
            "Normalize a URL by removing fragments, stripping trailing slashes, "
            "and standardizing port representation. Returns the normalized URL.",
            normalize_url,
            read_only=True,
        )

    return ctx.results
