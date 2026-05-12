"""Agent-based toolset permission matrix for Claude Bridge."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

TOOL_PERMISSIONS: dict[str, dict[str, set[str]]] = {
    "orchestrator": {
        "allow": {
            "git",
            "file_read",
            "file_write",
            "shell",
            "network",
            "analyze",
            "audit",
            "test",
            "log_read",
            "search",
            "index",
            "execute",
            "git_write",
            "shell_destructive",
            "write",
            "delete",
            "all_mutations",
        },
        "deny": set(),
    },
    "git_agent": {
        "allow": {"git", "file_read"},
        "deny": {"shell", "network"},
    },
    "security_agent": {
        "allow": {"analyze", "audit"},
        "deny": {"write", "delete"},
    },
    "debug_agent": {
        "allow": {"test", "log_read"},
        "deny": {"git_write", "shell_destructive"},
    },
    "research_agent": {
        "allow": {"file_read", "search", "index"},
        "deny": {"write", "execute"},
    },
    "review_agent": {
        "allow": {"file_read"},
        "deny": {
            "git",
            "file_write",
            "shell",
            "network",
            "analyze",
            "audit",
            "test",
            "log_read",
            "execute",
            "git_write",
            "shell_destructive",
            "write",
            "delete",
            "all_mutations",
        },
    },
}


@dataclass
class PermissionOverride:
    """Temporary permission elevation for an agent."""

    agent: str
    allow: set[str]
    duration: int  # seconds
    expires_at: float = field(default=0.0)

    def is_active(self) -> bool:
        """Check if override is still active."""
        return time.monotonic() < self.expires_at


class PermissionMatrix:
    """Manages agent tool permissions with runtime override capability."""

    def __init__(self) -> None:
        """Initialize the permission matrix."""
        self._overrides: dict[str, PermissionOverride] = {}
        self._lock = threading.RLock()

    def can_execute(self, agent: str, tool: str) -> bool:
        """Check if agent can execute the given tool.

        Args:
            agent: The agent identifier.
            tool: The tool name to check.

        Returns:
            True if the tool is allowed for the agent, False otherwise.
        """
        with self._lock:
            override = self._overrides.get(agent)
            if override is not None and override.is_active():
                return tool in override.allow

            if agent not in TOOL_PERMISSIONS:
                return False

            perms = TOOL_PERMISSIONS[agent]
            if tool in perms["allow"]:
                return True
            if tool in perms["deny"]:
                return False
            # Tool not in allow or deny lists - default deny
            return False

    def override_permission(self, agent: str, allow: set[str], duration: int) -> None:
        """Create a temporary permission elevation for an agent.

        Args:
            agent: The agent identifier.
            allow: Set of tools to allow.
            duration: Duration in seconds for the override.
        """
        with self._lock:
            self._overrides[agent] = PermissionOverride(
                agent=agent,
                allow=allow,
                duration=duration,
                expires_at=time.monotonic() + duration,
            )

    def get_agent_tools(self, agent: str) -> set[str]:
        """Get all allowed tools for an agent.

        Args:
            agent: The agent identifier.

        Returns:
            Set of tool names the agent is allowed to execute.
        """
        with self._lock:
            override = self._overrides.get(agent)
            if override is not None and override.is_active():
                return override.allow.copy()

            if agent not in TOOL_PERMISSIONS:
                return set()

            return TOOL_PERMISSIONS[agent]["allow"].copy()

    def clear_expired_overrides(self) -> None:
        """Remove any expired permission overrides."""
        with self._lock:
            expired = [ag for ag, ov in self._overrides.items() if not ov.is_active()]
            for ag in expired:
                del self._overrides[ag]
