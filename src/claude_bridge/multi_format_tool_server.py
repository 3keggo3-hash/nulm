"""Registration helpers for optional multi-format MCP tools."""

from __future__ import annotations

from typing import Any, Callable

from claude_bridge.tool_registration import ToolRegistrationContext


def register_multi_format_tools(
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

    if ctx.should_register("read_image"):

        async def read_image(path: str) -> str:
            from claude_bridge.multi_format import read_image as _read_image

            started_at = ctx.now_ms()
            result = _read_image(path)
            return audit_tool_call("read_image", {"path": path}, result, started_at=started_at)

        ctx.register(
            "read_image",
            "Read a supported image in the configured workspace. Returns MIME type, "
            "dimensions, byte size, and base64 content. Requires the optional "
            "claude-bridge[multi-format] dependency set.",
            read_image,
            read_only=True,
        )

    if ctx.should_register("read_pdf"):

        async def read_pdf(path: str, page_start: int = 1, page_end: int | None = None) -> str:
            from claude_bridge.multi_format import read_pdf as _read_pdf

            started_at = ctx.now_ms()
            result = await _read_pdf(path, page_start=page_start, page_end=page_end)
            return audit_tool_call(
                "read_pdf",
                {"path": path, "page_start": page_start, "page_end": page_end},
                result,
                started_at=started_at,
            )

        ctx.register(
            "read_pdf",
            "Extract text from a PDF in the configured workspace with page pagination. "
            "Requires the optional claude-bridge[multi-format] dependency set.",
            read_pdf,
            read_only=True,
        )

    return ctx.results
