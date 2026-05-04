"""Registration helpers for P6 meta-agent MCP tools."""

from __future__ import annotations

import json
import time
from typing import Any, Callable


def register_meta_agent_tools(
    *,
    mcp: Any,
    tool_options: Callable[..., dict[str, Any]],
    audit_tool_call: Callable[..., str],
    json_response: Callable[..., str],
    # Plan engine impls
    create_plan_impl: Callable[..., dict[str, Any]],
    execute_step_impl: Callable[..., dict[str, Any]],
    get_plan_status_impl: Callable[..., dict[str, Any]],
    # Approach explorer impls
    explore_approaches_impl: Callable[..., dict[str, Any]],
    execute_approach_impl: Callable[..., dict[str, Any]],
    compare_approaches_impl: Callable[..., dict[str, Any]],
    # Self critique impl
    self_critique_impl: Callable[..., dict[str, Any]],
    # Checkpoint impls
    create_checkpoint_impl: Callable[..., dict[str, Any]],
    restore_checkpoint_impl: Callable[..., dict[str, Any]],
    list_checkpoints_impl: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Register all meta-agent MCP tools and return a dict of callables."""

    @mcp.tool(
        **tool_options(
            "Create an execution plan with a goal and a JSON array of step "
            "descriptions. The plan is stored under .claude-bridge/plans/ "
            "and returns a plan_id for later execution and status queries.",
            destructive=True,
        )
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

    @mcp.tool(
        **tool_options(
            "Execute a single step in an existing plan by plan_id and step_id. "
            "Marks the step as completed, updates the plan progress, and sets "
            "the plan status to completed when all steps are done.",
            destructive=True,
        )
    )
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

    @mcp.tool(
        **tool_options(
            "Get the full status and details of a plan by its plan_id. "
            "Returns the plan object with all steps, their statuses, "
            "and overall completion count.",
            read_only=True,
        )
    )
    async def get_plan_status(plan_id: str) -> str:
        started_at = time.perf_counter()
        impl_result = get_plan_status_impl(plan_id=plan_id)
        result = json_response(
            impl_result.get("ok", False),
            impl_result.get("error", impl_result.get("message", "Plan status loaded")),
            details=impl_result,
        )
        return audit_tool_call(
            "get_plan_status",
            {"plan_id": plan_id},
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Explore alternative approaches for a programming problem using "
            "keyword-based template matching. Returns numbered approaches "
            "with pros, cons, and complexity levels. Approaches are stored "
            "under .claude-bridge/approaches/.",
            destructive=True,
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

    @mcp.tool(
        **tool_options(
            "Execute a previously explored approach by its approach_id. "
            "Marks the approach as executed and returns its metadata "
            "including name, complexity, pros, and cons.",
            destructive=True,
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
            "execute_approach",
            {"approach_id": approach_id},
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Compare multiple approaches by their IDs. Loads each approach "
            "from .claude-bridge/approaches/, ranks them by complexity "
            "(low → medium → high), and returns the best recommendation. "
            "Pass approach_ids as a JSON array of strings.",
            read_only=True,
        )
    )
    async def compare_approaches(approach_ids_json: str) -> str:
        started_at = time.perf_counter()
        try:
            approach_ids = json.loads(approach_ids_json)
        except json.JSONDecodeError as exc:
            result = json_response(
                False,
                "Invalid JSON for approach_ids",
                details={"error": str(exc)},
            )
            return audit_tool_call(
                "compare_approaches",
                {"approach_ids_json": approach_ids_json},
                result,
                started_at=started_at,
            )
        if not isinstance(approach_ids, list):
            result = json_response(
                False,
                "approach_ids must be a JSON array",
                details={},
            )
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

    @mcp.tool(
        **tool_options(
            "Run deterministic code review (self-critique) via AST parsing, "
            "regex, and text analysis. Scope can be a file path or \"project\" "
            "to review the whole project. Optional criteria_json is a JSON "
            "array of aspects to check: complexity, style, security, "
            "performance, naming, duplication, test_coverage. "
            "Defaults to [\"complexity\", \"style\"].",
            read_only=True,
        )
    )
    async def self_critique(
        scope: str,
        criteria_json: str | None = None,
    ) -> str:
        started_at = time.perf_counter()
        criteria = None
        if criteria_json is not None:
            try:
                criteria = json.loads(criteria_json)
            except json.JSONDecodeError as exc:
                result = json_response(
                    False,
                    "Invalid JSON for criteria",
                    details={"error": str(exc)},
                )
                return audit_tool_call(
                    "self_critique",
                    {"scope": scope, "criteria_json": criteria_json},
                    result,
                    started_at=started_at,
                )
            if not isinstance(criteria, list):
                result = json_response(
                    False,
                    "criteria must be a JSON array",
                    details={},
                )
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

    @mcp.tool(
        **tool_options(
            "Create a git-based checkpoint with a plan state snapshot. "
            "Runs git add -A and git commit in the project directory, "
            "then saves plan status under .claude-bridge/checkpoints/. "
            "Returns the commit hash, timestamp, and plan count.",
            destructive=True,
        )
    )
    async def create_checkpoint(name: str) -> str:
        started_at = time.perf_counter()
        impl_result = create_checkpoint_impl(name=name)
        result = json_response(
            impl_result.get("ok", False),
            impl_result.get("error", impl_result.get("message", "Checkpoint created")),
            details=impl_result,
        )
        return audit_tool_call(
            "create_checkpoint",
            {"name": name},
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "Restore a previously saved checkpoint by name. "
            "Loads the checkpoint snapshot and runs git checkout "
            "to the associated commit. WARNING: This overwrites all "
            "uncommitted changes in the working tree.",
            destructive=True,
        )
    )
    async def restore_checkpoint(name: str) -> str:
        started_at = time.perf_counter()
        impl_result = restore_checkpoint_impl(name=name)
        result = json_response(
            impl_result.get("ok", False),
            impl_result.get("error", impl_result.get("message", "Checkpoint restored")),
            details=impl_result,
        )
        return audit_tool_call(
            "restore_checkpoint",
            {"name": name},
            result,
            started_at=started_at,
        )

    @mcp.tool(
        **tool_options(
            "List all saved checkpoints from .claude-bridge/checkpoints/. "
            "Returns a summary of each checkpoint with name, timestamp, "
            "commit hash, and plan count.",
            read_only=True,
        )
    )
    async def list_checkpoints() -> str:
        started_at = time.perf_counter()
        impl_result = list_checkpoints_impl()
        result = json_response(
            impl_result.get("ok", False),
            impl_result.get("message", "Checkpoints listed"),
            details=impl_result,
        )
        return audit_tool_call(
            "list_checkpoints",
            {},
            result,
            started_at=started_at,
        )

    return {
        "create_plan": create_plan,
        "execute_step": execute_step,
        "get_plan_status": get_plan_status,
        "explore_approaches": explore_approaches,
        "execute_approach": execute_approach,
        "compare_approaches": compare_approaches,
        "self_critique": self_critique,
        "create_checkpoint": create_checkpoint,
        "restore_checkpoint": restore_checkpoint,
        "list_checkpoints": list_checkpoints,
    }
