"""OpenTelemetry distributed tracing for Claude Bridge."""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generator

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.trace import Span, Status, StatusCode
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
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
        self._propagator = TraceContextTextMapPropagator() if TraceContextTextMapPropagator else None
        self._level = TraceLevel.NONE
        self._initialized: bool = True
        self._configure_from_env()

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
    def start_span(self, name: str, attributes: SpanAttributes | None = None) -> Generator[Span | None, None, None]:
        if self._tracer is None or self._level == TraceLevel.NONE:
            yield None
            return
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
                for k, v in attributes.custom.items():
                    span.set_attribute(k, v)
            yield span

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
        yield span, attrs
        attrs.duration_ms = (time.perf_counter() - start) * 1000


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
        yield span, attrs
        attrs.duration_ms = (time.perf_counter() - start) * 1000
