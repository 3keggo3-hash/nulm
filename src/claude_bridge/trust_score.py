"""Trust Score MVP — read audit log and calculate deny rate, anomaly frequency, etc."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from claude_bridge.audit import _audit_dir


def get_trust_score(days: int = 7) -> dict[str, Any]:
    """Calculate a trust score based on recent audit records.

    Returns a dict with keys: score, deny_rate, anomaly_frequency,
    approval_rejection_trend, total_requests, last_updated.
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
                "last_updated": datetime.now(timezone.utc).isoformat(),
            },
        }

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    total = 0
    denies = 0
    anomalies = 0
    daily_counts: dict[str, int] = defaultdict(int)
    daily_denies: dict[str, int] = defaultdict(int)

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
                    timestamp = record.get("timestamp", "")
                    try:
                        dt = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(
                            tzinfo=timezone.utc
                        )
                    except (ValueError, TypeError):
                        continue
                    if dt < cutoff:
                        continue

                    total += 1
                    date_key = dt.strftime("%Y-%m-%d")

                    result = record.get("result", {})
                    if isinstance(result, dict) and not result.get("ok", True):
                        denies += 1
                        daily_denies[date_key] += 1
                    elif isinstance(record.get("decision"), dict):
                        if record["decision"].get("action") in ("deny", "ask"):
                            denies += 1
                            daily_denies[date_key] += 1

                    if record.get("anomaly_score", 0) > 0.5:
                        anomalies += 1

                    daily_counts[date_key] += 1
    except (OSError, FileNotFoundError):
        pass

    deny_rate = round(denies / max(total, 1), 3)
    anomaly_frequency = round(anomalies / max(total, 1), 3)
    score = round(max(0, 100 - (deny_rate * 60) - (anomaly_frequency * 40)))

    recent_days = sorted(daily_counts.keys())[-3:]
    if len(recent_days) >= 2 and recent_days:
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
        },
    }
