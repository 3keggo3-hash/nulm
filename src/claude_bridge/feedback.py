"""Feedback collection for Claude Bridge."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_bridge.audit import current_session_id


def _feedback_dir() -> Path:
    return Path.home() / ".claude-bridge" / "feedback"


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
    filepath.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return {
        "ok": True,
        "message": "Feedback saved",
        "details": {
            "file": str(filepath),
            "rating": rating,
            "session_id": session_id,
        },
    }
