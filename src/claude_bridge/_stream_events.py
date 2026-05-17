# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

"""MCP Protocol Stream Extensions: Server-initiated notification support.

This module provides infrastructure for server-initiated events (notifications)
that can be pushed to MCP clients without requiring them to poll.

Key components:
- NotificationSink: Interface for sending server-initiated events
- EventBroadcaster: Thread-safe subscriber management and event distribution
- StreamEvent: Typed event payload for workflow progress, indexing updates, etc.

Usage:
    broadcaster = EventBroadcaster()
    broadcaster.subscribe("workflow.progress", my_callback)
    broadcaster.publish("workflow.progress", {"step_id": "build", "status": "complete"})
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class StreamEvent:
    """A server-initiated event payload."""

    event_type: str
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    correlation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
        }


class NotificationSink:
    """Callback-based sink for server-initiated notifications."""

    def __init__(
        self,
        callback: Callable[[StreamEvent], None] | None = None,
        async_callback: Callable[[StreamEvent], Any] | None = None,
    ) -> None:
        self._callback = callback
        self._async_callback = async_callback
        self._closed = False

    def send(self, event: StreamEvent) -> None:
        if self._closed:
            return
        if self._callback:
            try:
                self._callback(event)
            except Exception:
                pass

    async def send_async(self, event: StreamEvent) -> None:
        if self._closed:
            return
        if self._async_callback:
            try:
                result = self._async_callback(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass
        elif self._callback:
            try:
                self._callback(event)
            except Exception:
                pass

    def close(self) -> None:
        self._closed = True


class EventBroadcaster:
    """Thread-safe event broadcaster for server-initiated notifications.

    Manages subscriptions and distributes events to matching subscribers.
    """

    def __init__(self) -> None:
        self._subscriptions: dict[str, list[NotificationSink]] = {}
        self._lock = threading.Lock()
        self._event_history: list[StreamEvent] = []
        self._max_history = 100

    def subscribe(
        self,
        event_type: str,
        callback: Callable[[StreamEvent], None] | None = None,
        async_callback: Callable[[StreamEvent], Any] | None = None,
    ) -> NotificationSink:
        """Subscribe to events of a specific type.

        Args:
            event_type: Event type pattern (e.g., "workflow.progress", "indexing.*")
            callback: Synchronous callback to invoke when event fires
            async_callback: Async callback to invoke when event fires

        Returns:
            NotificationSink that can be used to unsubscribe or close
        """
        sink = NotificationSink(callback=callback, async_callback=async_callback)
        with self._lock:
            if event_type not in self._subscriptions:
                self._subscriptions[event_type] = []
            self._subscriptions[event_type].append(sink)
        return sink

    def unsubscribe(self, sink: NotificationSink) -> None:
        """Unsubscribe a sink from all events."""
        with self._lock:
            for sinks in self._subscriptions.values():
                if sink in sinks:
                    sinks.remove(sink)
        sink.close()

    def publish(
        self,
        event_type: str,
        data: dict[str, Any],
        correlation_id: str | None = None,
    ) -> None:
        """Publish an event to all matching subscribers.

        Args:
            event_type: Type of event to publish
            data: Event payload data
            correlation_id: Optional correlation ID for tracing
        """
        event = StreamEvent(event_type=event_type, data=data, correlation_id=correlation_id)
        self._add_to_history(event)
        with self._lock:
            subscribers = list(self._subscriptions.get(event_type, []))
            # Also match wildcard patterns
            wildcard_subscribers = list(self._subscriptions.get("*", []))
            all_subscribers = subscribers + wildcard_subscribers
        for sink in all_subscribers:
            try:
                sink.send(event)
            except Exception:
                pass

    async def publish_async(
        self, event_type: str, data: dict[str, Any], correlation_id: str | None = None
    ) -> None:
        """Async version of publish for use in async contexts."""
        event = StreamEvent(event_type=event_type, data=data, correlation_id=correlation_id)
        self._add_to_history(event)
        with self._lock:
            subscribers = list(self._subscriptions.get(event_type, []))
            wildcard_subscribers = list(self._subscriptions.get("*", []))
            all_subscribers = subscribers + wildcard_subscribers
        for sink in all_subscribers:
            try:
                await sink.send_async(event)
            except Exception:
                pass

    def _add_to_history(self, event: StreamEvent) -> None:
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history :]

    def get_history(self, event_type: str | None = None, limit: int = 10) -> list[StreamEvent]:
        """Get recent event history, optionally filtered by type."""
        with self._lock:
            if event_type:
                return [e for e in self._event_history if e.event_type == event_type][-limit:]
            return list(self._event_history)[-limit:]

    def clear(self) -> None:
        """Clear all subscriptions and history."""
        with self._lock:
            self._subscriptions.clear()
            self._event_history.clear()


# Global broadcaster instance for use across the application
_broadcaster: EventBroadcaster | None = None
_broadcaster_lock = threading.Lock()


def get_broadcaster() -> EventBroadcaster:
    """Get the global EventBroadcaster instance."""
    global _broadcaster
    with _broadcaster_lock:
        if _broadcaster is None:
            _broadcaster = EventBroadcaster()
        return _broadcaster
