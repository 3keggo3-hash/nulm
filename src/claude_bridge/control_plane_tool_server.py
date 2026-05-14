"""Registration helpers for local control-plane MCP tools."""

from __future__ import annotations

from typing import Any, Callable, Literal, cast

from claude_bridge.tool_registration import ToolRegistrationContext


def register_control_plane_tools(
    *,
    mcp: Any,
    tool_options: Callable[..., dict[str, Any]],
    audit_tool_call: Callable[..., str],
    json_response: Callable[..., str],
    enabled_names: set[str] | None = None,
) -> dict[str, Any]:
    """Register task and approval visibility tools."""
    ctx = ToolRegistrationContext(
        mcp=mcp,
        tool_options=tool_options,
        audit_tool_call=audit_tool_call,
        enabled_names=enabled_names,
    )

    if ctx.should_register("list_tasks"):

        async def list_tasks(status: str | None = None, limit: int = 20) -> str:
            from claude_bridge.control_plane import control_plane_dir, list_tasks as list_impl

            started_at = ctx.now_ms()
            tasks = list_impl(status=status, limit=limit)
            result = json_response(
                True,
                f"Tasks loaded: {len(tasks)}",
                details={
                    "schema_version": "control_plane.tasks.v1",
                    "state_dir": str(control_plane_dir()),
                    "tasks": tasks,
                },
            )
            return audit_tool_call(
                "list_tasks",
                {"status": status, "limit": limit},
                result,
                started_at=started_at,
            )

        ctx.register("list_tasks", "List local control-plane tasks.", list_tasks, read_only=True)

    if ctx.should_register("task_status"):

        async def task_status(task_id: str = "latest") -> str:
            from claude_bridge.control_plane import get_task

            started_at = ctx.now_ms()
            task = get_task(task_id)
            if task is None:
                result = json_response(
                    False,
                    f"Task '{task_id}' not found",
                    code="task_not_found",
                    details={"task_id": task_id},
                )
            else:
                result = json_response(
                    True,
                    f"Task loaded: {task['id']}",
                    details={"schema_version": "control_plane.task.v1", "task": task},
                )
            return audit_tool_call(
                "task_status",
                {"task_id": task_id},
                result,
                started_at=started_at,
            )

        ctx.register(
            "task_status", "Show one local control-plane task.", task_status, read_only=True
        )

    if ctx.should_register("task_summary"):

        async def task_summary() -> str:
            from claude_bridge.control_plane import control_plane_dir, summarize_tasks

            started_at = ctx.now_ms()
            summary = summarize_tasks()
            result = json_response(
                True,
                "Task summary loaded",
                details={
                    "schema_version": "control_plane.task_summary.v1",
                    "state_dir": str(control_plane_dir()),
                    "summary": summary,
                },
            )
            return audit_tool_call("task_summary", {}, result, started_at=started_at)

        ctx.register(
            "task_summary", "Summarize local control-plane tasks.", task_summary, read_only=True
        )

    if ctx.should_register("list_pending_approvals"):

        async def list_pending_approvals(limit: int = 20) -> str:
            from claude_bridge.control_plane import (
                control_plane_dir,
                list_approvals as list_impl,
            )

            started_at = ctx.now_ms()
            approvals = list_impl(status="pending", limit=limit)
            result = json_response(
                True,
                f"Pending approvals loaded: {len(approvals)}",
                details={
                    "schema_version": "control_plane.approvals.v1",
                    "state_dir": str(control_plane_dir()),
                    "approvals": approvals,
                },
            )
            return audit_tool_call(
                "list_pending_approvals",
                {"limit": limit},
                result,
                started_at=started_at,
            )

        ctx.register(
            "list_pending_approvals",
            "List pending local control-plane approval requests.",
            list_pending_approvals,
            read_only=True,
        )

    if ctx.should_register("approve_pending_action"):

        async def approve_pending_action(approval_id: str, reason: str = "") -> str:
            return await _resolve_approval_tool(
                ctx=ctx,
                json_response=json_response,
                audit_tool_call=audit_tool_call,
                tool_name="approve_pending_action",
                approval_id=approval_id,
                status="approved",
                reason=reason,
            )

        ctx.register(
            "approve_pending_action",
            "Mark a local control-plane approval request as approved.",
            approve_pending_action,
            destructive=True,
        )

    if ctx.should_register("reject_pending_action"):

        async def reject_pending_action(approval_id: str, reason: str = "") -> str:
            return await _resolve_approval_tool(
                ctx=ctx,
                json_response=json_response,
                audit_tool_call=audit_tool_call,
                tool_name="reject_pending_action",
                approval_id=approval_id,
                status="denied",
                reason=reason,
            )

        ctx.register(
            "reject_pending_action",
            "Mark a local control-plane approval request as denied.",
            reject_pending_action,
            destructive=True,
        )

    return ctx.results


async def _resolve_approval_tool(
    *,
    ctx: ToolRegistrationContext,
    json_response: Callable[..., str],
    audit_tool_call: Callable[..., str],
    tool_name: str,
    approval_id: str,
    status: Literal["approved", "denied"],
    reason: str,
) -> str:
    from claude_bridge.control_plane import resolve_approval

    started_at = ctx.now_ms()
    approval = resolve_approval(
        approval_id,
        cast(Literal["approved", "denied"], status),
        reason=reason,
        metadata={"decision_reason": reason} if reason else None,
    )
    if approval is None:
        result = json_response(
            False,
            f"Approval '{approval_id}' not found",
            code="approval_not_found",
            details={"approval_id": approval_id},
        )
    else:
        result = json_response(
            True,
            f"Approval {status}: {approval_id}",
            details={
                "schema_version": "control_plane.approval.v1",
                "approval": approval,
            },
        )
    return audit_tool_call(
        tool_name,
        {"approval_id": approval_id, "status": status, "reason": reason},
        result,
        started_at=started_at,
    )
