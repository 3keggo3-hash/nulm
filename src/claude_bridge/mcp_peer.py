"""MCP Peer dataclass and storage for discovered MCP servers.

Provides structured representation of discovered MCP peers with their
capabilities, security status, and metadata for the discovery system.
"""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PEERS_DIR = Path(".claude-bridge/mcp_peers")


@dataclass(frozen=True)
class ToolSchema:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    risk_level: str = "low"
    validation_valid: bool = True
    validation_reason: str = "ok"
    blocked_patterns: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "risk_level": self.risk_level,
            "validation_valid": self.validation_valid,
            "validation_reason": self.validation_reason,
            "blocked_patterns": list(self.blocked_patterns),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolSchema:
        return cls(
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            input_schema=dict(data.get("input_schema", {})),
            risk_level=str(data.get("risk_level", "low")),
            validation_valid=bool(data.get("validation_valid", True)),
            validation_reason=str(data.get("validation_reason", "ok")),
            blocked_patterns=tuple(data.get("blocked_patterns", [])),
        )

    @classmethod
    def from_raw_schema(cls, raw: dict[str, Any], validation_result: Any = None) -> ToolSchema:
        name = str(raw.get("name", ""))
        description = str(raw.get("description", ""))
        schema = raw.get("inputSchema") or raw.get("parameters", {})
        if isinstance(schema, dict):
            input_schema = schema
        else:
            input_schema = {}

        risk_level = "low"
        if validation_result and hasattr(validation_result, "risk_level"):
            risk_level = validation_result.risk_level

        return cls(
            name=name,
            description=description,
            input_schema=input_schema,
            risk_level=risk_level,
            validation_valid=validation_result.valid if validation_result else True,
            validation_reason=validation_result.reason if validation_result else "ok",
            blocked_patterns=validation_result.blocked_patterns if validation_result else (),
        )


@dataclass
class MCPPeer:
    peer_id: str
    name: str
    transport: str
    endpoint: str
    discovered_at: str
    tools: list[ToolSchema] = field(default_factory=list)
    risk_level: str = "low"
    last_seen: str = ""
    status: str = "active"
    signature: str = ""
    trust_level: str = "unverified"

    def __post_init__(self) -> None:
        if not self.last_seen:
            self.last_seen = self.discovered_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "peer_id": self.peer_id,
            "name": self.name,
            "transport": self.transport,
            "endpoint": self.endpoint,
            "discovered_at": self.discovered_at,
            "tools": [t.to_dict() if isinstance(t, ToolSchema) else t for t in self.tools],
            "risk_level": self.risk_level,
            "last_seen": self.last_seen,
            "status": self.status,
            "signature": self.signature,
            "trust_level": self.trust_level,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MCPPeer:
        tools = []
        for t in data.get("tools", []):
            if isinstance(t, dict):
                tools.append(ToolSchema.from_dict(t))
            else:
                tools.append(t)

        return cls(
            peer_id=str(data.get("peer_id", "")),
            name=str(data.get("name", "")),
            transport=str(data.get("transport", "stdio")),
            endpoint=str(data.get("endpoint", "")),
            discovered_at=str(data.get("discovered_at", "")),
            tools=tools,
            risk_level=str(data.get("risk_level", "low")),
            last_seen=str(data.get("last_seen", "")),
            status=str(data.get("status", "active")),
            signature=str(data.get("signature", "")),
            trust_level=str(data.get("trust_level", "unverified")),
        )

    def update_last_seen(self) -> None:
        self.last_seen = datetime.now(timezone.utc).isoformat()

    def mark_untrusted(self) -> None:
        self.status = "untrusted"
        self.trust_level = "unverified"

    def get_active_tools(self) -> list[ToolSchema]:
        return [t for t in self.tools if t.validation_valid]

    def compute_peer_risk(self) -> str:
        if self.status == "untrusted":
            return "high"
        tool_risks = [t.risk_level for t in self.tools]
        if "high" in tool_risks:
            return "high"
        if "medium" in tool_risks:
            return "medium"
        return "low"


class MCPPeerRegistry:
    _lock = threading.Lock()

    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or Path.cwd()).resolve()
        self._peers_dir = self._root / PEERS_DIR
        self._cache: dict[str, MCPPeer] = {}

    def _peer_path(self, peer_id: str) -> Path:
        safe_name = peer_id.replace("/", "_").replace("..", "_")
        return self._peers_dir / f"{safe_name}.json"

    def save(self, peer: MCPPeer) -> tuple[bool, str]:
        with self._lock:
            try:
                self._peers_dir.mkdir(parents=True, exist_ok=True)
                path = self._peer_path(peer.peer_id)
                data = peer.to_dict()
                with path.open("w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                self._cache[peer.peer_id] = peer
                return True, ""
            except OSError as e:
                return False, str(e)

    def load(self, peer_id: str) -> MCPPeer | None:
        if peer_id in self._cache:
            return self._cache[peer_id]

        with self._lock:
            path = self._peer_path(peer_id)
            if not path.exists():
                return None

            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                peer = MCPPeer.from_dict(data)
                self._cache[peer_id] = peer
                return peer
            except (OSError, json.JSONDecodeError):
                return None

    def load_all(self) -> list[MCPPeer]:
        with self._lock:
            self._peers_dir.mkdir(parents=True, exist_ok=True)
            peers: list[MCPPeer] = []

            for path in self._peers_dir.glob("*.json"):
                try:
                    with path.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                    peer = MCPPeer.from_dict(data)
                    self._cache[peer.peer_id] = peer
                    peers.append(peer)
                except (OSError, json.JSONDecodeError):
                    continue

            return peers

    def delete(self, peer_id: str) -> tuple[bool, str]:
        with self._lock:
            path = self._peer_path(peer_id)
            if not path.exists():
                return False, "not found"

            try:
                path.unlink()
                self._cache.pop(peer_id, None)
                return True, ""
            except OSError as e:
                return False, str(e)

    def exists(self, peer_id: str) -> bool:
        if peer_id in self._cache:
            return True
        return self._peer_path(peer_id).exists()

    def upsert(self, peer: MCPPeer) -> tuple[bool, str]:
        existing = self.load(peer.peer_id)
        if existing:
            peer.last_seen = datetime.now(timezone.utc).isoformat()
        return self.save(peer)
