"""Tests for mcp_peer.py - MCPPeer dataclass and registry."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import tempfile
from pathlib import Path


from claude_bridge.mcp_peer import (
    MCPPeer,
    MCPPeerRegistry,
    ToolSchema,
)


class TestToolSchema:
    def test_to_dict(self):
        schema = ToolSchema(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {}},
            risk_level="medium",
            validation_valid=True,
            validation_reason="ok",
            blocked_patterns=(),
        )
        d = schema.to_dict()
        assert d["name"] == "test_tool"
        assert d["risk_level"] == "medium"
        assert d["validation_valid"] is True

    def test_from_dict(self):
        data = {
            "name": "test_tool",
            "description": "A test tool",
            "input_schema": {"type": "object", "properties": {}},
            "risk_level": "high",
            "validation_valid": False,
            "validation_reason": "blocked pattern found",
            "blocked_patterns": ["eval("],
        }
        schema = ToolSchema.from_dict(data)
        assert schema.name == "test_tool"
        assert schema.risk_level == "high"
        assert schema.validation_valid is False
        assert "eval(" in schema.blocked_patterns

    def test_from_raw_schema(self):
        raw = {
            "name": "raw_tool",
            "description": "Raw tool description",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        }
        schema = ToolSchema.from_raw_schema(raw)
        assert schema.name == "raw_tool"
        assert schema.validation_valid is True

    def test_default_values(self):
        schema = ToolSchema(name="simple", description="Simple tool")
        assert schema.input_schema == {}
        assert schema.risk_level == "low"
        assert schema.validation_valid is True
        assert schema.blocked_patterns == ()


class TestMCPPeer:
    def setup_method(self) -> None:
        self.peer = MCPPeer(
            peer_id="test_peer_123",
            name="Test MCP",
            transport="stdio",
            endpoint="test-mcp",
            discovered_at="2026-01-01T00:00:00Z",
        )

    def test_to_dict(self):
        d = self.peer.to_dict()
        assert d["peer_id"] == "test_peer_123"
        assert d["name"] == "Test MCP"
        assert d["transport"] == "stdio"
        assert d["status"] == "active"

    def test_from_dict(self):
        data = {
            "peer_id": "peer_456",
            "name": "Another MCP",
            "transport": "http",
            "endpoint": "http://localhost:8080",
            "discovered_at": "2026-01-02T00:00:00Z",
            "last_seen": "2026-01-03T00:00:00Z",
            "status": "inactive",
            "risk_level": "medium",
            "tools": [],
        }
        peer = MCPPeer.from_dict(data)
        assert peer.peer_id == "peer_456"
        assert peer.transport == "http"
        assert peer.status == "inactive"

    def test_update_last_seen(self):
        original = self.peer.last_seen
        self.peer.update_last_seen()
        assert self.peer.last_seen >= original

    def test_mark_untrusted(self):
        self.peer.mark_untrusted()
        assert self.peer.status == "untrusted"
        assert self.peer.trust_level == "unverified"

    def test_get_active_tools(self):
        tool1 = ToolSchema(name="tool1", description="desc1", validation_valid=True)
        tool2 = ToolSchema(name="tool2", description="desc2", validation_valid=False)
        self.peer.tools = [tool1, tool2]
        active = self.peer.get_active_tools()
        assert len(active) == 1
        assert active[0].name == "tool1"

    def test_compute_peer_risk_untrusted(self):
        self.peer.status = "untrusted"
        assert self.peer.compute_peer_risk() == "high"

    def test_compute_peer_risk_high_tool(self):
        self.peer.tools = [
            ToolSchema(name="t1", description="d1", risk_level="low"),
            ToolSchema(name="t2", description="d2", risk_level="high"),
        ]
        assert self.peer.compute_peer_risk() == "high"

    def test_compute_peer_risk_medium(self):
        self.peer.tools = [
            ToolSchema(name="t1", description="d1", risk_level="low"),
            ToolSchema(name="t2", description="d2", risk_level="medium"),
        ]
        assert self.peer.compute_peer_risk() == "medium"

    def test_compute_peer_risk_low(self):
        self.peer.tools = [
            ToolSchema(name="t1", description="d1", risk_level="low"),
            ToolSchema(name="t2", description="d2", risk_level="low"),
        ]
        assert self.peer.compute_peer_risk() == "low"

    def test_to_dict_with_tools(self):
        self.peer.tools = [
            ToolSchema(name="tool1", description="desc1"),
        ]
        d = self.peer.to_dict()
        assert len(d["tools"]) == 1
        assert d["tools"][0]["name"] == "tool1"


class TestMCPPeerRegistry:
    def setup_method(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._root = Path(self._tmpdir)
        self._registry = MCPPeerRegistry(root=self._root)

    def teardown_method(self) -> None:
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_save_and_load(self):
        peer = MCPPeer(
            peer_id="save_test_peer",
            name="Save Test",
            transport="stdio",
            endpoint="save-test",
            discovered_at="2026-01-01T00:00:00Z",
        )
        success, _ = self._registry.save(peer)
        assert success is True

        loaded = self._registry.load("save_test_peer")
        assert loaded is not None
        assert loaded.peer_id == "save_test_peer"
        assert loaded.name == "Save Test"

    def test_load_nonexistent(self):
        loaded = self._registry.load("nonexistent_peer")
        assert loaded is None

    def test_load_all_empty(self):
        peers = self._registry.load_all()
        assert peers == []

    def test_load_all_multiple(self):
        for i in range(3):
            peer = MCPPeer(
                peer_id=f"peer_{i}",
                name=f"Peer {i}",
                transport="stdio",
                endpoint=f"peer-{i}",
                discovered_at="2026-01-01T00:00:00Z",
            )
            self._registry.save(peer)

        peers = self._registry.load_all()
        assert len(peers) == 3

    def test_delete_existing(self):
        peer = MCPPeer(
            peer_id="delete_test_peer",
            name="Delete Test",
            transport="stdio",
            endpoint="delete-test",
            discovered_at="2026-01-01T00:00:00Z",
        )
        self._registry.save(peer)

        success, _ = self._registry.delete("delete_test_peer")
        assert success is True

        loaded = self._registry.load("delete_test_peer")
        assert loaded is None

    def test_delete_nonexistent(self):
        success, msg = self._registry.delete("nonexistent")
        assert success is False
        assert "not found" in msg

    def test_exists_after_save(self):
        peer = MCPPeer(
            peer_id="exists_test_peer",
            name="Exists Test",
            transport="stdio",
            endpoint="exists-test",
            discovered_at="2026-01-01T00:00:00Z",
        )
        self._registry.save(peer)

        assert self._registry.exists("exists_test_peer") is True
        assert self._registry.exists("nonexistent") is False

    def test_upsert_existing(self):
        peer = MCPPeer(
            peer_id="upsert_peer",
            name="Original Name",
            transport="stdio",
            endpoint="upsert",
            discovered_at="2026-01-01T00:00:00Z",
            last_seen="2026-01-01T00:00:00Z",
        )
        self._registry.save(peer)

        updated_peer = MCPPeer(
            peer_id="upsert_peer",
            name="Updated Name",
            transport="stdio",
            endpoint="upsert",
            discovered_at="2026-01-01T00:00:00Z",
            last_seen="2026-01-02T00:00:00Z",
        )
        self._registry.upsert(updated_peer)

        loaded = self._registry.load("upsert_peer")
        assert loaded is not None
        assert loaded.name == "Updated Name"

    def test_upsert_new(self):
        peer = MCPPeer(
            peer_id="upsert_new_peer",
            name="New Peer",
            transport="stdio",
            endpoint="upsert-new",
            discovered_at="2026-01-01T00:00:00Z",
        )
        success, _ = self._registry.upsert(peer)
        assert success is True
        assert self._registry.exists("upsert_new_peer") is True

    def test_cache_works(self):
        peer = MCPPeer(
            peer_id="cached_peer",
            name="Cached",
            transport="stdio",
            endpoint="cached",
            discovered_at="2026-01-01T00:00:00Z",
        )
        self._registry.save(peer)

        first = self._registry.load("cached_peer")
        second = self._registry.load("cached_peer")
        assert first is second

    def test_path_sanitization(self):
        peer = MCPPeer(
            peer_id="peer/with/path/traversal",
            name="Test",
            transport="stdio",
            endpoint="test",
            discovered_at="2026-01-01T00:00:00Z",
        )
        success, _ = self._registry.save(peer)
        assert success is True

        loaded = self._registry.load("peer/with/path/traversal")
        assert loaded is not None

    def test_concurrent_save(self):
        import threading

        results: list[bool] = []
        errors: list[str] = []

        def save_peer(peer_id: str) -> None:
            peer = MCPPeer(
                peer_id=peer_id,
                name=f"Peer {peer_id}",
                transport="stdio",
                endpoint=peer_id,
                discovered_at="2026-01-01T00:00:00Z",
            )
            success, err = self._registry.save(peer)
            results.append(success)
            if err:
                errors.append(err)

        threads = [threading.Thread(target=save_peer, args=(f"concurrent_{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(results)
        assert len(errors) == 0
        assert self._registry.exists("concurrent_0") is True
