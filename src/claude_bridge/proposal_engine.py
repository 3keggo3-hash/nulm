"""Proposal engine for memory-based recommendation candidates.

Provides task outcome analysis and alternative discovery. It does not fabricate
statistical recommendation proposals from heuristics; proposals require real
comparison evidence from the skill-comparison layer.
"""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_bridge.adaptive_council import ProposalStore
from claude_bridge.mcp_discovery import MCPDiscovery
from claude_bridge.memory import MemoryStore, get_memory_store

TRIGGER_ON_FAILURE = True
TRIGGER_ON_SLOW_COMPLETION = True
TRIGGER_ON_USER_REQUEST = True
TRIGGER_ON_EVERY_TASK = False

MAX_PROPOSALS_PER_SESSION = 3

DEFAULT_SLOW_THRESHOLD_MULTIPLIER = 2.0


@dataclass(frozen=True)
class TaskResult:
    task_type: str
    skill_used: str | None
    success: bool
    duration_ms: float
    error_type: str | None = None
    user_requested_suggestion: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "skill_used": self.skill_used,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "error_type": self.error_type,
            "user_requested_suggestion": self.user_requested_suggestion,
        }


@dataclass(frozen=True)
class OutcomeAnalysis:
    task_type: str
    skill_used: str | None
    success: bool
    duration_ms: float
    error_type: str | None


@dataclass(frozen=True)
class Alternative:
    name: str
    source: str
    acceptance_rate: float
    role: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "acceptance_rate": round(self.acceptance_rate, 3),
            "role": self.role,
        }


class ProposalEngine:
    MAX_PROPOSALS_PER_SESSION: int = MAX_PROPOSALS_PER_SESSION

    def __init__(
        self,
        memory_store: MemoryStore | None = None,
        mcp_discovery: MCPDiscovery | None = None,
        proposal_store: ProposalStore | None = None,
        max_proposals_per_session: int = MAX_PROPOSALS_PER_SESSION,
        slow_threshold_multiplier: float = DEFAULT_SLOW_THRESHOLD_MULTIPLIER,
    ) -> None:
        self._memory = memory_store or get_memory_store()
        self._discovery = mcp_discovery
        self._proposals = proposal_store or ProposalStore()
        self._session_proposal_count = 0
        self._historical_averages: dict[str, list[float]] = {}
        self._max_per_session = max_proposals_per_session
        self._slow_threshold = slow_threshold_multiplier

    def should_trigger(self, task_result: TaskResult) -> bool:
        if self._session_proposal_count >= self._max_per_session:
            return False

        if task_result.user_requested_suggestion and TRIGGER_ON_USER_REQUEST:
            return True

        if not task_result.success and TRIGGER_ON_FAILURE:
            return True

        if TRIGGER_ON_SLOW_COMPLETION:
            avg = self._get_historical_average(task_result.task_type)
            if avg > 0 and task_result.duration_ms > avg * self._slow_threshold:
                return True

        return False

    def _get_historical_average(self, task_type: str) -> float:
        durations = self._historical_averages.get(task_type, [])
        if not durations:
            return 0.0
        return sum(durations) / len(durations)

    def _update_historical(self, task_type: str, duration_ms: float) -> None:
        if task_type not in self._historical_averages:
            self._historical_averages[task_type] = []
        self._historical_averages[task_type].append(duration_ms)
        if len(self._historical_averages[task_type]) > 10:
            self._historical_averages[task_type] = self._historical_averages[task_type][-10:]

    def analyze_outcome(self, task_result: TaskResult) -> OutcomeAnalysis:
        return OutcomeAnalysis(
            task_type=task_result.task_type,
            skill_used=task_result.skill_used,
            success=task_result.success,
            duration_ms=task_result.duration_ms,
            error_type=task_result.error_type,
        )

    def find_best_alternative(self, analysis: OutcomeAnalysis) -> Alternative | None:
        alternatives: list[Alternative] = []

        lessons = self._memory.search_lessons(analysis.task_type)
        for lesson in lessons[:5]:
            if lesson.hits > 0:
                rate = min(lesson.hits / 100.0, 1.0)
                alternatives.append(
                    Alternative(
                        name=lesson.pattern,
                        source="memory",
                        acceptance_rate=rate,
                    )
                )

        if self._discovery:
            tools = self._discovery.get_observed_tools()
            for tool in tools:
                if self._matches_task_type(tool.name, analysis.task_type):
                    risk = 0.5 if tool.risk_level == "low" else 0.7
                    alternatives.append(
                        Alternative(
                            name=tool.name,
                            source="mcp_peer",
                            acceptance_rate=risk,
                            role="observer",
                        )
                    )

        if not alternatives:
            return None

        alternatives.sort(key=lambda a: a.acceptance_rate, reverse=True)
        return alternatives[0]

    def _matches_task_type(self, tool_name: str, task_type: str) -> bool:
        name_lower = tool_name.lower()
        type_lower = task_type.lower()
        return any(
            word in name_lower or word in type_lower for word in ["git", "shell", "file", "search"]
        )

    async def record_and_propose(self, task_result: TaskResult) -> None:
        self._update_historical(task_result.task_type, task_result.duration_ms)

        self._memory.add_lesson(
            pattern=task_result.task_type,
            solution=task_result.skill_used or "",
            project="",
        )

        if not self.should_trigger(task_result):
            return

        analysis = self.analyze_outcome(task_result)
        alternative = self.find_best_alternative(analysis)

        if alternative is None:
            return

        comparison_result = self._create_comparison_report(task_result, alternative)
        if comparison_result:
            from claude_bridge.adaptive_council import propose_deactivation

            proposal_id = await propose_deactivation(comparison_result, self._proposals)
            if proposal_id is not None:
                self._session_proposal_count += 1

    def _create_comparison_report(
        self,
        task_result: TaskResult,
        alternative: Alternative,
    ) -> Any | None:
        _ = (task_result, alternative)
        return None

    def reset_session(self) -> None:
        self._session_proposal_count = 0


def create_proposal_engine(
    root: Path | None = None,
    mcp_discovery: MCPDiscovery | None = None,
) -> ProposalEngine:
    memory = get_memory_store()
    proposals = ProposalStore(root=root)
    return ProposalEngine(
        memory_store=memory,
        mcp_discovery=mcp_discovery,
        proposal_store=proposals,
    )
