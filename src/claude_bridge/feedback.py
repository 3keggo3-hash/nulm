"""Feedback collection for Claude Bridge."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_bridge.audit import current_session_id

_FEEDBACK_CACHE: list[dict[str, Any]] = []
_LAST_COLLECTION_TIME: float = 0.0
_COLLECTION_INTERVAL_SECONDS: float = 300.0


def _feedback_dir() -> Path:
    return Path.home() / ".claude-bridge" / "feedback"


def _cache_feedback_record(record: dict[str, Any]) -> None:
    global _FEEDBACK_CACHE, _LAST_COLLECTION_TIME
    _FEEDBACK_CACHE.append(record)
    _LAST_COLLECTION_TIME = datetime.now(timezone.utc).timestamp()
    if len(_FEEDBACK_CACHE) > 50:
        _FEEDBACK_CACHE = _FEEDBACK_CACHE[-50:]


def should_collect_feedback(last_collection: float | None = None) -> bool:
    """Check if enough time has passed to avoid feedback fatigue."""
    now = datetime.now(timezone.utc).timestamp()
    if last_collection is None:
        last_collection = _LAST_COLLECTION_TIME
    return (now - last_collection) >= _COLLECTION_INTERVAL_SECONDS


def send_feedback_impl(
    rating: int,
    comment: str,
    include_session: bool = True,
) -> dict[str, Any]:
    """Validate and persist user feedback to the .claude-bridge/feedback directory."""
    if not isinstance(rating, int) or rating < 1 or rating > 5:
        return {
            "ok": False,
            "message": "Rating must be an integer between 1 and 5",
            "details": {"rating": rating},
        }

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    session_id = current_session_id() if include_session else None

    record: dict[str, Any] = {
        "timestamp": timestamp,
        "rating": rating,
        "comment": comment,
    }
    if session_id:
        record["session_id"] = session_id

    _feedback_dir().mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex[:8]}_{timestamp}.json"
    filepath = _feedback_dir() / filename
    filepath.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    _cache_feedback_record(record)

    return {
        "ok": True,
        "message": "Feedback saved",
        "details": {
            "file": str(filepath),
            "rating": rating,
            "session_id": session_id,
        },
    }


def get_feedback_summary(days_back: int = 7) -> dict[str, Any]:
    """Get aggregated feedback summary for the specified time period."""
    feedback_dir = _feedback_dir()
    if not feedback_dir.exists():
        return {"ok": True, "feedback_count": 0, "average_rating": None, "ratings_by_day": []}

    cutoff = datetime.now(timezone.utc).timestamp() - (days_back * 86400)
    ratings: list[int] = []
    ratings_by_day: dict[str, list[int]] = {}

    for filepath in feedback_dir.glob("*.json"):
        try:
            content = json.loads(filepath.read_text(encoding="utf-8"))
            ts = content.get("timestamp", "")
            if ts:
                dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if dt.timestamp() >= cutoff:
                    day_key = dt.strftime("%Y-%m-%d")
                    if day_key not in ratings_by_day:
                        ratings_by_day[day_key] = []
                    ratings_by_day[day_key].append(content.get("rating", 0))
                    ratings.append(content.get("rating", 0))
        except (OSError, ValueError, KeyError):
            continue

    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else None
    day_summaries = [
        {"date": day, "count": len(rvals), "average": round(sum(rvals) / len(rvals), 2)}
        for day, rvals in sorted(ratings_by_day.items())
    ]

    return {
        "ok": True,
        "feedback_count": len(ratings),
        "average_rating": avg_rating,
        "ratings_by_day": day_summaries,
    }


def get_recent_ratings(limit: int = 10) -> list[int]:
    """Get the most recent feedback ratings from cache."""
    return [r.get("rating", 0) for r in _FEEDBACK_CACHE[-limit:]]


def is_low_satisfaction() -> bool:
    """Check if recent feedback indicates low satisfaction (avg < 3).

    Returns True if we have at least 3 recent ratings with average < 3.0.
    This function is intended for future integration with adaptive behavior.
    Currently returns False as feedback consumption is not yet implemented.
    """
    recent = get_recent_ratings(limit=5)
    if len(recent) < 3:
        return False
    return sum(recent) / len(recent) < 3.0


def get_satisfaction_status() -> dict[str, Any]:
    """Return current satisfaction status for dashboard/monitoring.

    This data is intended for future adaptive behavior (e.g., showing
    more helpful hints when satisfaction is low). Currently returns
    raw data for future consumption.
    """
    recent = get_recent_ratings(limit=10)
    avg = sum(recent) / len(recent) if recent else 0.0
    return {
        "has_enough_data": len(recent) >= 3,
        "recent_count": len(recent),
        "average_rating": round(avg, 2) if recent else None,
        "is_low": avg < 3.0 if recent and len(recent) >= 3 else False,
        "recent_ratings": recent,
    }
