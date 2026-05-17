"""Skill comparison system for performance-based skill evaluation.

Provides comparison between skills using statistical validation
and deactivation eligibility determination.
"""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from claude_bridge.stats_engine import ComparisonResult, StatisticalThreshold
from claude_bridge.skill_schema import SkillMeta

DEFAULT_MIN_RATE_DIFFERENCE = 0.15


@dataclass(frozen=True)
class ComparisonReport:
    winner: str
    loser: str
    comparison: ComparisonResult
    deactivation_eligible: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "winner": self.winner,
            "loser": self.loser,
            "comparison": self.comparison.to_dict(),
            "deactivation_eligible": self.deactivation_eligible,
            "reason": self.reason,
        }


@dataclass
class PerformanceMetrics:
    hit_count: int = 0
    acceptance_rate: float = 0.0
    result_history: list[bool] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hit_count": self.hit_count,
            "acceptance_rate": round(self.acceptance_rate, 4),
            "result_history": self.result_history,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PerformanceMetrics:
        return cls(
            hit_count=int(data.get("hit_count", 0)),
            acceptance_rate=float(data.get("acceptance_rate", 0.0)),
            result_history=list(data.get("result_history", [])),
        )

    def record_outcome(self, success: bool) -> None:
        self.result_history.append(success)
        self.hit_count += 1
        if self.hit_count > 0:
            successes = sum(1 for r in self.result_history if r)
            self.acceptance_rate = successes / self.hit_count


def _extract_results(meta: SkillMeta) -> list[bool]:
    perf_data = getattr(meta, "performance_metrics", None)
    if perf_data is None:
        return []

    if isinstance(perf_data, dict):
        return list(perf_data.get("result_history", []))

    if hasattr(perf_data, "result_history"):
        return list(perf_data.result_history)

    return []


class SkillComparator:
    def __init__(
        self,
        stats_engine: StatisticalThreshold | None = None,
        min_rate_difference: float = DEFAULT_MIN_RATE_DIFFERENCE,
    ) -> None:
        self._stats = stats_engine or StatisticalThreshold()
        self._min_rate_diff = min_rate_difference

    def compare(self, skill_a: SkillMeta, skill_b: SkillMeta) -> ComparisonReport:
        results_a = _extract_results(skill_a)
        results_b = _extract_results(skill_b)

        comparison = self._stats.is_comparison_valid(results_a, results_b)

        if not comparison.valid:
            return ComparisonReport(
                winner="insufficient_data",
                loser="insufficient_data",
                comparison=comparison,
                deactivation_eligible=False,
                reason=f"insufficient_data: {comparison.reason}",
            )

        if not comparison.significant:
            return ComparisonReport(
                winner="none",
                loser="none",
                comparison=comparison,
                deactivation_eligible=False,
                reason="no_significant_difference",
            )

        if comparison.skill_a_rate > comparison.skill_b_rate:
            winner_name = skill_a.name
            loser_name = skill_b.name
        else:
            winner_name = skill_b.name
            loser_name = skill_a.name

        eligible = self.should_propose_deactivation(
            ComparisonReport(
                winner=winner_name,
                loser=loser_name,
                comparison=comparison,
                deactivation_eligible=False,
                reason="",
            )
        )

        rate_diff = abs(comparison.skill_a_rate - comparison.skill_b_rate)
        reason = f"{winner_name} ({comparison.skill_a_rate:.0%}) vs {loser_name} ({comparison.skill_b_rate:.0%}), diff={rate_diff:.0%}"

        return ComparisonReport(
            winner=winner_name,
            loser=loser_name,
            comparison=comparison,
            deactivation_eligible=eligible,
            reason=reason,
        )

    def should_propose_deactivation(self, report: ComparisonReport) -> bool:
        if report.winner == "insufficient_data" or report.winner == "none":
            return False

        if not report.comparison.significant:
            return False

        rate_diff = abs(
            (report.comparison.skill_a_rate or 0) - (report.comparison.skill_b_rate or 0)
        )
        return rate_diff >= self._min_rate_diff


def compare_skills(
    skill_a: SkillMeta,
    skill_b: SkillMeta,
    stats_engine: StatisticalThreshold | None = None,
) -> ComparisonReport:
    comparator = SkillComparator(stats_engine=stats_engine)
    return comparator.compare(skill_a, skill_b)
