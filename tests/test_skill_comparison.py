"""Tests for skill_comparison.py - SkillComparator and performance comparison."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import pytest

from claude_bridge.skill_comparison import (
    ComparisonReport,
    PerformanceMetrics,
    SkillComparator,
    compare_skills,
)
from claude_bridge.skill_schema import SkillMeta
from claude_bridge.stats_engine import StatisticalThreshold


class TestPerformanceMetrics:
    def test_record_outcome_success(self):
        metrics = PerformanceMetrics()
        metrics.record_outcome(True)
        assert metrics.hit_count == 1
        assert metrics.acceptance_rate == 1.0
        assert metrics.result_history == [True]

    def test_record_outcome_failure(self):
        metrics = PerformanceMetrics()
        metrics.record_outcome(False)
        assert metrics.hit_count == 1
        assert metrics.acceptance_rate == 0.0
        assert metrics.result_history == [False]

    def test_record_outcome_multiple(self):
        metrics = PerformanceMetrics()
        for outcome in [True, False, True, True, False]:
            metrics.record_outcome(outcome)
        assert metrics.hit_count == 5
        assert metrics.acceptance_rate == pytest.approx(0.6, rel=0.01)
        assert len(metrics.result_history) == 5

    def test_to_dict(self):
        metrics = PerformanceMetrics(
            hit_count=10, acceptance_rate=0.8, result_history=[True, True, False]
        )
        d = metrics.to_dict()
        assert d["hit_count"] == 10
        assert d["acceptance_rate"] == 0.8
        assert d["result_history"] == [True, True, False]

    def test_from_dict(self):
        data = {"hit_count": 5, "acceptance_rate": 0.6, "result_history": [True, False, True]}
        metrics = PerformanceMetrics.from_dict(data)
        assert metrics.hit_count == 5
        assert metrics.acceptance_rate == pytest.approx(0.6, rel=0.01)
        assert len(metrics.result_history) == 3


class TestSkillComparator:
    def setup_method(self) -> None:
        self._stats = StatisticalThreshold(min_sample_size=30)
        self._comparator = SkillComparator(stats_engine=self._stats)

    def _make_skill_with_results(self, name: str, results: list[bool]) -> SkillMeta:
        perf = PerformanceMetrics(result_history=results)
        skill = SkillMeta(name=name, version="1.0", trigger_phrases=["test"])
        skill.performance_metrics = perf
        return skill

    def test_both_skills_insufficient_data(self):
        skill_a = self._make_skill_with_results("skill_a", [True] * 10)
        skill_b = self._make_skill_with_results("skill_b", [True] * 10)
        report = self._comparator.compare(skill_a, skill_b)
        assert report.winner == "insufficient_data"
        assert report.deactivation_eligible is False

    def test_skill_a_insufficient_b_sufficient(self):
        skill_a = self._make_skill_with_results("skill_a", [True] * 10)
        skill_b = self._make_skill_with_results("skill_b", [True] * 40)
        report = self._comparator.compare(skill_a, skill_b)
        assert report.winner == "insufficient_data"
        assert report.deactivation_eligible is False

    def test_no_significant_difference(self):
        skill_a = self._make_skill_with_results("skill_a", [True] * 25 + [False] * 15)
        skill_b = self._make_skill_with_results("skill_b", [True] * 23 + [False] * 17)
        report = self._comparator.compare(skill_a, skill_b)
        assert report.winner == "none"
        assert report.deactivation_eligible is False

    def test_clear_winner_a_better(self):
        skill_a = self._make_skill_with_results("skill_a", [True] * 30 + [False] * 2)
        skill_b = self._make_skill_with_results("skill_b", [True] * 18 + [False] * 14)
        report = self._comparator.compare(skill_a, skill_b)
        assert report.winner == "skill_a"
        assert report.loser == "skill_b"
        assert report.deactivation_eligible is True

    def test_clear_winner_b_better(self):
        skill_a = self._make_skill_with_results("skill_a", [True] * 15 + [False] * 17)
        skill_b = self._make_skill_with_results("skill_b", [True] * 28 + [False] * 4)
        report = self._comparator.compare(skill_a, skill_b)
        assert report.winner == "skill_b"
        assert report.loser == "skill_a"
        assert report.deactivation_eligible is True

    def test_equal_performance_no_deactivation(self):
        skill_a = self._make_skill_with_results("skill_a", [True] * 25 + [False] * 15)
        skill_b = self._make_skill_with_results("skill_b", [True] * 25 + [False] * 15)
        report = self._comparator.compare(skill_a, skill_b)
        assert report.winner == "none"
        assert report.deactivation_eligible is False

    def test_small_difference_no_deactivation(self):
        skill_a = self._make_skill_with_results("skill_a", [True] * 24 + [False] * 8)
        skill_b = self._make_skill_with_results("skill_b", [True] * 22 + [False] * 10)
        report = self._comparator.compare(skill_a, skill_b)
        assert report.deactivation_eligible is False

    def test_should_propose_deactivation_insufficient_data(self):
        report = ComparisonReport(
            winner="insufficient_data",
            loser="skill_b",
            comparison=None,
            deactivation_eligible=False,
            reason="insufficient_data",
        )
        assert self._comparator.should_propose_deactivation(report) is False

    def test_should_propose_deactivation_no_winner(self):
        report = ComparisonReport(
            winner="none",
            loser="none",
            comparison=None,
            deactivation_eligible=False,
            reason="no_significant_difference",
        )
        assert self._comparator.should_propose_deactivation(report) is False

    def test_should_propose_deactivation_small_diff(self):
        from claude_bridge.stats_engine import ComparisonResult

        mock_comparison = ComparisonResult(
            valid=True,
            reason="ok",
            skill_a_rate=0.55,
            skill_b_rate=0.50,
            significant=True,
            p_value=0.1,
            z_score=0.5,
            rate_difference=0.05,
        )
        report = ComparisonReport(
            winner="skill_a",
            loser="skill_b",
            comparison=mock_comparison,
            deactivation_eligible=False,
            reason="small diff",
        )
        assert self._comparator.should_propose_deactivation(report) is False

    def test_should_propose_deactivation_eligible(self):
        from claude_bridge.stats_engine import ComparisonResult

        mock_comparison = ComparisonResult(
            valid=True,
            reason="ok",
            skill_a_rate=0.85,
            skill_b_rate=0.55,
            significant=True,
            p_value=0.01,
            z_score=2.5,
            rate_difference=0.30,
        )
        report = ComparisonReport(
            winner="skill_a",
            loser="skill_b",
            comparison=mock_comparison,
            deactivation_eligible=False,
            reason="clear winner",
        )
        assert self._comparator.should_propose_deactivation(report) is True

    def test_compare_skills_function(self):
        skill_a = self._make_skill_with_results("skill_a", [True] * 30)
        skill_b = self._make_skill_with_results("skill_b", [False] * 30)
        report = compare_skills(skill_a, skill_b)
        assert report.winner == "skill_a"
        assert report.deactivation_eligible is True

    def test_comparison_report_to_dict(self):
        from claude_bridge.stats_engine import ComparisonResult

        mock_comparison = ComparisonResult(
            valid=True,
            reason="ok",
            skill_a_rate=0.8,
            skill_b_rate=0.5,
            significant=True,
            p_value=0.01,
            z_score=2.5,
            rate_difference=0.3,
        )
        report = ComparisonReport(
            winner="skill_a",
            loser="skill_b",
            comparison=mock_comparison,
            deactivation_eligible=True,
            reason="test comparison",
        )
        d = report.to_dict()
        assert d["winner"] == "skill_a"
        assert d["loser"] == "skill_b"
        assert d["deactivation_eligible"] is True
        assert d["reason"] == "test comparison"
        assert "comparison" in d

    def test_custom_min_rate_difference(self):
        comparator = SkillComparator(min_rate_difference=0.25)
        skill_a = self._make_skill_with_results("skill_a", [True] * 26 + [False] * 4)
        skill_b = self._make_skill_with_results("skill_b", [True] * 20 + [False] * 10)
        report = comparator.compare(skill_a, skill_b)
        assert report.deactivation_eligible is False

        skill_c = self._make_skill_with_results("skill_c", [True] * 28 + [False] * 2)
        skill_d = self._make_skill_with_results("skill_d", [True] * 15 + [False] * 15)
        report2 = comparator.compare(skill_c, skill_d)
        assert report2.deactivation_eligible is True

    def test_skill_without_performance_metrics(self):
        skill_a = SkillMeta(name="skill_a", version="1.0", trigger_phrases=["test"])
        skill_b = self._make_skill_with_results("skill_b", [True] * 35)
        report = self._comparator.compare(skill_a, skill_b)
        assert report.winner == "insufficient_data"
        assert report.deactivation_eligible is False
