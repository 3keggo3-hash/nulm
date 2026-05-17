"""Workflow session persistence and resume capability."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, cast


def _sessions_dir() -> Path:
    import os

    if os.environ.get("CLAUDE_BRIDGE_CACHE_DIR"):
        return Path(os.environ["CLAUDE_BRIDGE_CACHE_DIR"]) / "sessions"
    return Path.home() / ".cache" / "nulm" / "sessions"


def _ensure_sessions_dir() -> Path:
    d = _sessions_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_workflow_session(
    session_id: str,
    state: str,
    steps: list[dict[str, Any]],
    current_step: int,
    task: str,
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Save a workflow session for later resume."""
    session_data = {
        "session_id": session_id,
        "state": state,
        "steps": steps,
        "current_step": current_step,
        "task": task,
        "metadata": metadata or {},
        "saved_at": time.time(),
    }
    session_file = _ensure_sessions_dir() / f"{session_id}.json"
    session_file.write_text(json.dumps(session_data, indent=2, ensure_ascii=False))
    return session_file


def load_workflow_session(session_id: str) -> dict[str, Any] | None:
    """Load a saved workflow session."""
    session_file = _ensure_sessions_dir() / f"{session_id}.json"
    if not session_file.exists():
        return None
    try:
        data = json.loads(session_file.read_text(encoding="utf-8"))
        return cast(dict[str, Any], data) if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def list_workflow_sessions() -> list[dict[str, Any]]:
    """List all saved workflow sessions."""
    sessions_dir = _ensure_sessions_dir()
    sessions = []
    for f in sessions_dir.glob("*.json"):
        try:
            sess = json.loads(f.read_text(encoding="utf-8"))
            sess["_file"] = str(f)
            sessions.append(sess)
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(sessions, key=lambda s: s.get("saved_at", 0), reverse=True)


def delete_workflow_session(session_id: str) -> bool:
    """Delete a workflow session."""
    session_file = _ensure_sessions_dir() / f"{session_id}.json"
    if session_file.exists():
        session_file.unlink()
        return True
    return False


def latest_session_id() -> str | None:
    """Get the most recent session ID."""
    sessions = list_workflow_sessions()
    if sessions:
        return sessions[0].get("session_id")
    return None


def session_summary(session: dict[str, Any]) -> str:
    """Format a session summary string."""
    state = session.get("state", "unknown")
    task = session.get("task", "unknown")
    current = session.get("current_step", 0)
    total = len(session.get("steps", []))
    saved = session.get("saved_at", 0)
    age = ""
    if saved:
        age = f" ({_format_age(saved)})"
    return f"[{state}] step {current}/{total} — {task[:50]}{age}"


def _format_age(timestamp: float) -> str:
    """Format a timestamp as relative time."""
    delta = time.time() - timestamp
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"
