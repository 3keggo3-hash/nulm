"""Sub-agents for specialized tasks."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from claude_bridge.agents.sub.git_agent import GitAgent
from claude_bridge.agents.sub.security_agent import SecurityAgent
from claude_bridge.agents.sub.debug_agent import DebugAgent
from claude_bridge.agents.sub.research_agent import ResearchAgent
from claude_bridge.agents.sub.review_agent import ReviewAgent
from claude_bridge.agents.sub.verification_agent import VerificationAgent

__all__ = [
    "GitAgent",
    "SecurityAgent",
    "DebugAgent",
    "ResearchAgent",
    "ReviewAgent",
    "VerificationAgent",
]
