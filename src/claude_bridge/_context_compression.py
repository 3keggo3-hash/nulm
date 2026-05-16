"""Context compression utilities for reducing context window usage."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any

from claude_bridge._audit_core import _load_records, current_session_id
from claude_bridge.anomaly import compute_anomaly_scores

# Decompression bomb protection limits
_MAX_COMPRESSION_RATIO = 1000  # 1MB compressed → 1GB decompressed max
_COMPRESSION_SIZE_LIMIT = 100 * 1024 * 1024  # 100MB max decompressed size


def validate_compression_ratio(compressed_size: int, decompressed_size: int) -> None:
    """Validate that decompressed data doesn't exceed safe limits.

    Raises:
        ValueError: If decompressed size exceeds safe limits or ratio is too high.
    """
    if decompressed_size > _COMPRESSION_SIZE_LIMIT:
        raise ValueError(
            f"Decompressed size {decompressed_size:,} bytes exceeds limit of "
            f"{_COMPRESSION_SIZE_LIMIT:,} bytes"
        )
    if compressed_size > 0:
        ratio = decompressed_size / compressed_size
        if ratio > _MAX_COMPRESSION_RATIO:
            raise ValueError(
                f"Compression ratio {ratio:.1f}x "
                f"(size {decompressed_size:,} bytes from {compressed_size:,} bytes) "
                f"exceeds maximum allowed ratio {_MAX_COMPRESSION_RATIO}x"
            )


class _LRUCache:
    """Simple in-memory LRU cache with TTL."""

    def __init__(self, max_size: int = 50, ttl_seconds: float = 60.0) -> None:
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds

    def get(self, key: str) -> Any | None:
        if key not in self._cache:
            return None
        value, timestamp = self._cache[key]
        if time.monotonic() - timestamp > self._ttl:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = (value, time.monotonic())
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)


_compress_cache = _LRUCache(max_size=50, ttl_seconds=60.0)


def compress_session(session_id: str) -> str:
    """Return a compact text summary of a session for context window reduction.

    Args:
        session_id: The session identifier.

    Returns:
        A compact single-paragraph summary covering tools used, file operations,
        shell commands, failure count, and anomaly signals.
    """
    if not session_id:
        session_id = current_session_id()

    cached = _compress_cache.get(session_id)
    if cached is not None:
        return cached

    records = _load_records(session_id)
    if not records:
        result = f"Session {session_id}: no records found."
        _compress_cache.set(session_id, result)
        return result

    tool_counts: dict[str, int] = {}
    file_ops: list[str] = []
    shell_cmds: list[str] = []
    failures = 0
    for record in records:
        tool = str(record.get("tool_name", "unknown"))
        tool_counts[tool] = tool_counts.get(tool, 0) + 1
        params = record.get("params", {})
        if isinstance(params, dict):
            path = params.get("path") or params.get("file")
            if path and tool in (
                "read_file",
                "write_file",
                "patch_file",
                "move_file",
                "copy_path",
            ):
                file_ops.append(str(path))
            cmd = params.get("command")
            if cmd and tool in ("run_shell", "start_process"):
                shell_cmds.append(str(cmd)[:60])
        result = record.get("result", {})
        if isinstance(result, dict) and not result.get("ok", False):
            failures += 1

    anomaly_result = compute_anomaly_scores(records)
    anomaly_count = sum(anomaly_result.get("anomaly_counts", {}).values())

    lines = [f"Session {session_id} summary:"]
    if tool_counts:
        top_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        tools_str = ", ".join(f"{t}[{c}]" for t, c in top_tools)
        lines.append(f"Tools: {tools_str}")
    if file_ops:
        unique_files = sorted(set(file_ops))[:10]
        files_str = ", ".join(unique_files)
        lines.append(f"Files: {files_str}")
    if shell_cmds:
        unique_cmds = sorted(set(shell_cmds))[:5]
        cmds_str = "; ".join(unique_cmds)
        lines.append(f"Commands: {cmds_str}")
    lines.append(f"Failures: {failures}/{len(records)}")
    if anomaly_count > 0:
        lines.append(f"Anomalies: {anomaly_count}")

    summary = " | ".join(lines)
    validate_compression_ratio(len(records), len(summary))
    _compress_cache.set(session_id, summary)
    return summary


def summarize_audit_records(records: list[dict[str, Any]]) -> str:
    """Return a compact narrative summary of a list of audit records.

    Focuses on outcomes, file touched, commands run, and any policy decisions.

    Args:
        records: List of audit record dictionaries.

    Returns:
        A compact multi-line summary string.
    """
    if not records:
        return "No records to summarize."

    tool_counts: dict[str, int] = {}
    touched_paths: list[str] = []
    commands: list[str] = []
    decisions: list[str] = []
    failures = 0
    total_input_chars = 0
    total_output_chars = 0
    total_tokens = 0

    for record in records:
        tool = str(record.get("tool_name", "unknown"))
        tool_counts[tool] = tool_counts.get(tool, 0) + 1

        params = record.get("params", {})
        if isinstance(params, dict):
            path = params.get("path") or params.get("file")
            if path:
                touched_paths.append(str(path))
            cmd = params.get("command")
            if cmd:
                commands.append(str(cmd)[:80])

        result = record.get("result", {})
        if isinstance(result, dict):
            decision_action = (
                result.get("decision", {}).get("action")
                if isinstance(result.get("decision"), dict)
                else None
            )
            if decision_action:
                decisions.append(decision_action)
            if not result.get("ok", False):
                failures += 1

        telemetry = record.get("telemetry", {})
        if isinstance(telemetry, dict):
            total_input_chars += int(telemetry.get("input_chars", 0) or 0)
            total_output_chars += int(telemetry.get("output_chars", 0) or 0)
            total_tokens += int(telemetry.get("estimated_total_tokens", 0) or 0)

    lines: list[str] = []
    total = len(records)
    lines.append(f"Records: {total} | Failures: {failures}")

    if tool_counts:
        sorted_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)
        top = sorted_tools[:6]
        tools_str = ", ".join(f"{t}({c})" for t, c in top)
        lines.append(f"Tools: {tools_str}")

    if touched_paths:
        unique_paths = sorted(set(touched_paths))
        paths_str = ", ".join(unique_paths[:15])
        if len(unique_paths) > 15:
            paths_str += f" ... +{len(unique_paths) - 15} more"
        lines.append(f"Paths: {paths_str}")

    if commands:
        unique_cmds = sorted(set(commands))
        cmds_str = "; ".join(unique_cmds[:5])
        if len(unique_cmds) > 5:
            cmds_str += f" ... +{len(unique_cmds) - 5} more"
        lines.append(f"Commands: {cmds_str}")

    if decisions:
        decision_counts: dict[str, int] = {}
        for d in decisions:
            decision_counts[d] = decision_counts.get(d, 0) + 1
        dec_str = ", ".join(f"{a}:{c}" for a, c in decision_counts.items())
        lines.append(f"Decisions: {dec_str}")

    lines.append(
        f"Tokens: in={total_input_chars:,} chars, out={total_output_chars:,} chars, "
        f"est={total_tokens:,}"
    )

    return "\n".join(lines)


def get_session_stats(session_id: str) -> dict[str, Any]:
    """Return per-session token usage and telemetry statistics.

    Args:
        session_id: The session identifier. Uses current session if empty.

    Returns:
        A dictionary with session_id, record counts, token estimates,
        per-tool token breakdown, and anomaly summary.
    """
    if not session_id:
        session_id = current_session_id()
    records = _load_records(session_id)

    tool_counts: dict[str, int] = {}
    tool_input_chars: dict[str, int] = {}
    tool_output_chars: dict[str, int] = {}
    tool_tokens: dict[str, int] = {}
    total_input_chars = 0
    total_output_chars = 0
    total_tokens = 0
    total_duration_ms = 0.0
    failures = 0
    truncated = 0

    for record in records:
        tool = str(record.get("tool_name", "unknown"))
        tool_counts[tool] = tool_counts.get(tool, 0) + 1

        total_duration_ms += float(record.get("duration_ms", 0.0) or 0.0)

        result = record.get("result", {})
        if isinstance(result, dict) and not result.get("ok", False):
            failures += 1

        telemetry = record.get("telemetry", {})
        if isinstance(telemetry, dict):
            in_chars = int(telemetry.get("input_chars", 0) or 0)
            out_chars = int(telemetry.get("output_chars", 0) or 0)
            tokens = int(telemetry.get("estimated_total_tokens", 0) or 0)
            total_input_chars += in_chars
            total_output_chars += out_chars
            total_tokens += tokens
            tool_input_chars[tool] = tool_input_chars.get(tool, 0) + in_chars
            tool_output_chars[tool] = tool_output_chars.get(tool, 0) + out_chars
            tool_tokens[tool] = tool_tokens.get(tool, 0) + tokens
            if telemetry.get("result_truncated") is True:
                truncated += 1

    anomaly_result = compute_anomaly_scores(records)

    return {
        "session_id": session_id,
        "total_records": len(records),
        "tool_counts": tool_counts,
        "failures": failures,
        "truncated_results": truncated,
        "duration_ms": round(total_duration_ms, 3),
        "telemetry": {
            "total_input_chars": total_input_chars,
            "total_output_chars": total_output_chars,
            "total_estimated_tokens": total_tokens,
            "avg_tokens_per_record": (
                round(total_tokens / max(1, len(records)), 1) if records else 0
            ),
            "tool_estimated_tokens": tool_tokens,
            "tool_input_chars": tool_input_chars,
            "tool_output_chars": tool_output_chars,
        },
        "anomaly_counts": anomaly_result.get("anomaly_counts", {}),
    }
