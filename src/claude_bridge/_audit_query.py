"""Audit record querying and session summarization."""

from __future__ import annotations

from typing import Any

from claude_bridge.anomaly import compute_anomaly_scores
from claude_bridge._audit_core import (
    latest_session_id,
    current_session_id,
    _load_records,
    _load_records_at_offsets,
)
from claude_bridge._audit_index import load_audit_index
from claude_bridge._audit_activity import (
    filter_audit_records,
    build_activity_summary,
)
from claude_bridge._audit_query_parser import AuditQueryParser, AuditQueryAST, QueryError

_VALID_DECISION_ACTIONS = {"allow", "deny", "ask"}
_VALID_DECISION_SOURCES = {"default", "builtin_guard", "rule", "approval", "ai"}
_VALID_RISK_LEVELS = {"low", "medium", "high", "critical"}


def _normalized_filter(value: str | None, valid: set[str]) -> str | None:
    if value is None:
        return None
    lowered = value.lower()
    return lowered if lowered in valid else "__invalid__"


def _filter_index_entries(
    entries: list[dict[str, Any]],
    *,
    tool_name: str | None = None,
    ok: bool | None = None,
    decision_action: str | None = None,
    decision_source: str | None = None,
    decision_risk_level: str | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    action = _normalized_filter(decision_action, _VALID_DECISION_ACTIONS)
    source = _normalized_filter(decision_source, _VALID_DECISION_SOURCES)
    risk = _normalized_filter(decision_risk_level, _VALID_RISK_LEVELS)
    if "__invalid__" in {action, source, risk}:
        return []

    filtered: list[dict[str, Any]] = []
    for entry in entries:
        if tool_name is not None and entry.get("tool_name") != tool_name:
            continue
        if ok is not None and bool(entry.get("ok", False)) != ok:
            continue
        if since is not None and str(entry.get("timestamp") or "") < since:
            continue
        if action is not None and entry.get("decision_action") != action:
            continue
        if source is not None and entry.get("decision_source") != source:
            continue
        if risk is not None and entry.get("decision_risk_level") != risk:
            continue
        filtered.append(entry)
    return filtered


def get_recent_tool_calls(
    *,
    limit: int = 20,
    tool_name: str | None = None,
    session_id: str | None = None,
    ok: bool | None = None,
    decision_action: str | None = None,
    decision_source: str | None = None,
    decision_risk_level: str | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    """Return recent tool calls with optional filters.

    All filter parameters are optional and backwards-compatible.  When
    provided they are delegated to :func:`filter_audit_records`.
    """
    selected_session_id = session_id or latest_session_id() or current_session_id()
    index_entries = load_audit_index(selected_session_id)
    if index_entries:
        filtered_entries = _filter_index_entries(
            index_entries,
            tool_name=tool_name,
            ok=ok,
            decision_action=decision_action,
            decision_source=decision_source,
            decision_risk_level=decision_risk_level,
            since=since,
        )
        total_after_filter = len(filtered_entries)
        limited_entries = list(reversed(filtered_entries))[: max(1, limit)]
        records = _load_records_at_offsets(
            selected_session_id,
            [int(entry["offset"]) for entry in limited_entries],
        )
        return {
            "session_id": selected_session_id,
            "records": records,
            "total_records": total_after_filter,
            "returned_records": len(records),
            "query_strategy": "audit_index",
        }

    records = _load_records(selected_session_id)
    has_advanced_filter = any(
        param is not None
        for param in (ok, decision_action, decision_source, decision_risk_level, since)
    )
    if has_advanced_filter:
        records = filter_audit_records(
            records,
            tool_name=tool_name,
            ok=ok,
            decision_action=decision_action,
            decision_source=decision_source,
            decision_risk_level=decision_risk_level,
            since=since,
        )
        total_after_filter = len(records)
    else:
        if tool_name:
            records = [record for record in records if record.get("tool_name") == tool_name]
        total_after_filter = len(records)
    records = list(reversed(records))
    limited = records[: max(1, limit)]
    return {
        "session_id": selected_session_id,
        "records": limited,
        "total_records": total_after_filter,
        "returned_records": len(limited),
        "query_strategy": "linear_scan",
    }


def summarize_session(
    session_id: str | None = None,
    *,
    limit: int = 20,
    tool_name: str | None = None,
    ok: bool | None = None,
    decision_action: str | None = None,
    decision_source: str | None = None,
    decision_risk_level: str | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    recent = get_recent_tool_calls(
        limit=limit,
        tool_name=tool_name,
        session_id=session_id,
        ok=ok,
        decision_action=decision_action,
        decision_source=decision_source,
        decision_risk_level=decision_risk_level,
        since=since,
    )
    counts: dict[str, int] = {}
    failure_count = 0
    total_duration_ms = 0.0
    total_input_chars = 0
    total_output_chars = 0
    total_estimated_tokens = 0
    truncated_results = 0
    tool_token_totals: dict[str, int] = {}
    for record in recent["records"]:
        tool_name = str(record.get("tool_name", "unknown"))
        counts[tool_name] = counts.get(tool_name, 0) + 1
        total_duration_ms += float(record.get("duration_ms", 0.0) or 0.0)
        result = record.get("result", {})
        if isinstance(result, dict) and not result.get("ok", False):
            failure_count += 1
        telemetry = record.get("telemetry", {})
        if isinstance(telemetry, dict):
            input_chars = int(telemetry.get("input_chars", 0) or 0)
            output_chars = int(telemetry.get("output_chars", 0) or 0)
            estimated_total_tokens = int(telemetry.get("estimated_total_tokens", 0) or 0)
            total_input_chars += input_chars
            total_output_chars += output_chars
            total_estimated_tokens += estimated_total_tokens
            tool_token_totals[tool_name] = (
                tool_token_totals.get(tool_name, 0) + estimated_total_tokens
            )
            if telemetry.get("result_truncated") is True:
                truncated_results += 1
    anomaly_result = compute_anomaly_scores(recent["records"])

    return {
        "session_id": recent["session_id"],
        "recent_records": recent["records"],
        "total_records": recent["total_records"],
        "returned_records": recent["returned_records"],
        "tool_counts": counts,
        "failure_count": failure_count,
        "activity": build_activity_summary(recent["records"]),
        "anomaly_counts": anomaly_result["anomaly_counts"],
        "telemetry": {
            "total_duration_ms": round(total_duration_ms, 3),
            "avg_duration_ms": round(total_duration_ms / max(1, len(recent["records"])), 3),
            "total_input_chars": total_input_chars,
            "total_output_chars": total_output_chars,
            "total_estimated_tokens": total_estimated_tokens,
"truncated_results": truncated_results,
            "tool_estimated_tokens": tool_token_totals,
        },
    }


def query_audit(
    query: str,
    session_id: str | None = None,
    *,
    limit: int = 100,
) -> dict[str, Any]:
    """Execute a SQL-like query against the audit trail.

    Args:
        query: SQL-like query string (e.g., "SELECT tool_name WHERE ok = true LIMIT 10")
        session_id: Session to query. Defaults to current/last session.
        limit: Maximum records to return (default 100). Acts as a safety ceiling.

    Returns:
        Dictionary with keys: session_id, records, total_records, returned_records,
        query_strategy, parsed_query (AST summary)

    Supported syntax:
        SELECT <fields>     -- comma-separated, default: *
        WHERE <conditions>  -- field op value, supports AND/OR
        ORDER BY <field> [ASC|DESC]
        LIMIT <n>

    Supported fields: tool_name, ok, decision_action, decision_source,
                      decision_risk_level, timestamp, duration_ms, session_id

    Supported operators: =, !=, >, <, >=, <=, LIKE, LIKE%, %LIKE, %LIKE%

    ReDoS protection is applied to LIKE patterns using the same validation
    as guard_policy.py.

    Raises:
        QueryError: If the query is malformed, contains invalid fields,
                    or has unsafe LIKE patterns.

    Example:
        >>> query_audit("SELECT tool_name WHERE decision_action = 'deny' LIMIT 20")
        >>> query_audit("WHERE ok = false ORDER BY timestamp DESC LIMIT 50")
    """
    selected_session_id = session_id or latest_session_id() or current_session_id()

    # Parse query with ReDoS protection
    parser = AuditQueryParser()
    try:
        ast = parser.parse(query)
    except QueryError:
        raise
    except Exception as exc:
        raise QueryError(f"Failed to parse query: {exc}") from exc

    # Enforce absolute limit
    if ast.limit is not None and ast.limit > limit:
        ast = AuditQueryAST(
            select_fields=ast.select_fields,
            where=ast.where,
            order_by=ast.order_by,
            limit=limit,
        )

    # Try index-based query first using existing filter infrastructure
    index_entries = load_audit_index(selected_session_id)

    if index_entries:
        # Map WHERE conditions to index filter parameters
        tool_name = None
        ok = None
        decision_action = None
        decision_source = None
        decision_risk_level = None

        if ast.where:
            for cond in ast.where.conditions:
                if cond.field == "tool_name":
                    tool_name = str(cond.value)
                elif cond.field == "ok":
                    ok = bool(cond.value) if isinstance(cond.value, bool) else None
                elif cond.field == "decision_action":
                    decision_action = str(cond.value)
                elif cond.field == "decision_source":
                    decision_source = str(cond.value)
                elif cond.field == "decision_risk_level":
                    decision_risk_level = str(cond.value)

        # Check if we can use index (simple equality filters only)
        if ast.where and all(
            c.operator == "=" for c in ast.where.conditions
        ):
            filtered_entries = _filter_index_entries(
                index_entries,
                tool_name=tool_name,
                ok=ok,
                decision_action=decision_action,
                decision_source=decision_source,
                decision_risk_level=decision_risk_level,
            )
            total_after_filter = len(filtered_entries)

            # Apply ordering and limit from parsed AST
            if ast.order_by:
                reverse = ast.order_by.direction.value == "DESC"
                filtered_entries = sorted(
                    filtered_entries,
                    key=lambda e: e.get(ast.order_by.field, ""),
                    reverse=reverse,
                )

            actual_limit = ast.limit if ast.limit is not None else limit
            limited_entries = list(reversed(filtered_entries))[: actual_limit]

            records = _load_records_at_offsets(
                selected_session_id,
                [int(entry["offset"]) for entry in limited_entries],
            )
            return {
                "session_id": selected_session_id,
                "records": records,
                "total_records": total_after_filter,
                "returned_records": len(records),
                "query_strategy": "audit_index",
                "parsed_query": {
                    "select_fields": ast.select_fields if ast.select_fields else ["*"],
                    "where": (
                        [(c.field, c.operator, c.value) for c in ast.where.conditions]
                        if ast.where else []
                    ),
                    "order_by": (
                        (ast.order_by.field, ast.order_by.direction.value)
                        if ast.order_by else None
                    ),
                    "limit": actual_limit,
                },
            }

    # Fall back to loading all records and applying parser
    records = _load_records(selected_session_id)
    filtered_records = parser.execute(ast, records)
    total_after_filter = len(filtered_records)

    # Apply built-in limit
    actual_limit = ast.limit if ast.limit is not None else limit
    limited_records = filtered_records[:actual_limit]

    return {
        "session_id": selected_session_id,
        "records": limited_records,
        "total_records": total_after_filter,
        "returned_records": len(limited_records),
        "query_strategy": "linear_scan",
        "parsed_query": {
            "select_fields": ast.select_fields if ast.select_fields else ["*"],
            "where": (
                [(c.field, c.operator, c.value) for c in ast.where.conditions]
                if ast.where else []
            ),
            "order_by": (
                (ast.order_by.field, ast.order_by.direction.value)
                if ast.order_by else None
            ),
            "limit": actual_limit,
        },
    }
