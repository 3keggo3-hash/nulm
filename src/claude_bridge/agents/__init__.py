"""Agent system for multi-agent orchestration."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from claude_bridge.agents.result import AgentResult
from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.contracts import (
    AgentArtifact,
    EvidenceRef,
    TaskBudget,
    TaskPermissions,
    TaskSpec,
)
from claude_bridge.agents.shared_memory import SharedMemorySpace
from claude_bridge.agents.mission_brief import ContextCurator, MissionBrief
from claude_bridge.agents.dag_scheduler import AgentDagScheduler, AgentDagSchedulerResult
from claude_bridge.agents.dispatcher import TaskDispatcher
from claude_bridge.agents.verifier import DeterministicVerifier, VerifierInput, VerifierOutput
from claude_bridge.agents.conflict_detector import ConflictDetector, PatchHunk
from claude_bridge.agents.adjudicator import AdjudicationResult, DeterministicAdjudicator
from claude_bridge.agents.enforcement import EnforcementDecision, EnforcementPolicy
from claude_bridge.agents.orchestrator import OrchestratorAgent

__all__ = [
    "AgentResult",
    "AgentArtifact",
    "BaseAgent",
    "EvidenceRef",
    "ContextCurator",
    "MissionBrief",
    "AgentDagScheduler",
    "AgentDagSchedulerResult",
    "AdjudicationResult",
    "ConflictDetector",
    "DeterministicVerifier",
    "DeterministicAdjudicator",
    "EnforcementDecision",
    "EnforcementPolicy",
    "PatchHunk",
    "VerifierInput",
    "VerifierOutput",
    "SharedMemorySpace",
    "TaskBudget",
    "TaskDispatcher",
    "TaskPermissions",
    "TaskSpec",
    "OrchestratorAgent",
]
