"""Benchmark scheduling and cron-like automation."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def _default_schedule_dir() -> Path:
    if os.environ.get("CLAUDE_BRIDGE_CACHE_DIR"):
        return Path(os.environ["CLAUDE_BRIDGE_CACHE_DIR"]) / "schedules"
    return Path.home() / ".cache" / "claude-bridge" / "schedules"


def _ensure_schedule_dir() -> Path:
    d = _default_schedule_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _parse_cron_expr(cron_expr: str) -> dict[str, Any]:
    """Parse a simple cron expression: min hour day month weekday."""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError("Cron expression must have 5 fields: min hour day month weekday")
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "weekday": parts[4],
    }


def _matches_cron_part(value: int, part: str) -> bool:
    """Check if a value matches a cron part (number, *, or comma-separated)."""
    if part == "*":
        return True
    if "," in part:
        return any(_matches_cron_part(value, p.strip()) for p in part.split(","))
    if "/" in part:
        base, step = part.split("/")
        base = int(base) if base != "*" else 0
        step = int(step)
        return (value - base) % step == 0
    if "-" in part:
        start, end = part.split("-")
        return int(start) <= value <= int(end)
    return value == int(part)


def should_run_now(schedule: dict[str, Any]) -> bool:
    """Check if a schedule should run now based on current time."""
    import datetime

    now = datetime.datetime.now()
    parts = schedule.get("cron", schedule)
    if isinstance(parts, str):
        parts = _parse_cron_expr(parts)

    minute = now.minute
    hour = now.hour
    day = now.day
    month = now.month
    weekday = now.weekday()

    return (
        _matches_cron_part(minute, parts.get("minute", "*"))
        and _matches_cron_part(hour, parts.get("hour", "*"))
        and _matches_cron_part(day, parts.get("day", "*"))
        and _matches_cron_part(month, parts.get("month", "*"))
        and _matches_cron_part(weekday, parts.get("weekday", "*"))
    )


def save_benchmark_schedule(
    name: str,
    cron_expr: str,
    project_dir: Path,
    query: str,
    path: str = ".",
    limit: int = 5,
    repeats: int = 3,
    baseline_file: Path | None = None,
) -> Path:
    """Save a recurring benchmark schedule."""
    schedule = {
        "name": name,
        "cron": _parse_cron_expr(cron_expr),
        "project_dir": str(project_dir.resolve()),
        "query": query,
        "path": path,
        "limit": limit,
        "repeats": repeats,
        "baseline_file": str(baseline_file.resolve()) if baseline_file else None,
        "last_run": None,
        "last_result": None,
        "created_at": time.time(),
    }
    schedule_dir = _ensure_schedule_dir()
    schedule_file = schedule_dir / f"{name}.json"
    schedule_file.write_text(json.dumps(schedule, indent=2, ensure_ascii=False))
    return schedule_file


def load_benchmark_schedule(name: str) -> dict[str, Any] | None:
    """Load a benchmark schedule by name."""
    schedule_file = _ensure_schedule_dir() / f"{name}.json"
    if not schedule_file.exists():
        return None
    try:
        return json.loads(schedule_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_benchmark_schedules() -> list[dict[str, Any]]:
    """List all saved benchmark schedules."""
    schedule_dir = _ensure_schedule_dir()
    schedules = []
    for f in schedule_dir.glob("*.json"):
        try:
            sched = json.loads(f.read_text(encoding="utf-8"))
            sched["_file"] = str(f)
            schedules.append(sched)
        except (OSError, json.JSONDecodeError):
            continue
    return schedules


def delete_benchmark_schedule(name: str) -> bool:
    """Delete a benchmark schedule."""
    schedule_file = _ensure_schedule_dir() / f"{name}.json"
    if schedule_file.exists():
        schedule_file.unlink()
        return True
    return False


def run_scheduled_benchmark(schedule: dict[str, Any]) -> dict[str, Any]:
    """Run a benchmark from a schedule."""
    from claude_bridge.benchmarking import run_index_and_relevance_benchmark

    project_dir = Path(schedule["project_dir"])
    query = schedule["query"]
    path = schedule.get("path", ".")
    limit = schedule.get("limit", 5)
    repeats = schedule.get("repeats", 3)
    baseline_file = Path(schedule["baseline_file"]) if schedule.get("baseline_file") else None

    try:
        result = run_index_and_relevance_benchmark(
            project_dir=project_dir,
            path=path,
            query=query,
            limit=limit,
            repeats=repeats,
            clear_cache=False,
        )

        if baseline_file and baseline_file.exists():
            from claude_bridge.benchmarking import compare_benchmark_to_baseline

            comparison = compare_benchmark_to_baseline(result, baseline_file)
            result["comparison"] = comparison

        schedule["last_run"] = time.time()
        schedule["last_result"] = result

        schedule_file = Path(_ensure_schedule_dir()) / f"{schedule['name']}.json"
        schedule_file.write_text(json.dumps(schedule, indent=2, ensure_ascii=False))

        return result
    except Exception as exc:
        return {"error": str(exc), "schedule": schedule["name"]}


def check_and_run_due_benchmarks() -> list[dict[str, Any]]:
    """Check all schedules and run any that are due."""
    results = []
    for sched in list_benchmark_schedules():
        if should_run_now(sched):
            result = run_scheduled_benchmark(sched)
            results.append(result)
    return results
