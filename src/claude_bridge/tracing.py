"""OpenTelemetry distributed tracing for Claude Bridge."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generator

try:
    from opentelemetry import trace  # type: ignore[import-not-found]
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
    from opentelemetry.sdk.trace.export import (  # type: ignore[import-not-found]
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )
    from opentelemetry.trace import Span, Status, StatusCode  # type: ignore[import-not-found]
    from opentelemetry.trace.propagation.tracecontext import (  # type: ignore[import-not-found]
        TraceContextTextMapPropagator,
    )
except ImportError:
    trace = None
    Span = Status = StatusCode = None
    TracerProvider = BatchSpanProcessor = ConsoleSpanExporter = None
    TraceContextTextMapPropagator = None


class TraceLevel(str, Enum):
    NONE = "none"
    BASIC = "basic"
    DETAILED = "detailed"


@dataclass
class SpanAttributes:
    tool_name: str | None = None
    tool_result_ok: bool | None = None
    duration_ms: float | None = None
    error_type: str | None = None
    project_path: str | None = None
    user_goal: str | None = None
    workflow_steps: int | None = None
    agent_id: str | None = None
    operation_type: str | None = None
    cache_hit: bool | None = None
    custom: dict[str, Any] = field(default_factory=dict)


class TracingManager:
    _instance: "TracingManager | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "TracingManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._tracer: trace.Tracer | None = None
        self._provider: TracerProvider | None = None
        self._propagator = (
            TraceContextTextMapPropagator() if TraceContextTextMapPropagator else None
        )
        self._level = TraceLevel.NONE
        self._initialized: bool = True
        self._span_storage: list[dict[str, Any]] = []
        self._span_storage_lock = threading.Lock()
        self._max_storage_size = 1000
        self._configure_from_env()

    def set_level(self, level: TraceLevel) -> None:
        self._level = level
        if level != TraceLevel.NONE and trace is not None and self._tracer is None:
            self._setup_tracer()

    def get_recent_spans(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._span_storage_lock:
            return sorted(self._span_storage, key=lambda x: x.get("timestamp", 0), reverse=True)[
                :limit
            ]

    def get_span_stats(self) -> dict[str, Any]:
        with self._span_storage_lock:
            if not self._span_storage:
                return {
                    "total_spans": 0,
                    "error_count": 0,
                    "avg_duration_ms": 0,
                    "p50_duration_ms": 0,
                    "p95_duration_ms": 0,
                    "p99_duration_ms": 0,
                }
            durations = [s.get("duration_ms", 0) for s in self._span_storage]
            durations.sort()
            error_count = sum(1 for s in self._span_storage if s.get("error_type"))
            return {
                "total_spans": len(self._span_storage),
                "error_count": error_count,
                "avg_duration_ms": sum(durations) / len(durations) if durations else 0,
                "p50_duration_ms": self._percentile(durations, 50),
                "p95_duration_ms": self._percentile(durations, 95),
                "p99_duration_ms": self._percentile(durations, 99),
            }

    def _percentile(self, sorted_values: list[float], p: float) -> float:
        if not sorted_values:
            return 0.0
        idx = int(len(sorted_values) * p / 100.0)
        idx = min(idx, len(sorted_values) - 1)
        return sorted_values[idx]

    def _configure_from_env(self) -> None:
        level_str = os.environ.get("CLAUDE_BRIDGE_TRACING", "none").lower()
        try:
            self._level = TraceLevel(level_str)
        except ValueError:
            self._level = TraceLevel.NONE
        if self._level != TraceLevel.NONE and trace is not None:
            self._setup_tracer()

    def _setup_tracer(self) -> None:
        if trace is None:
            return
        self._provider = TracerProvider()
        exporter = ConsoleSpanExporter()
        self._provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(self._provider)
        self._tracer = trace.get_tracer("claude-bridge", "0.1.0")

    @property
    def tracer(self) -> trace.Tracer | None:
        return self._tracer

    @property
    def level(self) -> TraceLevel:
        return self._level

    @contextmanager
    def start_span(
        self, name: str, attributes: SpanAttributes | None = None
    ) -> Generator[Span | None, None, None]:
        if self._tracer is None or self._level == TraceLevel.NONE:
            yield None
            return
        start_time = time.perf_counter()
        with self._tracer.start_as_current_span(name) as span:
            if attributes:
                if attributes.tool_name:
                    span.set_attribute("tool.name", attributes.tool_name)
                if attributes.tool_result_ok is not None:
                    span.set_attribute("tool.result_ok", attributes.tool_result_ok)
                if attributes.duration_ms is not None:
                    span.set_attribute("tool.duration_ms", attributes.duration_ms)
                if attributes.error_type:
                    span.set_attribute("error.type", attributes.error_type)
                if attributes.project_path:
                    span.set_attribute("project.path", attributes.project_path)
                if attributes.user_goal:
                    span.set_attribute("user.goal", attributes.user_goal)
                if attributes.workflow_steps is not None:
                    span.set_attribute("workflow.steps", attributes.workflow_steps)
                if attributes.agent_id:
                    span.set_attribute("agent.id", attributes.agent_id)
                if attributes.operation_type:
                    span.set_attribute("operation.type", attributes.operation_type)
                if attributes.cache_hit is not None:
                    span.set_attribute("cache.hit", attributes.cache_hit)
                for k, v in attributes.custom.items():
                    span.set_attribute(k, v)
            yield span
            duration_ms = (time.perf_counter() - start_time) * 1000
            with self._span_storage_lock:
                span_record = {
                    "name": name,
                    "timestamp": start_time,
                    "duration_ms": duration_ms,
                    "trace_level": self._level.value,
                }
                if attributes:
                    span_record["tool_name"] = attributes.tool_name
                    span_record["error_type"] = attributes.error_type
                    span_record["user_goal"] = attributes.user_goal
                self._span_storage.append(span_record)
                if len(self._span_storage) > self._max_storage_size:
                    self._span_storage = self._span_storage[-self._max_storage_size :]

    def record_exception(self, span: Span | None, exception: Exception) -> None:
        if span is None or Status is None:
            return
        span.record_exception(exception)
        span.set_status(Status(StatusCode.ERROR, str(exception)))

    def set_ok(self, span: Span | None) -> None:
        if span is None or Status is None:
            return
        span.set_status(Status(StatusCode.OK))

    def create_span_attributes(self, **kwargs: Any) -> SpanAttributes:
        return SpanAttributes(**kwargs)

    def inject_context(self, carrier: dict[str, str]) -> dict[str, str]:
        if self._propagator is None:
            return carrier
        self._propagator.inject(carrier)
        return carrier

    def extract_context(self, carrier: dict[str, str]) -> Any:
        if self._propagator is None:
            return None
        return self._propagator.extract(carrier)

    def shutdown(self) -> None:
        if self._provider is not None:
            self._provider.shutdown()


_TRACING_MANAGER: TracingManager | None = None


def get_tracing_manager() -> TracingManager:
    global _TRACING_MANAGER
    if _TRACING_MANAGER is None:
        _TRACING_MANAGER = TracingManager()
    return _TRACING_MANAGER


@contextmanager
def trace_tool_call(
    tool_name: str,
    project_path: str | None = None,
) -> Generator[tuple[Span | None, SpanAttributes], None, None]:
    manager = get_tracing_manager()
    attrs = manager.create_span_attributes(
        tool_name=tool_name,
        project_path=project_path,
    )
    start = time.perf_counter()
    with manager.start_span(f"tool.{tool_name}", attrs) as span:
        try:
            yield span, attrs
            manager.set_ok(span)
        except Exception as exc:
            manager.record_exception(span, exc)
            raise
        finally:
            if attrs.duration_ms is None:
                attrs.duration_ms = (time.perf_counter() - start) * 1000
            if span is not None:
                span.set_attribute("tool.duration_ms", attrs.duration_ms)
                if attrs.tool_result_ok is not None:
                    span.set_attribute("tool.result_ok", attrs.tool_result_ok)


@contextmanager
def trace_workflow(
    task: str,
    max_steps: int | None = None,
) -> Generator[tuple[Span | None, SpanAttributes], None, None]:
    manager = get_tracing_manager()
    attrs = manager.create_span_attributes(
        user_goal=task,
        workflow_steps=max_steps,
    )
    start = time.perf_counter()
    with manager.start_span("workflow.execute", attrs) as span:
        try:
            yield span, attrs
            manager.set_ok(span)
        except Exception as exc:
            manager.record_exception(span, exc)
            raise
        finally:
            attrs.duration_ms = (time.perf_counter() - start) * 1000
            if span is not None:
                span.set_attribute("workflow.duration_ms", attrs.duration_ms)
