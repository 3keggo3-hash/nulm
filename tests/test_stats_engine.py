"""Tests for stats_engine.py - StatisticalThreshold and comparison validation."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import pytest

from claude_bridge.stats_engine import (
    ComparisonResult,
    StatisticalThreshold,
)


class TestStatisticalThreshold:
    def test_insufficient_data_both_small(self):
        engine = StatisticalThreshold()
        result = engine.is_comparison_valid(
            skill_a_results=[True, False, True, False, True],
            skill_b_results=[True, True, False, True, False],
        )
        assert result.valid is False
        assert "insufficient_data" in result.reason
        assert result.significant is False

    def test_insufficient_data_a_small(self):
        engine = StatisticalThreshold()
        results_a = [True] * 15 + [False] * 10
        results_b = [True] * 35 + [False] * 15
        result = engine.is_comparison_valid(results_a, results_b)
        assert result.valid is False
        assert "insufficient_data" in result.reason

    def test_insufficient_data_b_small(self):
        engine = StatisticalThreshold()
        results_a = [True] * 35 + [False] * 15
        results_b = [True] * 15 + [False] * 10
        result = engine.is_comparison_valid(results_a, results_b)
        assert result.valid is False
        assert "insufficient_data" in result.reason

    def test_exact_min_sample_size(self):
        engine = StatisticalThreshold(min_sample_size=30)
        results_a = [True] * 30
        results_b = [False] * 30
        result = engine.is_comparison_valid(results_a, results_b)
        assert result.valid is True

    def test_no_significant_difference_equal_rates(self):
        engine = StatisticalThreshold(min_sample_size=30, confidence_level=0.95)
        results_a = [True] * 20 + [False] * 10
        results_b = [True] * 22 + [False] * 8
        result = engine.is_comparison_valid(results_a, results_b)
        assert result.valid is True
        assert result.significant is False

    def test_clear_winner_a_better(self):
        engine = StatisticalThreshold(min_sample_size=30, confidence_level=0.95)
        results_a = [True] * 28 + [False] * 2
        results_b = [True] * 18 + [False] * 12
        result = engine.is_comparison_valid(results_a, results_b)
        assert result.valid is True
        assert result.skill_a_rate == pytest.approx(0.933, rel=0.01)
        assert result.skill_b_rate == pytest.approx(0.6, rel=0.01)
        assert result.significant is True
        assert result.rate_difference == pytest.approx(0.333, rel=0.01)

    def test_clear_winner_b_better(self):
        engine = StatisticalThreshold(min_sample_size=30, confidence_level=0.95)
        results_a = [True] * 15 + [False] * 15
        results_b = [True] * 27 + [False] * 3
        result = engine.is_comparison_valid(results_a, results_b)
        assert result.valid is True
        assert result.skill_b_rate > result.skill_a_rate
        assert result.significant is True

    def test_marginal_difference_not_significant(self):
        engine = StatisticalThreshold(min_sample_size=30, confidence_level=0.95)
        results_a = [True] * 22 + [False] * 8
        results_b = [True] * 20 + [False] * 10
        result = engine.is_comparison_valid(results_a, results_b)
        assert result.valid is True
        assert result.significant is False

    def test_rate_calculation_correct(self):
        engine = StatisticalThreshold(min_sample_size=8)
        results_a = [True, True, False, True, False, True, True, True]
        results_b = [False, False, True, False, True, False, False, False]
        result = engine.is_comparison_valid(results_a, results_b)
        assert result.valid is True
        assert result.skill_a_rate == pytest.approx(0.75, rel=0.01)
        assert result.skill_b_rate == pytest.approx(0.25, rel=0.01)

    def test_all_true_results(self):
        engine = StatisticalThreshold(min_sample_size=30)
        results_a = [True] * 40
        results_b = [True] * 40
        result = engine.is_comparison_valid(results_a, results_b)
        assert result.valid is True
        assert result.skill_a_rate == 1.0
        assert result.skill_b_rate == 1.0
        assert result.significant is False

    def test_all_false_results(self):
        engine = StatisticalThreshold(min_sample_size=30)
        results_a = [False] * 40
        results_b = [False] * 40
        result = engine.is_comparison_valid(results_a, results_b)
        assert result.valid is True
        assert result.skill_a_rate == 0.0
        assert result.skill_b_rate == 0.0
        assert result.significant is False

    def test_deactivation_eligible_clear_winner(self):
        engine = StatisticalThreshold(min_sample_size=30, confidence_level=0.95)
        results_a = [True] * 28 + [False] * 2
        results_b = [True] * 18 + [False] * 12
        comparison = engine.is_comparison_valid(results_a, results_b)
        assert comparison.significant is True
        assert engine.is_deactivation_eligible(comparison, min_rate_difference=0.15) is True

    def test_deactivation_not_eligible_insufficient_significance(self):
        engine = StatisticalThreshold(min_sample_size=30, confidence_level=0.95)
        results_a = [True] * 22 + [False] * 8
        results_b = [True] * 20 + [False] * 10
        comparison = engine.is_comparison_valid(results_a, results_b)
        assert comparison.significant is False
        assert engine.is_deactivation_eligible(comparison, min_rate_difference=0.15) is False

    def test_deactivation_not_eligible_insufficient_data(self):
        engine = StatisticalThreshold(min_sample_size=30)
        results_a = [True] * 5
        results_b = [True] * 5
        comparison = engine.is_comparison_valid(results_a, results_b)
        assert comparison.valid is False
        assert engine.is_deactivation_eligible(comparison, min_rate_difference=0.15) is False

    def test_deactivation_not_eligible_small_difference(self):
        engine = StatisticalThreshold(min_sample_size=30, confidence_level=0.95)
        results_a = [True] * 24 + [False] * 6
        results_b = [True] * 21 + [False] * 9
        comparison = engine.is_comparison_valid(results_a, results_b)
        assert comparison.valid is True
        assert comparison.significant is False
        assert engine.is_deactivation_eligible(comparison, min_rate_difference=0.15) is False

    def test_comparison_result_to_dict(self):
        result = ComparisonResult(
            valid=True,
            reason="ok",
            skill_a_rate=0.75,
            skill_b_rate=0.55,
            significant=True,
            p_value=0.023,
            z_score=2.0,
            rate_difference=0.2,
        )
        d = result.to_dict()
        assert d["valid"] is True
        assert d["reason"] == "ok"
        assert d["skill_a_rate"] == 0.75
        assert d["skill_b_rate"] == 0.55
        assert d["significant"] is True
        assert d["p_value"] == 0.023
        assert d["z_score"] == 2.0
        assert d["rate_difference"] == 0.2

    def test_custom_min_sample_size(self):
        engine = StatisticalThreshold(min_sample_size=10)
        results_a = [True] * 10
        results_b = [False] * 10
        result = engine.is_comparison_valid(results_a, results_b)
        assert result.valid is True

    def test_custom_confidence_level(self):
        engine = StatisticalThreshold(min_sample_size=30, confidence_level=0.99)
        results_a = [True] * 28 + [False] * 2
        results_b = [True] * 18 + [False] * 12
        result = engine.is_comparison_valid(results_a, results_b)
        assert result.valid is True
