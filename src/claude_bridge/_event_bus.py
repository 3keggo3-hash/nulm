"""Thread-safe event bus for Nulm hooks and quality gates."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class EventType(Enum):
    TOOL_CALL = "tool_call"
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    PROMPT_SEND = "prompt_send"
    RESULT_RECEIVE = "result_receive"
    WORKFLOW_PLAN_CREATED = "workflow_plan_created"
    WORKFLOW_APPROVAL_PENDING = "workflow_approval_pending"
    WORKFLOW_STEP_EXECUTED = "workflow_step_executed"
    WORKFLOW_STATE_TRANSITION = "workflow_state_transition"
    VERIFICATION_PASS = "verification_pass"
    VERIFICATION_FAIL = "verification_fail"


@dataclass(order=True)
class Event:
    priority: int = 0
    event_type: EventType = EventType.TOOL_CALL
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str | None = None


@dataclass
class EventHandler:
    name: str
    handler: Callable[[Event], None]
    priority: int = 100


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[EventType, list[EventHandler]] = {}
        self._lock = threading.RLock()

    def subscribe(
        self,
        event_type: EventType,
        handler: Callable[[Event], None],
        name: str = "",
        priority: int = 100,
    ) -> None:
        with self._lock:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(
                EventHandler(name=name or f"handler_{id(handler)}", handler=handler, priority=priority)
            )
            self._handlers[event_type].sort(key=lambda h: h.priority, reverse=True)

    def unsubscribe(self, event_type: EventType, name: str) -> None:
        with self._lock:
            if event_type in self._handlers:
                self._handlers[event_type] = [
                    h for h in self._handlers[event_type] if h.name != name
                ]

    def publish(self, event_type: EventType, data: dict[str, Any] | None = None) -> None:
        from datetime import datetime, timezone

        event = Event(
            priority=0,
            event_type=event_type,
            data=data or {},
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            handlers = list(self._handlers.get(event_type, []))

        for handler in handlers:
            try:
                handler.handler(event)
            except Exception:
                pass

    def get_handlers(self, event_type: EventType) -> list[EventHandler]:
        with self._lock:
            return list(self._handlers.get(event_type, []))


_EVENT_BUS_INSTANCE: EventBus | None = None
_EVENT_BUS_LOCK = threading.Lock()


def get_event_bus() -> EventBus:
    global _EVENT_BUS_INSTANCE
    with _EVENT_BUS_LOCK:
        if _EVENT_BUS_INSTANCE is None:
            _EVENT_BUS_INSTANCE = EventBus()
        return _EVENT_BUS_INSTANCE