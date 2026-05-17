"""Tests for mcp_discovery.py - MCP Discovery Engine."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch


from claude_bridge.mcp_discovery import (
    MCPDiscovery,
    _is_mcp_process_name,
    _get_stdio_endpoint_from_cmdline,
    DISCOVERY_INTERVAL_SECONDS,
)
from claude_bridge.mcp_peer import MCPPeer, ToolSchema


class TestIsMcpProcessName:
    def test_mcp_in_name(self):
        assert _is_mcp_process_name("mcp-server") is True
        assert _is_mcp_process_name("my-mcp-tool") is True

    def test_nulm_in_name(self):
        assert _is_mcp_process_name("nulm") is True

    def test_claude_bridge_in_name(self):
        assert _is_mcp_process_name("claude-bridge") is True

    def test_claude_code_in_name(self):
        assert _is_mcp_process_name("claude-code") is True

    def test_unrelated_name(self):
        assert _is_mcp_process_name("python") is False
        assert _is_mcp_process_name("node") is False
        assert _is_mcp_process_name("docker") is False


class TestGetStdioEndpoint:
    def test_stdio_flag(self):
        result = _get_stdio_endpoint_from_cmdline("mcp-server -stdio")
        assert result == "stdio"

    def test_stdio_double_flag(self):
        result = _get_stdio_endpoint_from_cmdline("mcp-server --stdio")
        assert result == "stdio"

    def test_stdio_with_value(self):
        result = _get_stdio_endpoint_from_cmdline("mcp-server -stdio my-endpoint")
        assert result == "my-endpoint"

    def test_empty_cmdline(self):
        result = _get_stdio_endpoint_from_cmdline("")
        assert result is None

    def test_no_stdio(self):
        result = _get_stdio_endpoint_from_cmdline("mcp-server --http 8080")
        assert result is None


class TestMCPDiscovery:
    def setup_method(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._root = Path(self._tmpdir)
        self._discovery = MCPDiscovery(root=self._root)

    def teardown_method(self) -> None:
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_init_with_defaults(self):
        discovery = MCPDiscovery()
        assert discovery._interval == DISCOVERY_INTERVAL_SECONDS
        assert discovery._running is False

    def test_init_custom_validator(self):
        from claude_bridge.tool_validator import ToolSchemaValidator

        validator = ToolSchemaValidator(max_param_count=5)
        discovery = MCPDiscovery(validator=validator)
        assert discovery._validator.max_param_count == 5

    def test_get_observed_tools_empty(self):
        tools = self._discovery.get_observed_tools()
        assert tools == []

    def test_get_all_peers_empty(self):
        peers = self._discovery.get_all_peers()
        assert peers == []

    def test_get_active_peers_empty(self):
        peers = self._discovery.get_active_peers()
        assert peers == []

    def test_get_peer_tools_nonexistent(self):
        tools = self._discovery.get_peer_tools("nonexistent")
        assert tools is None

    @patch("claude_bridge.mcp_discovery._get_running_mcp_processes")
    async def test_discover_stdio_mcps_no_processes(self, mock_processes):
        mock_processes.return_value = []
        peers = await self._discovery.discover_stdio_mcps()
        assert peers == []

    @patch("claude_bridge.mcp_discovery._get_running_mcp_processes")
    async def test_discover_stdio_mcps_with_processes(self, mock_processes):
        mock_processes.return_value = [
            {"pid": "12345", "name": "mcp-server", "cmdline": "mcp-server -stdio"},
        ]
        peers = await self._discovery.discover_stdio_mcps()
        assert len(peers) == 1
        assert peers[0].name == "mcp-server"
        assert peers[0].transport == "stdio"

    @patch("claude_bridge.mcp_discovery._get_running_mcp_processes")
    async def test_discover_stdio_mcps_skips_existing(self, mock_processes):
        mock_processes.return_value = [
            {"pid": "12345", "name": "mcp-server", "cmdline": "mcp-server -stdio"},
        ]

        existing_peer = MCPPeer(
            peer_id="stdio_12345_stdio",
            name="mcp-server",
            transport="stdio",
            endpoint="stdio",
            discovered_at="2026-01-01T00:00:00Z",
        )
        self._discovery._registry.save(existing_peer)

        peers = await self._discovery.discover_stdio_mcps()
        assert len(peers) == 0

    async def test_probe_mcp_capabilities_filters_attached_tools(self):
        peer = MCPPeer(
            peer_id="test_peer",
            name="Test MCP",
            transport="stdio",
            endpoint="test",
            discovered_at="2026-01-01T00:00:00Z",
            tools=[
                ToolSchema(
                    name="test_tool",
                    description="A test tool",
                    input_schema={"type": "object", "properties": {}},
                )
            ],
        )

        tools = await self._discovery.probe_mcp_capabilities(peer)
        assert len(tools) == 1
        assert tools[0].name == "test_tool"

    async def test_probe_mcp_capabilities_invalid_tool_blocked(self):
        peer = MCPPeer(
            peer_id="test_peer",
            name="Test MCP",
            transport="stdio",
            endpoint="test",
            discovered_at="2026-01-01T00:00:00Z",
            tools=[
                ToolSchema(
                    name="exec_tool",
                    description="Execute eval() code",
                    input_schema={"type": "object", "properties": {}},
                )
            ],
        )

        tools = await self._discovery.probe_mcp_capabilities(peer)
        assert len(tools) == 0

    async def test_probe_mcp_capabilities_does_not_actively_probe_http_transport(self):
        peer = MCPPeer(
            peer_id="test_peer",
            name="Test MCP",
            transport="http",
            endpoint="http://localhost:8080",
            discovered_at="2026-01-01T00:00:00Z",
        )

        tools = await self._discovery.probe_mcp_capabilities(peer)
        assert len(tools) == 0

    async def test_observe_peer_new_metadata_only(self):
        peer = MCPPeer(
            peer_id="observe_test_peer",
            name="Observe Test",
            transport="stdio",
            endpoint="observe-test",
            discovered_at="2026-01-01T00:00:00Z",
        )

        observed = await self._discovery.observe_peer(peer)
        assert observed.peer_id == "observe_test_peer"
        assert self._discovery._registry.exists("observe_test_peer") is True
        assert observed.status == "active"

    async def test_observe_peer_filters_existing_tools(self):
        peer = MCPPeer(
            peer_id="update_tools_peer",
            name="Update Tools",
            transport="stdio",
            endpoint="update-tools",
            discovered_at="2026-01-01T00:00:00Z",
            status="active",
            tools=[
                ToolSchema(
                    name="new_tool",
                    description="A new tool",
                    input_schema={"type": "object", "properties": {}},
                ),
                ToolSchema(
                    name="run_shell",
                    description="Execute shell command",
                    input_schema={"type": "object", "properties": {}},
                ),
            ],
        )

        self._discovery._registry.save(peer)

        observed = await self._discovery.observe_peer(peer)
        assert len(observed.tools) == 1
        assert observed.tools[0].name == "new_tool"

    def test_start_stop_discovery_loop(self):
        self._discovery.start_discovery_loop()
        assert self._discovery._running is True

        self._discovery.stop_discovery_loop()
        assert self._discovery._running is False

    async def test_concurrent_observe_peer_same_id(self):
        peer = MCPPeer(
            peer_id="concurrent_test_peer",
            name="Concurrent Test",
            transport="stdio",
            endpoint="concurrent-test",
            discovered_at="2026-01-01T00:00:00Z",
        )

        await self._discovery.observe_peer(peer)
        await self._discovery.observe_peer(peer)
        await self._discovery.observe_peer(peer)

        peers = self._discovery.get_all_peers()
        assert len(peers) == 1
        assert peers[0].peer_id == "concurrent_test_peer"

    async def test_refresh_peer_nonexistent(self):
        result = await self._discovery.refresh_peer("nonexistent")
        assert result is None

    async def test_refresh_peer_existing(self):
        peer = MCPPeer(
            peer_id="refresh_test_peer",
            name="Refresh Test",
            transport="stdio",
            endpoint="refresh-test",
            discovered_at="2026-01-01T00:00:00Z",
            status="active",
        )
        self._discovery._registry.save(peer)

        result = await self._discovery.refresh_peer("refresh_test_peer")
        assert result is not None
        assert result.peer_id == "refresh_test_peer"

    def test_get_all_peers_multiple(self):
        for i in range(3):
            peer = MCPPeer(
                peer_id=f"peer_{i}",
                name=f"Peer {i}",
                transport="stdio",
                endpoint=f"peer-{i}",
                discovered_at="2026-01-01T00:00:00Z",
            )
            self._discovery._registry.save(peer)

        peers = self._discovery.get_all_peers()
        assert len(peers) == 3

    def test_get_active_peers_filters_inactive(self):
        active_peer = MCPPeer(
            peer_id="active_peer",
            name="Active",
            transport="stdio",
            endpoint="active",
            discovered_at="2026-01-01T00:00:00Z",
            status="active",
        )
        inactive_peer = MCPPeer(
            peer_id="inactive_peer",
            name="Inactive",
            transport="stdio",
            endpoint="inactive",
            discovered_at="2026-01-01T00:00:00Z",
            status="inactive",
        )

        self._discovery._registry.save(active_peer)
        self._discovery._registry.save(inactive_peer)

        active = self._discovery.get_active_peers()
        assert len(active) == 1
        assert active[0].peer_id == "active_peer"
