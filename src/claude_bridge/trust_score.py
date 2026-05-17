"""Trust Score — audit log analysis with actionable diagnostic insights."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class TrustDiagnostics:
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
class TrustInsight:
    severity: str
    category: str
    message: str
    affected_tools: list[str] = field(default_factory=list)
    recommendation: str = ""


SLOW_RESPONSE_THRESHOLD_MS = 5000
MAX_CONSECUTIVE_FOR_REVIEW = 5


def _parse_timestamp(ts: str) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


def _generate_insights(diagnostics: TrustDiagnostics) -> list[TrustInsight]:
    insights: list[TrustInsight] = []

    if diagnostics.total_requests == 0:
        return insights

    if diagnostics.deny_rate > 0.3:
        insights.append(
            TrustInsight(
                severity="high",
                category="deny_rate",
                message=f"High deny rate: {diagnostics.deny_rate:.1%} of requests denied",
                recommendation="Review denied calls - adjust guard policy or approval thresholds",
            )
        )
    elif diagnostics.deny_rate > 0.1:
        insights.append(
            TrustInsight(
                severity="medium",
                category="deny_rate",
                message=f"Moderate deny rate: {diagnostics.deny_rate:.1%} of requests denied",
                recommendation="Some requests denied - check if tool patterns are clear to agent",
            )
        )

    if diagnostics.max_consecutive_denies >= MAX_CONSECUTIVE_FOR_REVIEW:
        insights.append(
            TrustInsight(
                severity="high",
                category="consecutive_denies",
                message=f"{diagnostics.max_consecutive_denies} consecutive denies detected",
                recommendation="Investigate denied pattern - agent may be stuck",
            )
        )

    high_error_tools = [tool for tool, rate in diagnostics.tool_deny_rates.items() if rate > 0.5]
    if high_error_tools:
        insights.append(
            TrustInsight(
                severity="high",
                category="tool_errors",
                message=f"High error rate for tools: {', '.join(high_error_tools[:3])}",
                affected_tools=high_error_tools,
                recommendation="High error rate for these tools - verify params or check perms",
            )
        )

    if diagnostics.slow_response_rate > 0.2:
        insights.append(
            TrustInsight(
                severity="medium",
                category="performance",
                message=(
                    f"Slow: {diagnostics.slow_response_rate:.1%} "
                    f"> {SLOW_RESPONSE_THRESHOLD_MS}ms"
                ),
                recommendation="Enable result caching or reduce batch sizes",
            )
        )

    if diagnostics.anomaly_frequency > 0.2:
        insights.append(
            TrustInsight(
                severity="medium",
                category="anomaly",
                message=f"Frequent anomalies: {diagnostics.anomaly_frequency:.1%} flagged",
                recommendation="Review anomaly patterns - may indicate unusual usage",
            )
        )

    if len(diagnostics.daily_deny_rates) >= 3:
        sorted_dates = sorted(diagnostics.daily_deny_rates.keys())
        if len(sorted_dates) >= 2:
            recent = diagnostics.daily_deny_rates.get(sorted_dates[-1], 0)
            older = diagnostics.daily_deny_rates.get(sorted_dates[0], 0)
            if recent > older * 1.5 and older > 0:
                insights.append(
                    TrustInsight(
                        severity="high",
                        category="trend",
                        message="Deny rate trending upward significantly",
                        recommendation="Recent activity shows increasing denials - investigate",
                    )
                )

    return insights


def _compute_diagnostics(signals: dict[str, Any]) -> TrustDiagnostics:
    return TrustDiagnostics(
        deny_rate=signals.get("deny_rate", 0.0),
        anomaly_frequency=signals.get("anomaly_frequency", 0.0),
        consecutive_denies=signals.get("consecutive_denies", 0),
        max_consecutive_denies=signals.get("max_consecutive_denies", 0),
        error_rate=signals.get("error_rate", 0.0),
        slow_response_rate=signals.get("slow_response_rate", 0.0),
        tool_deny_rates=signals.get("tool_deny_rates", {}),
        daily_deny_rates=signals.get("daily_deny_rates", {}),
        total_requests=signals.get("total_requests", 0),
        anomaly_score_sum=signals.get("anomaly_score_sum", 0.0),
        response_time_avg=signals.get("response_time_avg", 0.0),
    )


def get_trust_signals(days: int = 7) -> dict[str, Any]:
    """Extract raw diagnostic signals from audit logs."""
    from claude_bridge.audit import _audit_dir

    audit_dir = _audit_dir()
    if not audit_dir.exists():
        return {"ok": True, "signals": TrustDiagnostics().__dict__, "total_requests": 0}

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
    """Calculate actionable diagnostic insights from recent audit records.

    Returns insights with severity, category, message, and recommendations
    instead of an arbitrary score number.
    """
    from claude_bridge.audit import _audit_dir

    audit_dir = _audit_dir()
    if not audit_dir.exists():
        return {
            "ok": True,
            "has_data": False,
            "message": "No audit data available",
            "details": {
                "days_analyzed": days,
                "last_updated": datetime.now(timezone.utc).isoformat(),
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

    diagnostics = TrustDiagnostics(
        deny_rate=round(denies / max(total, 1), 3),
        anomaly_frequency=round(anomalies / max(total, 1), 3),
        consecutive_denies=consecutive_count,
        max_consecutive_denies=max_consecutive,
        error_rate=round(errors / max(total, 1), 3),
        slow_response_rate=round(slow_responses / max(total, 1), 3),
        tool_deny_rates={
            tool: round(tool_denies[tool] / max(tool_counts[tool], 1), 3) for tool in tool_counts
        },
        daily_deny_rates={
            d: round(daily_denies[d] / max(daily_counts[d], 1), 3) for d in daily_counts
        },
        total_requests=total,
        anomaly_score_sum=round(anomaly_score_sum, 2),
        response_time_avg=(
            round(sum(response_times) / len(response_times), 2) if response_times else 0.0
        ),
    )

    insights = _generate_insights(diagnostics)

    return {
        "ok": True,
        "has_data": total > 0,
        "message": (
            f"Trust diagnostics: {len(insights)} issue(s) found"
            if insights
            else "Trust diagnostics: no issues detected"
        ),
        "details": {
            "days_analyzed": days,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "total_requests": total,
            "deny_rate": diagnostics.deny_rate,
            "max_consecutive_denies": diagnostics.max_consecutive_denies,
            "error_rate": diagnostics.error_rate,
            "slow_response_rate": diagnostics.slow_response_rate,
            "insights": [ins.__dict__ for ins in insights],
        },
    }
