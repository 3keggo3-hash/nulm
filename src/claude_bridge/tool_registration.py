"""Shared tool registration helpers to reduce MCP server boilerplate."""

from __future__ import annotations

import time
from typing import Any, Callable


class ToolRegistrationContext:
    """Manages MCP tool registration with enabled-set filtering and result tracking.

    Usage::

        ctx = ToolRegistrationContext(
            mcp=mcp,
            tool_options=tool_options,
            audit_tool_call=audit_tool_call,
            enabled_names=enabled_names,
        )

        if ctx.should_register("read_file"):
            async def read_file(path: str, ...) -> str:
                started_at = time.perf_counter()
                result = await read_file_impl(path, ...)
                return audit_tool_call("read_file", {...}, result, started_at=started_at)
            ctx.register("read_file", "Read a file...", read_file, read_only=True)
    """

    def __init__(
        self,
        *,
        mcp: Any,
        tool_options: Callable[..., dict[str, Any]],
        audit_tool_call: Callable[..., str],
        enabled_names: set[str] | None = None,
    ) -> None:
        self.mcp = mcp
        self.tool_options = tool_options
        self.audit_tool_call = audit_tool_call
        self.enabled_names = enabled_names
        self.results: dict[str, Any] = {}

    def should_register(self, name: str) -> bool:
        return self.enabled_names is None or name in self.enabled_names

    def register(
        self,
        name: str,
        description: str,
        fn: Callable,
        *,
        read_only: bool = False,
        destructive: bool = False,
        open_world: bool = False,
    ) -> None:
        if not self.should_register(name):
            return
        decorated = self.mcp.tool(
            **self.tool_options(
                description,
                read_only=read_only,
                destructive=destructive,
                open_world=open_world,
            )
        )(fn)
        self.results[name] = decorated

    def add_extra(self, name: str, value: Any) -> None:
        self.results[name] = value

    def now_ms(self) -> float:
        return time.perf_counter()
