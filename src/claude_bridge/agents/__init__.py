"""Agent system for multi-agent orchestration."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from claude_bridge.agents.result import AgentResult
from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.shared_memory import SharedMemorySpace
from claude_bridge.agents.dispatcher import TaskDispatcher
from claude_bridge.agents.orchestrator import OrchestratorAgent

__all__ = [
    "AgentResult",
    "BaseAgent",
    "SharedMemorySpace",
    "TaskDispatcher",
    "OrchestratorAgent",
]
