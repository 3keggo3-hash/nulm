"""Trust Score — audit log analysis with explainable trust scoring."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from claude_bridge.audit import _audit_dir


@dataclass
class TrustSignals:
    deny_rate: float = 0.0
    anomaly_frequency: float = 0.0
    consecutive_denies: int = 0
    max_consecutive_denies: int = 0
    error_rate: float = 0.0
    slow_response_rate: float = 0.0
    tool_deny_rates: dict[str, float] = field(default_factory=dict)
    daily_deny_rates: dict[str, float] = field(default_factory=dict)
    total_requests: int = 0
    anomaly_score_sum: float = 0.0
    response_time_avg: float = 0.0
    recent_deny_rate: float = 0.0
    older_deny_rate: float = 0.0


@dataclass
class TrustFactors:
    deny_penalty: float
    anomaly_penalty: float
    consecutive_deny_penalty: float
    error_penalty: float
    slow_response_penalty: float
    trend_adjustment: float

    def to_dict(self) -> dict[str, float]:
        return {
            "deny_penalty": self.deny_penalty,
            "anomaly_penalty": self.anomaly_penalty,
            "consecutive_deny_penalty": self.consecutive_deny_penalty,
            "error_penalty": self.error_penalty,
            "slow_response_penalty": self.slow_response_penalty,
            "trend_adjustment": self.trend_adjustment,
        }


TRUST_WEIGHTS = {
    "deny": 35,
    "anomaly": 25,
    "consecutive_deny": 15,
    "error": 10,
    "slow_response": 10,
    "trend_boost": 5,
}

SLOW_RESPONSE_THRESHOLD_MS = 5000
MAX_CONSECUTIVE_FOR_PENALTY = 5


def _parse_timestamp(ts: str) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


def _compute_trust_factors(signals: TrustSignals, days: int) -> TrustFactors:
    deny_penalty = signals.deny_rate * TRUST_WEIGHTS["deny"]
    anomaly_penalty = signals.anomaly_frequency * TRUST_WEIGHTS["anomaly"]

    consecutive_deny_penalty = 0.0
    if signals.max_consecutive_denies >= 2:
        consecutive_deny_penalty = (
            min(signals.max_consecutive_denies, MAX_CONSECUTIVE_FOR_PENALTY)
            / MAX_CONSECUTIVE_FOR_PENALTY
        ) * TRUST_WEIGHTS["consecutive_deny"]

    error_penalty = signals.error_rate * TRUST_WEIGHTS["error"]
    slow_penalty = signals.slow_response_rate * TRUST_WEIGHTS["slow_response"]

    trend_adjustment = 0.0
    if signals.total_requests > 10 and signals.daily_deny_rates:
        sorted_dates = sorted(signals.daily_deny_rates.keys())
        if len(sorted_dates) >= 2:
            recent = signals.daily_deny_rates.get(sorted_dates[-1], 0)
            older = signals.daily_deny_rates.get(sorted_dates[0], 0)
            if older > 0:
                change_ratio = recent / older
                if change_ratio > 1.5:
                    trend_adjustment = -TRUST_WEIGHTS["trend_boost"]
                elif change_ratio < 0.67:
                    trend_adjustment = TRUST_WEIGHTS["trend_boost"]

    return TrustFactors(
        deny_penalty=round(deny_penalty, 2),
        anomaly_penalty=round(anomaly_penalty, 2),
        consecutive_deny_penalty=round(consecutive_deny_penalty, 2),
        error_penalty=round(error_penalty, 2),
        slow_response_penalty=round(slow_penalty, 2),
        trend_adjustment=round(trend_adjustment, 2),
    )


def _calculate_score(factors: TrustFactors, signals: TrustSignals) -> tuple[int, str]:
    base_score = 100.0
    deductions = (
        factors.deny_penalty
        + factors.anomaly_penalty
        + factors.consecutive_deny_penalty
        + factors.error_penalty
        + factors.slow_response_penalty
    )
    score = max(0, min(100, base_score - deductions + factors.trend_adjustment))
    reason = (
        f"deny:{signals.deny_rate:.1%}, "
        f"anomaly:{signals.anomaly_frequency:.1%}, "
        f"consecutive:{signals.max_consecutive_denies}"
    )
    return int(round(score)), reason


def _explain_score(score: int, signals: TrustSignals, factors: TrustFactors) -> str:
    if score >= 90:
        return "High trust: low deny rate and minimal anomalies"
    elif score >= 70:
        return "Moderate trust: some denies or anomalies detected"
    elif score >= 50:
        return "Low trust: elevated deny rate or anomaly frequency"
    else:
        return "Critical trust: high deny rate, anomalies, or errors"


def get_trust_signals(days: int = 7) -> dict[str, Any]:
    """Extract raw trust signals from audit logs without calculating score."""
    audit_dir = _audit_dir()
    if not audit_dir.exists():
        return {"ok": True, "signals": TrustSignals().__dict__, "total_requests": 0}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    total = 0
    denies = 0
    anomalies = 0
    errors = 0
    slow_responses = 0
    consecutive_count = 0
    max_consecutive = 0
    daily_counts: dict[str, int] = defaultdict(int)
    daily_denies: dict[str, int] = defaultdict(int)
    tool_denies: dict[str, int] = defaultdict(int)
    tool_counts: dict[str, int] = defaultdict(int)
    anomaly_score_sum = 0.0
    response_times: list[float] = []

    try:
        for jsonl_file in audit_dir.glob("*.jsonl"):
            with open(jsonl_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = _parse_timestamp(record.get("timestamp", ""))
                    if ts is None or ts < cutoff:
                        continue

                    total += 1
                    date_key = ts.strftime("%Y-%m-%d")
                    tool = record.get("tool", "unknown")
                    tool_counts[tool] += 1

                    response_time = record.get("duration_ms", 0)
                    if response_time > 0:
                        response_times.append(response_time)
                        if response_time > SLOW_RESPONSE_THRESHOLD_MS:
                            slow_responses += 1

                    is_deny = False
                    result = record.get("result", {})
                    if isinstance(result, dict) and not result.get("ok", True):
                        denies += 1
                        daily_denies[date_key] += 1
                        tool_denies[tool] += 1
                        is_deny = True
                        if result.get("error"):
                            errors += 1
                    elif isinstance(record.get("decision"), dict):
                        if record["decision"].get("action") in ("deny", "ask"):
                            denies += 1
                            daily_denies[date_key] += 1
                            tool_denies[tool] += 1
                            is_deny = True

                    if is_deny:
                        consecutive_count += 1
                        max_consecutive = max(max_consecutive, consecutive_count)
                    else:
                        consecutive_count = 0

                    anomaly_score = record.get("anomaly_score", 0)
                    if anomaly_score > 0:
                        anomalies += 1
                        anomaly_score_sum += anomaly_score

                    daily_counts[date_key] += 1
    except (OSError, FileNotFoundError):
        pass

    avg_response = sum(response_times) / len(response_times) if response_times else 0.0

    tool_deny_rates = {
        tool: round(tool_denies[tool] / max(tool_counts[tool], 1), 3) for tool in tool_counts
    }
    daily_deny_rates = {
        d: round(daily_denies[d] / max(daily_counts[d], 1), 3) for d in daily_counts
    }

    return {
        "ok": True,
        "signals": {
            "deny_rate": round(denies / max(total, 1), 3),
            "anomaly_frequency": round(anomalies / max(total, 1), 3),
            "consecutive_denies": consecutive_count,
            "max_consecutive_denies": max_consecutive,
            "error_rate": round(errors / max(total, 1), 3),
            "slow_response_rate": round(slow_responses / max(total, 1), 3),
            "tool_deny_rates": tool_deny_rates,
            "daily_deny_rates": daily_deny_rates,
            "total_requests": total,
            "anomaly_score_sum": round(anomaly_score_sum, 2),
            "response_time_avg": round(avg_response, 2),
        },
        "total_requests": total,
    }


def get_trust_score(days: int = 7) -> dict[str, Any]:
    """Calculate an explainable trust score based on recent audit records.

    Returns a dict with keys: score, deny_rate, anomaly_frequency,
    approval_rejection_trend, total_requests, last_updated, explanation,
    and breakdown of penalty factors.
    """
    audit_dir = _audit_dir()
    if not audit_dir.exists():
        return {
            "ok": True,
            "score": 100,
            "message": "No audit data available",
            "details": {
                "score": 100,
                "deny_rate": 0.0,
                "anomaly_frequency": 0.0,
                "approval_rejection_trend": "stable",
                "total_requests": 0,
                "days_analyzed": days,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "explanation": "No audit data — defaulting to full trust",
                "factors": TrustFactors(0, 0, 0, 0, 0, 0).to_dict(),
            },
        }

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    total = 0
    denies = 0
    anomalies = 0
    errors = 0
    slow_responses = 0
    consecutive_count = 0
    max_consecutive = 0
    daily_counts: dict[str, int] = defaultdict(int)
    daily_denies: dict[str, int] = defaultdict(int)
    tool_denies: dict[str, int] = defaultdict(int)
    tool_counts: dict[str, int] = defaultdict(int)
    anomaly_score_sum = 0.0
    response_times: list[float] = []

    try:
        for jsonl_file in audit_dir.glob("*.jsonl"):
            with open(jsonl_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = _parse_timestamp(record.get("timestamp", ""))
                    if ts is None or ts < cutoff:
                        continue

                    total += 1
                    date_key = ts.strftime("%Y-%m-%d")
                    tool = record.get("tool", "unknown")
                    tool_counts[tool] += 1

                    response_time = record.get("duration_ms", 0)
                    if response_time > 0:
                        response_times.append(response_time)
                        if response_time > SLOW_RESPONSE_THRESHOLD_MS:
                            slow_responses += 1

                    is_deny = False
                    result = record.get("result", {})
                    if isinstance(result, dict) and not result.get("ok", True):
                        denies += 1
                        daily_denies[date_key] += 1
                        tool_denies[tool] += 1
                        is_deny = True
                        if result.get("error"):
                            errors += 1
                    elif isinstance(record.get("decision"), dict):
                        if record["decision"].get("action") in ("deny", "ask"):
                            denies += 1
                            daily_denies[date_key] += 1
                            tool_denies[tool] += 1
                            is_deny = True

                    if is_deny:
                        consecutive_count += 1
                        max_consecutive = max(max_consecutive, consecutive_count)
                    else:
                        consecutive_count = 0

                    anomaly_score = record.get("anomaly_score", 0)
                    if anomaly_score > 0:
                        anomalies += 1
                        anomaly_score_sum += anomaly_score

                    daily_counts[date_key] += 1
    except (OSError, FileNotFoundError):
        pass

    deny_rate = round(denies / max(total, 1), 3)
    anomaly_frequency = round(anomalies / max(total, 1), 3)
    error_rate = round(errors / max(total, 1), 3)
    slow_response_rate = round(slow_responses / max(total, 1), 3)

    tool_deny_rates = {
        tool: round(tool_denies[tool] / max(tool_counts[tool], 1), 3) for tool in tool_counts
    }
    daily_deny_rates = {
        d: round(daily_denies[d] / max(daily_counts[d], 1), 3) for d in daily_counts
    }

    signals = TrustSignals(
        deny_rate=deny_rate,
        anomaly_frequency=anomaly_frequency,
        consecutive_denies=consecutive_count,
        max_consecutive_denies=max_consecutive,
        error_rate=error_rate,
        slow_response_rate=slow_response_rate,
        tool_deny_rates=tool_deny_rates,
        daily_deny_rates=daily_deny_rates,
        total_requests=total,
        anomaly_score_sum=round(anomaly_score_sum, 2),
        response_time_avg=(
            round(sum(response_times) / len(response_times), 2) if response_times else 0.0
        ),
    )

    factors = _compute_trust_factors(signals, days)
    score, score_reason = _calculate_score(factors, signals)
    explanation = _explain_score(score, signals, factors)

    recent_days = sorted(daily_counts.keys())[-3:]
    if len(recent_days) >= 2:
        first = daily_denies.get(recent_days[0], 0) / max(daily_counts[recent_days[0]], 1)
        last = daily_denies.get(recent_days[-1], 0) / max(daily_counts[recent_days[-1]], 1)
        if last > first * 1.2:
            trend = "increasing"
        elif last < first * 0.8:
            trend = "decreasing"
        else:
            trend = "stable"
    else:
        trend = "stable"

    return {
        "ok": True,
        "score": score,
        "message": f"Trust score: {score}/100",
        "details": {
            "score": score,
            "deny_rate": deny_rate,
            "anomaly_frequency": anomaly_frequency,
            "approval_rejection_trend": trend,
            "total_requests": total,
            "days_analyzed": days,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "explanation": explanation,
            "factors": factors.to_dict(),
            "max_consecutive_denies": max_consecutive,
            "error_rate": error_rate,
            "slow_response_rate": slow_response_rate,
            "tool_deny_rates": tool_deny_rates,
            "daily_deny_rates": daily_deny_rates,
            "avg_response_time_ms": signals.response_time_avg,
        },
    }
