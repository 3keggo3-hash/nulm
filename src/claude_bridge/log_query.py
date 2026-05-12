"""Log query and aggregation system for Claude Bridge audit logs."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from claude_bridge._audit_core import _audit_dir


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class AggregationFunc(str, Enum):
    COUNT = "count"
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"


@dataclass
class LogQuery:
    start_time: datetime | None = None
    end_time: datetime | None = None
    level: LogLevel | None = None
    pattern: str | None = None
    tool_name: str | None = None
    user_goal: str | None = None
    limit: int = 100
    offset: int = 0


@dataclass
class LogEntry:
    timestamp: datetime
    level: LogLevel
    message: str
    tool_name: str | None = None
    duration_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AggregationResult:
    func: AggregationFunc
    field: str
    value: float | int
    count: int = 0


class LogQueryEngine:
    def __init__(self, audit_dir: Path | None = None) -> None:
        self._audit_dir = audit_dir or _audit_dir()
        self._cache: dict[str, tuple[list[LogEntry], datetime]] = {}
        self._cache_ttl = 60.0
        self._lock = threading.Lock()

    def query(self, query: LogQuery) -> list[LogEntry]:
        entries = self._load_entries()
        filtered = self._filter_entries(entries, query)
        sorted_entries = sorted(filtered, key=lambda e: e.timestamp, reverse=True)
        return sorted_entries[query.offset : query.offset + query.limit]

    def count(self, query: LogQuery) -> int:
        entries = self._load_entries()
        filtered = self._filter_entries(entries, query)
        return len(filtered)

    def aggregate(self, query: LogQuery, field: str, func: AggregationFunc) -> AggregationResult:
        entries = self._load_entries()
        filtered = self._filter_entries(entries, query)
        values: list[float] = []
        for entry in filtered:
            if field == "duration_ms" and entry.duration_ms is not None:
                values.append(entry.duration_ms)
            elif field == "count":
                values.append(1.0)
        if not values:
            return AggregationResult(func=func, field=field, value=0, count=0)
        result_value: float | int
        if func == AggregationFunc.COUNT:
            result_value = len(values)
        elif func == AggregationFunc.SUM:
            result_value = sum(values)
        elif func == AggregationFunc.AVG:
            result_value = sum(values) / len(values)
        elif func == AggregationFunc.MIN:
            result_value = min(values)
        elif func == AggregationFunc.MAX:
            result_value = max(values)
        else:
            result_value = len(values)
        return AggregationResult(func=func, field=field, value=result_value, count=len(values))

    def group_by(
        self, query: LogQuery, group_field: str
    ) -> dict[str, list[LogEntry]]:
        entries = self._load_entries()
        filtered = self._filter_entries(entries, query)
        groups: dict[str, list[LogEntry]] = {}
        for entry in filtered:
            key: str
            if group_field == "tool_name":
                key = entry.tool_name or "unknown"
            elif group_field == "level":
                key = entry.level.value
            elif group_field == "hour":
                key = entry.timestamp.strftime("%Y-%m-%d %H:00")
            elif group_field == "date":
                key = entry.timestamp.strftime("%Y-%m-%d")
            else:
                key = "unknown"
            if key not in groups:
                groups[key] = []
            groups[key].append(entry)
        return groups

    def _load_entries(self) -> list[LogEntry]:
        cache_key = str(self._audit_dir)
        entries: list[LogEntry] = []
        with self._lock:
            if cache_key in self._cache:
                cached_entries, cached_at = self._cache[cache_key]
                if (datetime.now() - cached_at).total_seconds() < self._cache_ttl:
                    return cached_entries
        if not self._audit_dir.exists():
            return entries
        for log_file in sorted(self._audit_dir.glob("*.jsonl")):
            try:
                entries.extend(self._parse_log_file(log_file))
            except Exception:
                pass
        with self._lock:
            self._cache[cache_key] = (entries, datetime.now())
        return entries

    def _parse_log_file(self, path: Path) -> list[LogEntry]:
        entries: list[LogEntry] = []
        import json

        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                timestamp = datetime.fromisoformat(data.get("timestamp", datetime.now().isoformat()))
                level_str = data.get("level", "info")
                try:
                    level = LogLevel(level_str.lower())
                except ValueError:
                    level = LogLevel.INFO
                entry = LogEntry(
                    timestamp=timestamp,
                    level=level,
                    message=data.get("message", ""),
                    tool_name=data.get("tool_name"),
                    duration_ms=data.get("duration_ms"),
                    metadata=data.get("metadata", {}),
                )
                entries.append(entry)
            except Exception:
                pass
        return entries

    def _filter_entries(self, entries: list[LogEntry], query: LogQuery) -> list[LogEntry]:
        filtered = entries
        if query.start_time:
            filtered = [e for e in filtered if e.timestamp >= query.start_time]
        if query.end_time:
            filtered = [e for e in filtered if e.timestamp <= query.end_time]
        if query.level:
            filtered = [e for e in filtered if e.level == query.level]
        if query.pattern:
            pattern = re.compile(query.pattern, re.IGNORECASE)
            filtered = [e for e in filtered if pattern.search(e.message)]
        if query.tool_name:
            filtered = [e for e in filtered if e.tool_name == query.tool_name]
        if query.user_goal:
            filtered = [
                e for e in filtered if query.user_goal.lower() in e.message.lower()
            ]
        return filtered


_LOG_QUERY_ENGINE: LogQueryEngine | None = None
_ENGINE_LOCK = threading.Lock()


def get_log_query_engine() -> LogQueryEngine:
    global _LOG_QUERY_ENGINE
    with _ENGINE_LOCK:
        if _LOG_QUERY_ENGINE is None:
            _LOG_QUERY_ENGINE = LogQueryEngine()
        return _LOG_QUERY_ENGINE


def query_logs(
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    level: LogLevel | None = None,
    pattern: str | None = None,
    tool_name: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[LogEntry]:
    engine = get_log_query_engine()
    query = LogQuery(
        start_time=start_time,
        end_time=end_time,
        level=level,
        pattern=pattern,
        tool_name=tool_name,
        limit=limit,
        offset=offset,
    )
    return engine.query(query)


def aggregate_logs(
    field: str,
    func: AggregationFunc,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    level: LogLevel | None = None,
    tool_name: str | None = None,
) -> AggregationResult:
    engine = get_log_query_engine()
    query = LogQuery(
        start_time=start_time,
        end_time=end_time,
        level=level,
        tool_name=tool_name,
    )
    return engine.aggregate(query, field, func)


def get_log_stats() -> dict[str, Any]:
    engine = get_log_query_engine()
    entries = engine.query(LogQuery(limit=1000))
    if not entries:
        return {"total": 0, "by_level": {}, "by_tool": {}}
    by_level: dict[str, int] = {}
    by_tool: dict[str, int] = {}
    for entry in entries:
        level_key = entry.level.value
        by_level[level_key] = by_level.get(level_key, 0) + 1
        tool_key = entry.tool_name or "unknown"
        by_tool[tool_key] = by_tool.get(tool_key, 0) + 1
    return {
        "total": len(entries),
        "by_level": by_level,
        "by_tool": by_tool,
        "oldest": entries[-1].timestamp.isoformat() if entries else None,
        "newest": entries[0].timestamp.isoformat() if entries else None,
    }
