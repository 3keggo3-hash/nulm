"""Registration helpers for P6 meta-agent MCP tools."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import time
from typing import Any, Callable

from claude_bridge.config import active_role, active_user, project_dir
from claude_bridge.guard_policy import DecisionAction, ToolRequestContext
from claude_bridge.rules_engine import evaluate_runtime_policy_chain
from claude_bridge.tool_utils import require_approval

_MAX_REFLECT_RECURSION_DEPTH = 3
_MAX_META_REVIEW_ITEMS = 20


def _build_reflection_summary(records: list[dict[str, Any]], depth: int) -> dict[str, Any]:
    if depth >= _MAX_REFLECT_RECURSION_DEPTH:
        return {
            "truncated": True,
            "reason": "max_recursion_depth",
            "depth": depth,
        }
    tool_counts: dict[str, int] = {}
    error_count = 0
    total_latency = 0.0
    for rec in records:
        tn = rec.get("tool_name", "unknown")
        tool_counts[tn] = tool_counts.get(tn, 0) + 1
        if not rec.get("ok", True):
            error_count += 1
        total_latency += rec.get("duration_ms", 0.0)
    return {
        "truncated": False,
        "depth": depth,
        "tool_counts": tool_counts,
        "unique_tools": len(tool_counts),
        "error_count": error_count,
        "error_rate": round(error_count / max(len(records), 1), 3),
        "total_latency_ms": round(total_latency, 2),
        "avg_latency_ms": round(total_latency / max(len(records), 1), 2),
    }


def register_meta_agent_tools(
    *,
    mcp: Any,
    tool_options: Callable[..., dict[str, Any]],
    audit_tool_call: Callable[..., str],
    json_response: Callable[..., str],
    create_plan_impl: Callable[..., dict[str, Any]],
    execute_step_impl: Callable[..., dict[str, Any]],
    get_plan_status_impl: Callable[..., dict[str, Any]],
    explore_approaches_impl: Callable[..., dict[str, Any]],
    execute_approach_impl: Callable[..., dict[str, Any]],
    compare_approaches_impl: Callable[..., dict[str, Any]],
    self_critique_impl: Callable[..., dict[str, Any]],
    create_checkpoint_impl: Callable[..., dict[str, Any]],
    restore_checkpoint_impl: Callable[..., dict[str, Any]],
    list_checkpoints_impl: Callable[..., dict[str, Any]],
    get_recent_tool_calls_impl: Callable[..., dict[str, Any]] | None = None,
    enabled_names: set[str] | None = None,
) -> dict[str, Any]:
    _enabled = enabled_names
    results: dict[str, Any] = {}

    async def _require_mutating_meta_approval(tool_name: str, params: dict[str, Any]) -> str | None:
        policy_context = ToolRequestContext(
            tool_name=tool_name,
            params=params,
            project_dir=str(project_dir()),
            role=active_role(),
            user=active_user(),
        )
        rule_decision = evaluate_runtime_policy_chain(policy_context)
        if rule_decision is not None and rule_decision.action == DecisionAction.DENY:
            return json_response(
                False,
                rule_decision.reason,
                code="policy_denied",
                details=params,
                decision=rule_decision,
                decision_in_details=True,
            )
        if rule_decision is not None and rule_decision.action == DecisionAction.ALLOW:
            return None
        rejection = await require_approval(
            tool_name,
            params,
            rejection_message=(
                rule_decision.reason if rule_decision is not None else f"{tool_name} rejected"
            ),
            rejection_details=params,
        )
        if rejection is None:
            return None
        if rule_decision is None:
            return rejection
        return json_response(
            False,
            rule_decision.reason,
            code="approval_rejected",
            details=params,
            decision=rule_decision,
            decision_in_details=True,
        )

    if _enabled is None or "create_plan" in _enabled:

        @mcp.tool(
            **tool_options("Create an execution plan with a goal and steps.", destructive=True)
        )
        async def create_plan(goal: str, steps_json: str) -> str:
            started_at = time.perf_counter()
            impl_result = create_plan_impl(goal=goal, steps_json=steps_json)
            result = json_response(
                impl_result.get("ok", False),
                impl_result.get("error", impl_result.get("message", "Plan created")),
                details=impl_result,
            )
            return audit_tool_call(
                "create_plan",
                {"goal": goal, "steps_json_length": len(steps_json)},
                result,
                started_at=started_at,
            )

        results["create_plan"] = create_plan

    if _enabled is None or "execute_step" in _enabled:

        @mcp.tool(**tool_options("Execute a single step in an existing plan.", destructive=True))
        async def execute_step(plan_id: str, step_id: int) -> str:
            started_at = time.perf_counter()
            impl_result = execute_step_impl(plan_id=plan_id, step_id=step_id)
            result = json_response(
                impl_result.get("ok", False),
                impl_result.get("error", impl_result.get("message", "Step executed")),
                details=impl_result,
            )
            return audit_tool_call(
                "execute_step",
                {"plan_id": plan_id, "step_id": step_id},
                result,
                started_at=started_at,
            )

        results["execute_step"] = execute_step

    if _enabled is None or "get_plan_status" in _enabled:

        @mcp.tool(**tool_options("Get the full status of a plan by its plan_id.", read_only=True))
        async def get_plan_status(plan_id: str) -> str:
            started_at = time.perf_counter()
            impl_result = get_plan_status_impl(plan_id=plan_id)
            result = json_response(
                impl_result.get("ok", False),
                impl_result.get("error", impl_result.get("message", "Plan status loaded")),
                details=impl_result,
            )
            return audit_tool_call(
                "get_plan_status", {"plan_id": plan_id}, result, started_at=started_at
            )

        results["get_plan_status"] = get_plan_status

    if _enabled is None or "explore_approaches" in _enabled:

        @mcp.tool(
            **tool_options(
                "Explore alternative approaches for a programming problem.", destructive=True
            )
        )
        async def explore_approaches(problem: str, count: int = 3) -> str:
            started_at = time.perf_counter()
            impl_result = explore_approaches_impl(problem=problem, count=count)
            result = json_response(
                impl_result.get("ok", False),
                impl_result.get("message", "Approaches explored"),
                details=impl_result,
            )
            return audit_tool_call(
                "explore_approaches",
                {"problem": problem, "count": count},
                result,
                started_at=started_at,
            )

        results["explore_approaches"] = explore_approaches

    if _enabled is None or "execute_approach" in _enabled:

        @mcp.tool(
            **tool_options(
                "Execute a previously explored approach by its approach_id.", destructive=True
            )
        )
        async def execute_approach(approach_id: str) -> str:
            started_at = time.perf_counter()
            impl_result = execute_approach_impl(approach_id=approach_id)
            result = json_response(
                impl_result.get("ok", False),
                impl_result.get("message", "Approach executed"),
                details=impl_result,
            )
            return audit_tool_call(
                "execute_approach", {"approach_id": approach_id}, result, started_at=started_at
            )

        results["execute_approach"] = execute_approach

    if _enabled is None or "compare_approaches" in _enabled:

        @mcp.tool(**tool_options("Compare multiple approaches by their IDs.", read_only=True))
        async def compare_approaches(approach_ids_json: str) -> str:
            started_at = time.perf_counter()
            try:
                approach_ids = json.loads(approach_ids_json)
            except json.JSONDecodeError as exc:
                result = json_response(
                    False, "Invalid JSON for approach_ids", details={"error": str(exc)}
                )
                return audit_tool_call(
                    "compare_approaches",
                    {"approach_ids_json": approach_ids_json},
                    result,
                    started_at=started_at,
                )
            if not isinstance(approach_ids, list):
                result = json_response(False, "approach_ids must be a JSON array", details={})
                return audit_tool_call(
                    "compare_approaches",
                    {"approach_ids_json": approach_ids_json},
                    result,
                    started_at=started_at,
                )
            impl_result = compare_approaches_impl(approach_ids=approach_ids)
            result = json_response(
                impl_result.get("ok", False),
                impl_result.get("message", "Approaches compared"),
                details=impl_result,
            )
            return audit_tool_call(
                "compare_approaches",
                {"approach_ids_json": approach_ids_json},
                result,
                started_at=started_at,
            )

        results["compare_approaches"] = compare_approaches

    if _enabled is None or "self_critique" in _enabled:

        @mcp.tool(
            **tool_options(
                "Run deterministic code review via AST and text analysis.", read_only=True
            )
        )
        async def self_critique(scope: str, criteria_json: str | None = None) -> str:
            started_at = time.perf_counter()
            criteria = None
            if criteria_json is not None:
                try:
                    criteria = json.loads(criteria_json)
                except json.JSONDecodeError as exc:
                    result = json_response(
                        False, "Invalid JSON for criteria", details={"error": str(exc)}
                    )
                    return audit_tool_call(
                        "self_critique",
                        {"scope": scope, "criteria_json": criteria_json},
                        result,
                        started_at=started_at,
                    )
                if not isinstance(criteria, list):
                    result = json_response(False, "criteria must be a JSON array", details={})
                    return audit_tool_call(
                        "self_critique",
                        {"scope": scope, "criteria_json": criteria_json},
                        result,
                        started_at=started_at,
                    )
            impl_result = self_critique_impl(scope=scope, criteria=criteria)
            result = json_response(
                impl_result.get("ok", False),
                impl_result.get("message", "Self-critique complete"),
                details=impl_result.get("details", impl_result),
            )
            return audit_tool_call(
                "self_critique",
                {"scope": scope, "criteria_json": criteria_json},
                result,
                started_at=started_at,
            )

        results["self_critique"] = self_critique

    if _enabled is None or "create_checkpoint" in _enabled:

        @mcp.tool(
            **tool_options(
                "Create a git-based checkpoint with plan state snapshot.", destructive=True
            )
        )
        async def create_checkpoint(name: str) -> str:
            started_at = time.perf_counter()
            approval_result = await _require_mutating_meta_approval(
                "create_checkpoint", {"name": name}
            )
            if approval_result is not None:
                result = approval_result
                return audit_tool_call(
                    "create_checkpoint", {"name": name}, result, started_at=started_at
                )
            impl_result = create_checkpoint_impl(name=name)
            result = json_response(
                impl_result.get("ok", False),
                impl_result.get("error", impl_result.get("message", "Checkpoint created")),
                details=impl_result,
            )
            return audit_tool_call(
                "create_checkpoint", {"name": name}, result, started_at=started_at
            )

        results["create_checkpoint"] = create_checkpoint

    if _enabled is None or "restore_checkpoint" in _enabled:

        @mcp.tool(**tool_options("Restore a previously saved checkpoint.", destructive=True))
        async def restore_checkpoint(name: str) -> str:
            started_at = time.perf_counter()
            approval_result = await _require_mutating_meta_approval(
                "restore_checkpoint", {"name": name}
            )
            if approval_result is not None:
                result = approval_result
                return audit_tool_call(
                    "restore_checkpoint", {"name": name}, result, started_at=started_at
                )
            impl_result = restore_checkpoint_impl(name=name)
            result = json_response(
                impl_result.get("ok", False),
                impl_result.get("error", impl_result.get("message", "Checkpoint restored")),
                details=impl_result,
            )
            return audit_tool_call(
                "restore_checkpoint", {"name": name}, result, started_at=started_at
            )

        results["restore_checkpoint"] = restore_checkpoint

    if _enabled is None or "list_checkpoints" in _enabled:

        @mcp.tool(**tool_options("List all saved checkpoints.", read_only=True))
        async def list_checkpoints() -> str:
            started_at = time.perf_counter()
            impl_result = list_checkpoints_impl()
            result = json_response(
                impl_result.get("ok", False),
                impl_result.get("message", "Checkpoints listed"),
                details=impl_result,
            )
            return audit_tool_call("list_checkpoints", {}, result, started_at=started_at)

        results["list_checkpoints"] = list_checkpoints

    if _enabled is None or "reflect_on_recent_work" in _enabled:

        @mcp.tool(
            **tool_options(
                "Reflect on recent tool calls to identify patterns and suggest improvements.",
                read_only=True,
            )
        )
        async def reflect_on_recent_work(
            limit: int = 20,
            depth: int = 1,
        ) -> str:
            started_at = time.perf_counter()
            safe_limit = max(1, min(limit, 100))
            safe_depth = max(0, min(depth, _MAX_REFLECT_RECURSION_DEPTH))
            records = (
                get_recent_tool_calls_impl(limit=safe_limit)
                if get_recent_tool_calls_impl
                else {"records": []}
            )
            raw_records = records.get("records", [])
            summary = _build_reflection_summary(raw_records, safe_depth)
            suggestions: list[str] = []
            if summary.get("error_rate", 0) > 0.2:
                suggestions.append("High error rate (>20%) - review failed tool calls for patterns")
            elif summary.get("error_rate", 0) > 0.1:
                suggestions.append("Moderate error rate (10-20%) - check tool parameters")

            unique_tools = summary.get("unique_tools", 0)
            if unique_tools < 3 and safe_limit > 5:
                suggestions.append(
                    "Low tool diversity - using same tools repeatedly may indicate inefficiency"
                )

            top_tool = max(
                summary.get("tool_counts", {}).items(), key=lambda x: x[1], default=(None, 0)
            )
            if top_tool[1] and safe_limit > 0 and top_tool[1] / safe_limit > 0.6:
                suggestions.append(
                    f"Heavy reliance on {top_tool[0]} "
                    f"(>{top_tool[1]/safe_limit:.0%}) - consider if alternatives exist"
                )
            result = json_response(
                True,
                "Reflection complete",
                details={
                    "summary": summary,
                    "suggestions": suggestions,
                    "records_count": len(raw_records),
                    "max_depth_reached": safe_depth >= _MAX_REFLECT_RECURSION_DEPTH,
                },
            )
            return audit_tool_call(
                "reflect_on_recent_work",
                {"limit": safe_limit, "depth": safe_depth},
                result,
                started_at=started_at,
            )

        results["reflect_on_recent_work"] = reflect_on_recent_work

    if _enabled is None or "meta_review" in _enabled:

        @mcp.tool(
            **tool_options(
                "Review multiple tool results holistically for consistency and gaps.",
                read_only=True,
            )
        )
        async def meta_review(results_json: str) -> str:
            started_at = time.perf_counter()
            try:
                tool_results = json.loads(results_json)
            except json.JSONDecodeError as exc:
                result = json_response(
                    False,
                    "Invalid JSON for results",
                    details={"error": str(exc)},
                )
                return audit_tool_call(
                    "meta_review", {"results_json": "<invalid>"}, result, started_at=started_at
                )
            if not isinstance(tool_results, list):
                result = json_response(False, "results_json must be a JSON array", details={})
                return audit_tool_call(
                    "meta_review", {"results_json": "<invalid>"}, result, started_at=started_at
                )
            limited = tool_results[:_MAX_META_REVIEW_ITEMS]
            if len(tool_results) > _MAX_META_REVIEW_ITEMS:
                limited = tool_results[:_MAX_META_REVIEW_ITEMS]
            ok_count = sum(1 for r in limited if isinstance(r, dict) and r.get("ok", False))
            error_count = len(limited) - ok_count
            inconsistencies: list[str] = []
            for i, item in enumerate(limited):
                if not isinstance(item, dict):
                    inconsistencies.append(f"Item {i} is not a dict")
                    continue
                if "error" in item and item.get("ok", True):
                    inconsistencies.append(f"Item {i} has error field but ok=True")
            result = json_response(
                True,
                "Meta-review complete",
                details={
                    "reviewed_count": len(limited),
                    "total_submitted": len(tool_results),
                    "ok_count": ok_count,
                    "error_count": error_count,
                    "inconsistencies": inconsistencies,
                    "truncated": len(tool_results) > _MAX_META_REVIEW_ITEMS,
                },
            )
            return audit_tool_call(
                "meta_review", {"results_count": len(tool_results)}, result, started_at=started_at
            )

        results["meta_review"] = meta_review

    return results
