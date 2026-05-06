"""Cross-session behavioral baseline helpers for anomaly detection."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_COMMAND_TOOLS = {"run_shell", "start_process"}
_PATH_KEYS = {"file", "path", "source", "destination", "target", "from_path", "to_path"}


def _tool_name(record: dict[str, Any]) -> str:
    value = record.get("tool_name")
    return value.strip() if isinstance(value, str) else ""


def _command_prefix(command: str) -> str:
    parts = command.strip().split()
    if not parts:
        return ""
    if len(parts) >= 2 and parts[0] in {"python", "python3"} and parts[1] == "-m":
        return " ".join(parts[:3])
    if len(parts) >= 2 and parts[0] in {"npm", "pnpm", "yarn", "git"}:
        return " ".join(parts[:2])
    return parts[0]


def _record_command_prefixes(record: dict[str, Any]) -> set[str]:
    if _tool_name(record) not in _COMMAND_TOOLS:
        return set()
    params = record.get("params", {})
    if not isinstance(params, dict):
        return set()
    command = params.get("command")
    if not isinstance(command, str):
        return set()
    prefix = _command_prefix(command)
    return {prefix} if prefix else set()


def _path_root(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    if not normalized:
        return ""
    if normalized.startswith("/"):
        parts = [part for part in normalized.split("/") if part]
        return f"/{parts[0]}" if parts else "/"
    return normalized.split("/", 1)[0]


def _record_path_roots(record: dict[str, Any]) -> set[str]:
    params = record.get("params", {})
    if not isinstance(params, dict):
        return set()
    roots: set[str] = set()
    for key in _PATH_KEYS:
        value = params.get(key)
        if isinstance(value, str):
            root = _path_root(value)
            if root:
                roots.add(root)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    root = _path_root(item)
                    if root:
                        roots.add(root)
    return roots


def build_baseline_from_records(
    records: list[dict[str, Any]],
    *,
    session_count: int = 1,
) -> dict[str, Any]:
    """Build a compact behavioral baseline from audit records."""
    tool_counts: dict[str, int] = {}
    command_prefixes: set[str] = set()
    path_roots: set[str] = set()
    active_hours: set[int] = set()

    for record in records:
        tool = _tool_name(record)
        if tool:
            tool_counts[tool] = tool_counts.get(tool, 0) + 1
        command_prefixes.update(_record_command_prefixes(record))
        path_roots.update(_record_path_roots(record))
        timestamp = record.get("timestamp")
        if isinstance(timestamp, str):
            try:
                hour = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).hour
            except ValueError:
                continue
            active_hours.add(hour)

    safe_session_count = max(1, session_count)
    return {
        "version": 1,
        "session_count": safe_session_count,
        "record_count": len(records),
        "avg_records_per_session": round(len(records) / safe_session_count, 3),
        "tool_counts": tool_counts,
        "command_prefixes": sorted(command_prefixes),
        "path_roots": sorted(path_roots),
        "active_hours": sorted(active_hours),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def merge_baseline(
    existing: dict[str, Any] | None,
    new_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge new records into an existing baseline."""
    if not existing:
        return build_baseline_from_records(new_records, session_count=1)

    previous_records = int(existing.get("record_count", 0) or 0)
    previous_sessions = int(existing.get("session_count", 0) or 0)
    new_baseline = build_baseline_from_records(new_records, session_count=1)
    session_count = max(1, previous_sessions + 1)
    record_count = previous_records + len(new_records)

    tool_counts = dict(existing.get("tool_counts", {}))
    for tool, count in new_baseline["tool_counts"].items():
        tool_counts[tool] = int(tool_counts.get(tool, 0) or 0) + int(count)

    return {
        "version": 1,
        "session_count": session_count,
        "record_count": record_count,
        "avg_records_per_session": round(record_count / session_count, 3),
        "tool_counts": tool_counts,
        "command_prefixes": sorted(
            set(existing.get("command_prefixes", [])) | set(new_baseline["command_prefixes"])
        ),
        "path_roots": sorted(set(existing.get("path_roots", [])) | set(new_baseline["path_roots"])),
        "active_hours": sorted(
            set(existing.get("active_hours", [])) | set(new_baseline["active_hours"])
        ),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def load_baseline(path: Path) -> dict[str, Any] | None:
    """Load a baseline JSON file, returning None if unavailable or invalid."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def save_baseline(path: Path, baseline: dict[str, Any]) -> None:
    """Persist a baseline JSON file with private file permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline, indent=2, sort_keys=True), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
