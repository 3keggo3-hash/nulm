"""Hook registry for Nulm quality gates and extensibility."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

from claude_bridge._event_bus import EventBus, EventType, get_event_bus


@dataclass
class HookSpec:
    name: str
    event_type: EventType
    priority: int = 100
    handler: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None


@dataclass
class HookResult:
    allow: bool = True
    modified_params: dict[str, Any] | None = None
    message: str | None = None


class HookRegistry:
    def __init__(self) -> None:
        self._hooks: dict[str, HookSpec] = {}
        self._lock = threading.RLock()
        self._event_bus: EventBus | None = None

    @property
    def event_bus(self) -> EventBus:
        if self._event_bus is None:
            self._event_bus = get_event_bus()
        return self._event_bus

    def register(self, hook_spec: HookSpec) -> None:
        with self._lock:
            self._hooks[hook_spec.name] = hook_spec

    def unregister(self, name: str) -> None:
        with self._lock:
            self._hooks.pop(name, None)

    def get_hooks(self, event_type: EventType) -> list[HookSpec]:
        with self._lock:
            return [h for h in self._hooks.values() if h.event_type == event_type]

    def invoke_hooks(
        self,
        event_type: EventType,
        context: dict[str, Any],
    ) -> HookResult:
        hooks = self.get_hooks(event_type)
        modified_context: dict[str, Any] | None = None
        message: str | None = None

        for hook in hooks:
            if hook.handler is None:
                continue
            try:
                result = hook.handler(context)
                if result is not None:
                    if isinstance(result, dict):
                        if modified_context is None:
                            modified_context = dict(context)
                        modified_context.update(result)
                    elif isinstance(result, HookResult):
                        if not result.allow:
                            return result
                        if result.modified_params is not None:
                            if modified_context is None:
                                modified_context = dict(context)
                            modified_context.update(result.modified_params)
                        if result.message:
                            message = result.message
            except Exception:
                continue

        return HookResult(
            allow=True,
            modified_params=modified_context,
            message=message,
        )


_HOOK_REGISTRY_INSTANCE: HookRegistry | None = None
_HOOK_REGISTRY_LOCK = threading.Lock()


def get_hook_registry() -> HookRegistry:
    global _HOOK_REGISTRY_INSTANCE
    with _HOOK_REGISTRY_LOCK:
        if _HOOK_REGISTRY_INSTANCE is None:
            _HOOK_REGISTRY_INSTANCE = HookRegistry()
        return _HOOK_REGISTRY_INSTANCE


class _HookDecorator:
    def __init__(self, event_type: EventType) -> None:
        self._event_type = event_type

    def __call__(
        self,
        name: str = "",
        priority: int = 100,
    ) -> Callable[[Callable[[dict[str, Any]], dict[str, Any] | None]], Callable[..., None]]:
        def decorator(
            func: Callable[[dict[str, Any]], dict[str, Any] | None],
        ) -> Callable[..., None]:
            hook_name = name or func.__name__
            spec = HookSpec(
                name=hook_name,
                event_type=self._event_type,
                priority=priority,
                handler=func,
            )
            registry = get_hook_registry()
            registry.register(spec)

            def wrapper(*args: Any, **kwargs: Any) -> None:
                pass

            return wrapper

        return decorator


class _HookModule:
    on_tool_call = _HookDecorator(EventType.TOOL_CALL)
    on_agent_start = _HookDecorator(EventType.AGENT_START)
    on_agent_end = _HookDecorator(EventType.AGENT_END)
    on_prompt_send = _HookDecorator(EventType.PROMPT_SEND)
    on_result_receive = _HookDecorator(EventType.RESULT_RECEIVE)
    on_workflow_event = _HookDecorator(EventType.WORKFLOW_PLAN_CREATED)
    on_workflow_plan_created = _HookDecorator(EventType.WORKFLOW_PLAN_CREATED)
    on_workflow_approval_pending = _HookDecorator(EventType.WORKFLOW_APPROVAL_PENDING)
    on_workflow_step_executed = _HookDecorator(EventType.WORKFLOW_STEP_EXECUTED)
    on_workflow_state_transition = _HookDecorator(EventType.WORKFLOW_STATE_TRANSITION)
    on_verification_pass = _HookDecorator(EventType.VERIFICATION_PASS)
    on_verification_fail = _HookDecorator(EventType.VERIFICATION_FAIL)


hook = _HookModule()
