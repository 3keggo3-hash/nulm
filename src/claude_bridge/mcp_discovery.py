"""MCP Discovery Engine for observing nearby MCP-like processes.

Discovery is intentionally observational: it records peer metadata and filters
already-known tool schemas, but it does not execute peer commands to probe them.
"""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    import psutil  # type: ignore[import-untyped]

    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


from claude_bridge.mcp_peer import MCPPeer, MCPPeerRegistry, ToolSchema
from claude_bridge.tool_validator import ToolSchemaValidator

DISCOVERY_INTERVAL_SECONDS = 300


_MCP_PROCESS_PATTERNS = [
    "mcp",
    "nulm",
    "claude-bridge",
    "claude-code",
]


def _is_mcp_process_name(name: str) -> bool:
    name_lower = name.lower()
    return any(pattern in name_lower for pattern in _MCP_PROCESS_PATTERNS)


def _get_running_mcp_processes() -> list[dict[str, str]]:
    if not _HAS_PSUTIL:
        return []

    processes: list[dict[str, str]] = []
    my_pid = os.getpid()

    try:
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if proc.pid == my_pid:
                    continue

                info = proc.info
                name = info.get("name", "")

                if not _is_mcp_process_name(name):
                    continue

                cmdline = info.get("cmdline") or []
                cmdline_str = " ".join(cmdline) if cmdline else ""

                processes.append(
                    {
                        "pid": str(proc.pid),
                        "name": name,
                        "cmdline": cmdline_str,
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass

    return processes


def _get_stdio_endpoint_from_cmdline(cmdline: str) -> str | None:
    if not cmdline:
        return None

    if "stdio" in cmdline.lower():
        parts = cmdline.split()
        for i, part in enumerate(parts):
            if part in ("-stdio", "--stdio", "stdio"):
                if i + 1 < len(parts) and not parts[i + 1].startswith("-"):
                    return parts[i + 1]
        return "stdio"

    return None


class MCPDiscovery:
    _lock = asyncio.Lock()

    def __init__(
        self,
        root: Path | None = None,
        validator: ToolSchemaValidator | None = None,
        interval_seconds: int = DISCOVERY_INTERVAL_SECONDS,
    ) -> None:
        self._root = (root or Path.cwd()).resolve()
        self._registry = MCPPeerRegistry(root=self._root)
        self._validator = validator or ToolSchemaValidator()
        self._interval = interval_seconds
        self._running = False
        self._task: asyncio.Task | None = None

    async def discover_stdio_mcps(self) -> list[MCPPeer]:
        loop = asyncio.get_event_loop()
        processes = await loop.run_in_executor(None, _get_running_mcp_processes)

        peers: list[MCPPeer] = []
        for proc_info in processes:
            endpoint = _get_stdio_endpoint_from_cmdline(proc_info["cmdline"]) or proc_info["name"]

            peer_id = f"stdio_{proc_info['pid']}_{endpoint}"

            if self._registry.exists(peer_id):
                continue

            peer = MCPPeer(
                peer_id=peer_id,
                name=proc_info["name"],
                transport="stdio",
                endpoint=endpoint,
                discovered_at=datetime.now(timezone.utc).isoformat(),
                status="active",
            )
            peers.append(peer)

        return peers

    async def probe_mcp_capabilities(self, peer: MCPPeer) -> list[ToolSchema]:
        """Filter schemas that were already attached to a discovered peer.

        This method deliberately avoids launching peer processes or package-manager
        commands. Active capability probing needs an explicit transport adapter and
        approval model; until then, discovery remains metadata-only.
        """
        validated_tools: list[ToolSchema] = []
        for tool in peer.tools:
            raw_schema = {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            }
            validation = self._validator.validate(raw_schema)
            if not validation.valid or validation.risk_level == "high":
                continue
            validated_tools.append(ToolSchema.from_raw_schema(raw_schema, validation))
        return validated_tools

    async def observe_peer(self, peer: MCPPeer) -> MCPPeer:
        async with self._lock:
            existing = self._registry.load(peer.peer_id)

            if existing:
                existing.update_last_seen()
                existing.last_seen = datetime.now(timezone.utc).isoformat()

                existing.tools = await self.probe_mcp_capabilities(existing)

                self._registry.save(existing)
                return existing

            peer.tools = await self.probe_mcp_capabilities(peer)

            self._registry.save(peer)
            return peer

    async def run_discovery_loop(self) -> None:
        self._running = True

        while self._running:
            try:
                peers = await self.discover_stdio_mcps()

                for peer in peers:
                    await self.observe_peer(peer)

            except Exception:
                pass

            await asyncio.sleep(self._interval)

    def start_discovery_loop(self) -> None:
        if self._task is not None and not self._task.done():
            return

        self._running = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._task = None
            return

        self._task = loop.create_task(self.run_discovery_loop())

    def stop_discovery_loop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def get_observed_tools(self) -> list[ToolSchema]:
        all_tools: list[ToolSchema] = []

        for peer in self._registry.load_all():
            if peer.status == "untrusted":
                continue

            for tool in peer.tools:
                if tool.validation_valid and tool.risk_level != "high":
                    all_tools.append(tool)

        return all_tools

    def get_peer_tools(self, peer_id: str) -> list[ToolSchema] | None:
        peer = self._registry.load(peer_id)
        if peer is None:
            return None
        return peer.get_active_tools()

    def get_all_peers(self) -> list[MCPPeer]:
        return self._registry.load_all()

    def get_active_peers(self) -> list[MCPPeer]:
        return [p for p in self._registry.load_all() if p.status == "active"]

    async def refresh_peer(self, peer_id: str) -> MCPPeer | None:
        peer = self._registry.load(peer_id)
        if peer is None:
            return None

        return await self.observe_peer(peer)
