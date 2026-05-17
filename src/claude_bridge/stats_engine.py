"""Statistical threshold engine for skill comparison.

Provides statistical validation for comparing skill performance metrics
using two-proportion z-test with configurable confidence levels.
"""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

MIN_SAMPLE_SIZE = 30
CONFIDENCE_LEVEL = 0.95
Z_SCORE_95 = 1.96


@dataclass(frozen=True)
class ComparisonResult:
    valid: bool
    reason: str
    skill_a_rate: float
    skill_b_rate: float
    significant: bool
    p_value: float | None = None
    z_score: float | None = None
    rate_difference: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "reason": self.reason,
            "skill_a_rate": round(self.skill_a_rate, 4),
            "skill_b_rate": round(self.skill_b_rate, 4),
            "significant": self.significant,
            "p_value": round(self.p_value, 6) if self.p_value is not None else None,
            "z_score": round(self.z_score, 4) if self.z_score is not None else None,
            "rate_difference": (
                round(self.rate_difference, 4) if self.rate_difference is not None else None
            ),
        }


def _calculate_proportion_z_test(
    n_a: int,
    x_a: int,
    n_b: int,
    x_b: int,
) -> tuple[float, float]:
    p_a = x_a / n_a if n_a > 0 else 0.0
    p_b = x_b / n_b if n_b > 0 else 0.0

    p_pool = (x_a + x_b) / (n_a + n_b) if (n_a + n_b) > 0 else 0.0

    if p_pool == 0 or p_pool == 1:
        se = 0.0
    else:
        se = math.sqrt(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b))

    z = (p_a - p_b) / se if se > 0 else 0.0

    p_value = 2.0 * (1.0 - _normal_cdf(abs(z)))
    p_value = max(0.0, min(1.0, p_value))

    return z, p_value


def _normal_cdf(z: float) -> float:
    t = 1 / (1 + 0.2316419 * abs(z))
    poly = t * (
        0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821855978 + t * 1.330274429)))
    )
    p = 1 - (1 / (math.sqrt(2 * math.pi))) * math.exp(-z * z / 2) * poly
    return p


class StatisticalThreshold:
    min_sample_size: int = MIN_SAMPLE_SIZE
    confidence_level: float = CONFIDENCE_LEVEL

    def __init__(
        self,
        min_sample_size: int = MIN_SAMPLE_SIZE,
        confidence_level: float = CONFIDENCE_LEVEL,
    ) -> None:
        self.min_sample_size = min_sample_size
        self.confidence_level = confidence_level

    def is_comparison_valid(
        self,
        skill_a_results: list[bool],
        skill_b_results: list[bool],
    ) -> ComparisonResult:
        n_a = len(skill_a_results)
        n_b = len(skill_b_results)

        if n_a < self.min_sample_size or n_b < self.min_sample_size:
            return ComparisonResult(
                valid=False,
                reason=f"insufficient_data: need {self.min_sample_size}, got a={n_a}, b={n_b}",
                skill_a_rate=0.0,
                skill_b_rate=0.0,
                significant=False,
                p_value=None,
                z_score=None,
                rate_difference=None,
            )

        x_a = sum(1 for r in skill_a_results if r)
        x_b = sum(1 for r in skill_b_results if r)

        rate_a = x_a / n_a
        rate_b = x_b / n_b

        z, p_value = _calculate_proportion_z_test(n_a, x_a, n_b, x_b)

        significant = p_value < (1 - self.confidence_level)

        return ComparisonResult(
            valid=True,
            reason="ok",
            skill_a_rate=rate_a,
            skill_b_rate=rate_b,
            significant=significant,
            p_value=p_value,
            z_score=z,
            rate_difference=rate_a - rate_b,
        )

    def is_deactivation_eligible(
        self,
        comparison: ComparisonResult,
        min_rate_difference: float = 0.15,
    ) -> bool:
        if not comparison.valid or not comparison.significant:
            return False
        return abs(comparison.rate_difference or 0) >= min_rate_difference
