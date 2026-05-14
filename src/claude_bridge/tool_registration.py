"""Shared tool registration helpers to reduce MCP server boilerplate."""

from __future__ import annotations

import time
from typing import Any, Callable


class ToolMetadata:
    """Metadata for a registered tool."""

    def __init__(
        self,
        name: str,
        description: str,
        version: str = "1.0.0",
        read_only: bool = False,
        destructive: bool = False,
        open_world: bool = False,
        tags: list[str] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.version = version
        self.read_only = read_only
        self.destructive = destructive
        self.open_world = open_world
        self.tags = tags or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "read_only": self.read_only,
            "destructive": self.destructive,
            "open_world": self.open_world,
            "tags": self.tags,
        }


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

    DEFAULT_VERSION = "1.0.0"

    def __init__(
        self,
        *,
        mcp: Any,
        tool_options: Callable[..., dict[str, Any]],
        audit_tool_call: Callable[..., str],
        enabled_names: set[str] | None = None,
        default_version: str = DEFAULT_VERSION,
    ) -> None:
        self.mcp = mcp
        self.tool_options = tool_options
        self.audit_tool_call = audit_tool_call
        self.enabled_names = enabled_names
        self.default_version = default_version
        self.results: dict[str, Any] = {}
        self._metadata: dict[str, ToolMetadata] = {}

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
        version: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        if not self.should_register(name):
            return
        ver = version or self.default_version
        decorated = self.mcp.tool(
            **self.tool_options(
                description,
                read_only=read_only,
                destructive=destructive,
                open_world=open_world,
            )
        )(fn)
        self.results[name] = decorated
        self._metadata[name] = ToolMetadata(
            name=name,
            description=description,
            version=ver,
            read_only=read_only,
            destructive=destructive,
            open_world=open_world,
            tags=tags,
        )

    def add_extra(self, name: str, value: Any) -> None:
        self.results[name] = value

    def get_metadata(self, name: str) -> ToolMetadata | None:
        return self._metadata.get(name)

    def get_all_metadata(self) -> dict[str, ToolMetadata]:
        return dict(self._metadata)

    def now_ms(self) -> float:
        return time.perf_counter()
