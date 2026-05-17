"""Shared memory space for inter-agent communication."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import threading
from typing import Any


class SharedMemorySpace:
    """Thread-safe shared memory for inter-agent communication."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._agent_views: dict[str, dict[str, Any]] = {}

    def write(self, key: str, value: Any) -> None:
        """Write a value to the shared memory.

        Args:
            key: The key to write to.
            value: The value to store.
        """
        with self._lock:
            self._data[key] = value

    def read(self, key: str) -> Any | None:
        """Read a value from the shared memory.

        Args:
            key: The key to read.

        Returns:
            The stored value or None if not found.
        """
        with self._lock:
            return self._data.get(key)

    def get_agent_view(self, agent: str) -> dict[str, Any]:
        """Get a view of shared memory from a specific agent's perspective.

        Args:
            agent: The agent name requesting the view.

        Returns:
            Dictionary containing data visible to the agent.
        """
        with self._lock:
            return dict(self._data)

    def update_agent_view(self, agent: str, data: dict[str, Any]) -> None:
        """Update the agent's view in shared memory.

        Args:
            agent: The agent name.
            data: Data to add to the agent's view.
        """
        with self._lock:
            if agent not in self._agent_views:
                self._agent_views[agent] = {}
            self._agent_views[agent].update(data)

    def get_all_keys(self) -> list[str]:
        """Get all keys in shared memory.

        Returns:
            List of all keys.
        """
        with self._lock:
            return list(self._data.keys())

    def clear(self) -> None:
        """Clear all shared memory."""
        with self._lock:
            self._data.clear()
            self._agent_views.clear()
