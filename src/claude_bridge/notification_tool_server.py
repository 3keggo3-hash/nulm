"""Registration helpers for MCP notification/streaming tools.

Provides tools for server-initiated notifications (Feature 1: MCP Protocol Stream Extensions).
"""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import time
from typing import Any, Callable

from claude_bridge.tool_registration import ToolRegistrationContext


def register_notification_tools(
    *,
    mcp: Any,
    tool_options: Callable[..., dict[str, Any]],
    audit_tool_call: Callable[..., str],
    json_response: Callable[..., str],
    enabled_names: set[str] | None = None,
) -> dict[str, Any]:
    """Register server-initiated notification tools.

    These tools enable clients to:
    - Subscribe to event streams (stream_subscribe)
    - Query recent events (get_recent_events)
    - Check notification capability (get_stream_capabilities)
    """
    ctx = ToolRegistrationContext(
        mcp=mcp,
        tool_options=tool_options,
        audit_tool_call=audit_tool_call,
        enabled_names=enabled_names,
    )

    if ctx.should_register("stream_subscribe"):
        from claude_bridge._stream_events import get_broadcaster

        async def stream_subscribe(event_type: str, include_history: bool = True) -> str:
            """Subscribe to server-initiated events of a specific type.

            After subscribing, the server may push events to the client via
            the response's 'subscription_id'. Events are stored and can be
            retrieved via get_recent_events.

            Args:
                event_type: Event type to subscribe to (e.g., "workflow.progress")
                include_history: If true, include recent matching events in response
            """
            started_at = time.perf_counter()
            broadcaster = get_broadcaster()
            history = (
                broadcaster.get_history(event_type=event_type, limit=5) if include_history else []
            )
            history_data = [e.to_dict() for e in history]
            result = json_response(
                True,
                f"Subscribed to {event_type}",
                details={
                    "subscription_id": f"sub_{int(time.time()*1000)}",
                    "event_type": event_type,
                    "active": True,
                    "recent_events": history_data,
                    "note": "Server-initiated events will be available via get_recent_events",
                },
            )
            return audit_tool_call(
                "stream_subscribe", {"event_type": event_type}, result, started_at=started_at
            )

        ctx.register(
            "stream_subscribe",
            "Subscribe to server-initiated events. Use get_recent_events to retrieve events.",
            stream_subscribe,
            read_only=True,
        )

    if ctx.should_register("get_recent_events"):
        from claude_bridge._stream_events import get_broadcaster

        async def get_recent_events(event_type: str | None = None, limit: int = 10) -> str:
            """Get recent server-initiated events.

            Args:
                event_type: Filter by event type (optional)
                limit: Maximum number of events to return (default 10, max 50)
            """
            started_at = time.perf_counter()
            broadcaster = get_broadcaster()
            actual_limit = min(limit, 50)
            events = broadcaster.get_history(event_type=event_type, limit=actual_limit)
            events_data = [e.to_dict() for e in events]
            result = json_response(
                True,
                f"Retrieved {len(events_data)} events",
                details={
                    "events": events_data,
                    "count": len(events_data),
                    "event_type_filter": event_type,
                },
            )
            return audit_tool_call(
                "get_recent_events",
                {"event_type": event_type, "limit": limit},
                result,
                started_at=started_at,
            )

        ctx.register(
            "get_recent_events",
            "Retrieve recent server-initiated events.",
            get_recent_events,
            read_only=True,
        )

    if ctx.should_register("get_stream_capabilities"):

        async def get_stream_capabilities() -> str:
            """Get server capabilities for streaming and server-initiated notifications.

            Returns capability information about:
            - Supported event types
            - Whether streaming subscriptions are available
            """
            started_at = time.perf_counter()
            result = json_response(
                True,
                "Stream capabilities retrieved",
                details={
                    "stream_events_enabled": True,
                    "capabilities": ["workflow.progress", "indexing.phase", "benchmark.progress"],
                    "max_history_size": 100,
                    "supports_subscription": True,
                    "supports_wildcard": True,
                    "version": "1.0.0",
                },
            )
            return audit_tool_call("get_stream_capabilities", {}, result, started_at=started_at)

        ctx.register(
            "get_stream_capabilities",
            "Get server streaming and event notification capabilities.",
            get_stream_capabilities,
            read_only=True,
        )

    if ctx.should_register("emit_progress_event"):
        from claude_bridge._stream_events import get_broadcaster

        async def emit_progress_event(
            workflow_id: str, step_id: str, status: str, tokens_spent: int = 0, duration_ms: int = 0
        ) -> str:
            """Emit a workflow progress event for monitoring.

            This tool demonstrates server-initiated events by publishing
            a workflow.progress event that clients can retrieve via get_recent_events.

            Args:
                workflow_id: Identifier of the workflow
                step_id: Current step identifier
                status: Status of the step (started, running, complete, failed)
                tokens_spent: Token usage for this step
                duration_ms: Execution time in milliseconds
            """
            started_at = time.perf_counter()
            broadcaster = get_broadcaster()
            broadcaster.publish(
                "workflow.progress",
                {
                    "workflow_id": workflow_id,
                    "step_id": step_id,
                    "status": status,
                    "tokens_spent": tokens_spent,
                    "duration_ms": duration_ms,
                },
                correlation_id=f"{workflow_id}.{step_id}",
            )
            result = json_response(
                True,
                f"Progress event emitted for {workflow_id}/{step_id}",
                details={
                    "workflow_id": workflow_id,
                    "step_id": step_id,
                    "status": status,
                    "event_type": "workflow.progress",
                },
            )
            return audit_tool_call(
                "emit_progress_event",
                {"workflow_id": workflow_id, "step_id": step_id, "status": status},
                result,
                started_at=started_at,
            )

        ctx.register(
            "emit_progress_event",
            "Emit a workflow progress event for server-initiated notification demonstration.",
            emit_progress_event,
        )

    return ctx.results
