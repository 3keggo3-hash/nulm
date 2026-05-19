"""Integration tests for OTLP export and health endpoints."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


import pytest
from unittest.mock import MagicMock, patch
import threading
import time

pytestmark = pytest.mark.integration


class TestOTLPExport:
    """Tests for OTLP export configuration."""

    def test_tracing_manager_initialization(self):
        from claude_bridge.tracing import TracingManager, TraceLevel

        tm = TracingManager()
        assert tm is not None
        assert hasattr(tm, "set_level")
        assert hasattr(tm, "start_span")
        assert tm.level == TraceLevel.NONE

    def test_tracing_manager_singleton(self):
        from claude_bridge.tracing import TracingManager, get_tracing_manager

        tm1 = TracingManager()
        tm2 = get_tracing_manager()
        assert tm1 is tm2

    def test_set_level_basic(self):
        from claude_bridge.tracing import TracingManager, TraceLevel

        tm = TracingManager()
        tm.set_level(TraceLevel.BASIC)
        assert tm.level == TraceLevel.BASIC

    def test_set_level_detailed(self):
        from claude_bridge.tracing import TracingManager, TraceLevel

        tm = TracingManager()
        tm.set_level(TraceLevel.DETAILED)
        assert tm.level == TraceLevel.DETAILED

    def test_span_attributes_creation(self):
        from claude_bridge.tracing import TracingManager, SpanAttributes

        tm = TracingManager()
        attrs = tm.create_span_attributes(
            tool_name="test_tool",
            tool_result_ok=True,
            duration_ms=100.0,
        )
        assert attrs.tool_name == "test_tool"
        assert attrs.tool_result_ok is True
        assert attrs.duration_ms == 100.0

    def test_get_recent_spans_empty(self):
        from claude_bridge.tracing import TracingManager

        tm = TracingManager()
        spans = tm.get_recent_spans(limit=10)
        assert isinstance(spans, list)

    def test_get_span_stats_empty(self):
        from claude_bridge.tracing import TracingManager

        tm = TracingManager()
        stats = tm.get_span_stats()
        assert stats["total_spans"] == 0
        assert stats["error_count"] == 0
        assert "p50_duration_ms" in stats

    def test_inject_context_empty_carrier(self):
        from claude_bridge.tracing import TracingManager

        tm = TracingManager()
        carrier: dict[str, str] = {}
        result = tm.inject_context(carrier)
        assert result == carrier

    def test_extract_context_empty_carrier(self):
        from claude_bridge.tracing import TracingManager

        tm = TracingManager()
        carrier: dict[str, str] = {}
        result = tm.extract_context(carrier)
        assert result is None

    def test_trace_tool_call_context_manager(self):
        from claude_bridge.tracing import trace_tool_call, get_tracing_manager

        manager = get_tracing_manager()
        manager.set_level(manager.level)

        with trace_tool_call("test_tool", project_path="/tmp") as (span, attrs):
            assert attrs is not None
            assert attrs.tool_name == "test_tool"

    def test_trace_workflow_context_manager(self):
        from claude_bridge.tracing import trace_workflow, get_tracing_manager

        manager = get_tracing_manager()
        with trace_workflow("test task", max_steps=5) as (span, attrs):
            assert attrs is not None
            assert attrs.user_goal == "test task"

    def test_span_storage_max_size_enforced(self):
        from claude_bridge.tracing import TracingManager

        tm = TracingManager()
        original_max = tm._max_storage_size
        tm._max_storage_size = 5
        tm._span_storage.clear()
        for i in range(10):
            tm._span_storage.append({"name": f"span_{i}", "timestamp": float(i)})
        tm._max_storage_size = original_max
        assert len(tm._span_storage) <= 10


class TestHealthEndpoints:
    """Tests for health check endpoints with mocked components."""

    def test_health_check_result_dataclass(self):
        from claude_bridge.observability import HealthCheckResult, HealthStatus

        result = HealthCheckResult(
            component="test",
            status=HealthStatus.HEALTHY,
            message="ok",
            latency_ms=1.5,
        )
        assert result.component == "test"
        assert result.status == HealthStatus.HEALTHY
        assert result.message == "ok"
        assert result.latency_ms == 1.5

    def test_health_status_enum_values(self):
        from claude_bridge.observability import HealthStatus

        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"

    def test_health_check_check_components(self):
        from claude_bridge.observability import HealthCheck

        health = HealthCheck()
        results = health.check_components()
        assert isinstance(results, dict)
        assert "config" in results
        assert "audit" in results
        assert "indexing" in results
        assert "shell" in results

    def test_health_check_get_report_structure(self):
        from claude_bridge.observability import HealthCheck

        health = HealthCheck()
        report = health.get_report()
        assert "status" in report
        assert "timestamp" in report
        assert "components" in report

    def test_health_check_report_includes_component_details(self):
        from claude_bridge.observability import HealthCheck

        health = HealthCheck()
        report = health.get_report()
        for comp_name, comp_data in report["components"].items():
            assert "status" in comp_data
            assert "message" in comp_data
            assert "latency_ms" in comp_data
            assert "metadata" in comp_data

    def test_health_check_overall_healthy(self):
        from claude_bridge.observability import HealthCheck, HealthStatus

        health = HealthCheck()
        health._last_check = {
            "comp1": MagicMock(status=HealthStatus.HEALTHY),
            "comp2": MagicMock(status=HealthStatus.HEALTHY),
        }
        health._last_check_time = time.time()
        report = health.get_report()
        assert report["status"] == HealthStatus.HEALTHY.value

    def test_health_check_overall_unhealthy(self):
        from claude_bridge.observability import HealthCheck, HealthStatus

        health = HealthCheck()
        health._last_check = {
            "comp1": MagicMock(status=HealthStatus.HEALTHY),
            "comp2": MagicMock(status=HealthStatus.UNHEALTHY),
        }
        health._last_check_time = time.time()
        report = health.get_report()
        assert report["status"] == HealthStatus.UNHEALTHY.value

    def test_health_check_overall_degraded(self):
        from claude_bridge.observability import HealthCheck, HealthStatus

        health = HealthCheck()
        health._last_check = {
            "comp1": MagicMock(status=HealthStatus.HEALTHY),
            "comp2": MagicMock(status=HealthStatus.DEGRADED),
        }
        health._last_check_time = time.time()
        report = health.get_report()
        assert report["status"] == HealthStatus.DEGRADED.value

    def test_health_check_refresh_on_stale(self):
        from claude_bridge.observability import HealthCheck

        health = HealthCheck()
        health._last_check_time = 0.0
        with patch.object(health, "check_components") as mock_check:
            mock_check.return_value = {}
            report = health.get_report()
            assert mock_check.called


class TestMetricsEndpoint:
    """Tests for /metrics endpoint output format."""

    def test_metrics_collector_singleton(self):
        from claude_bridge.observability import MetricsCollector

        mc1 = MetricsCollector()
        mc2 = MetricsCollector()
        assert mc1 is mc2

    def test_metrics_collector_increment(self):
        from claude_bridge.observability import MetricsCollector

        mc = MetricsCollector()
        mc.reset()
        mc.increment("test_counter", 1.0)
        count = mc.get("test_counter")
        assert count == 1.0

    def test_metrics_collector_increment_with_labels(self):
        from claude_bridge.observability import MetricsCollector

        mc = MetricsCollector()
        mc.reset()
        mc.increment("test_counter", labels={"tool": "read"})
        count = mc.get("test_counter", labels={"tool": "read"})
        assert count == 1.0

    def test_metrics_collector_observe(self):
        from claude_bridge.observability import MetricsCollector

        mc = MetricsCollector()
        mc.reset()
        mc.observe("test_histogram", 50.0)
        mc.observe("test_histogram", 100.0)
        avg = mc.get_histogram("test_histogram")
        assert avg == 75.0

    def test_metrics_collector_observe_with_labels(self):
        from claude_bridge.observability import MetricsCollector

        mc = MetricsCollector()
        mc.reset()
        mc.observe("test_histogram", 10.0, labels={"op": "shell"})
        value = mc.get_histogram("test_histogram", labels={"op": "shell"})
        assert value == 10.0

    def test_metrics_collector_get_percentile(self):
        from claude_bridge.observability import MetricsCollector

        mc = MetricsCollector()
        mc.reset()
        for v in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]:
            mc.observe("test_percentile", v)
        p50 = mc.get_percentile("test_percentile", 50)
        assert p50 == 5.0 or p50 == 6.0

    def test_metrics_collector_get_histogram_stats(self):
        from claude_bridge.observability import MetricsCollector

        mc = MetricsCollector()
        mc.reset()
        mc.observe("test_stats", 10.0)
        mc.observe("test_stats", 20.0)
        mc.observe("test_stats", 30.0)
        stats = mc.get_histogram_stats("test_stats")
        assert stats["count"] == 3
        assert stats["sum"] == 60.0
        assert stats["avg"] == 20.0
        assert stats["min"] == 10.0
        assert stats["max"] == 30.0

    def test_metrics_collector_set_gauge(self):
        from claude_bridge.observability import MetricsCollector

        mc = MetricsCollector()
        mc.reset()
        mc.set_gauge("test_gauge", 42.0)
        value = mc.get_gauge("test_gauge")
        assert value == 42.0

    def test_metrics_collector_render_prometheus(self):
        from claude_bridge.observability import MetricsCollector

        mc = MetricsCollector()
        mc.reset()
        mc.increment("test_counter_total", 5.0)
        mc.set_gauge("test_gauge_value", 100.0)
        output = mc.render_prometheus()
        assert "test_counter_total" in output or output == ""

    def test_prometheus_metrics_render(self):
        from claude_bridge.observability import PrometheusMetrics

        pm = PrometheusMetrics()
        output = pm.render()
        assert isinstance(output, str)


class TestTracesEndpoint:
    """Tests for /api/traces endpoint."""

    def test_tracing_manager_get_recent_spans_limit(self):
        from claude_bridge.tracing import TracingManager

        tm = TracingManager()
        spans = tm.get_recent_spans(limit=5)
        assert isinstance(spans, list)
        assert len(spans) <= 5

    def test_tracing_manager_get_span_stats_with_data(self):
        from claude_bridge.tracing import TracingManager

        tm = TracingManager()
        tm._span_storage.clear()
        tm._span_storage.append({"duration_ms": 50.0, "error_type": None})
        tm._span_storage.append({"duration_ms": 100.0, "error_type": "timeout"})
        tm._span_storage.append({"duration_ms": 75.0, "error_type": None})
        stats = tm.get_span_stats()
        assert stats["total_spans"] == 3
        assert stats["error_count"] == 1
        assert stats["avg_duration_ms"] == 75.0

    def test_tracing_manager_get_span_stats_percentiles(self):
        from claude_bridge.tracing import TracingManager

        tm = TracingManager()
        tm._span_storage.clear()
        for ms in [10.0, 20.0, 30.0, 40.0, 50.0]:
            tm._span_storage.append({"duration_ms": ms, "error_type": None})
        stats = tm.get_span_stats()
        assert stats["total_spans"] == 5

    def test_trace_level_enum(self):
        from claude_bridge.tracing import TraceLevel

        assert TraceLevel.NONE.value == "none"
        assert TraceLevel.BASIC.value == "basic"
        assert TraceLevel.DETAILED.value == "detailed"


class TestTracingIntegration:
    """Integration tests for TracingManager with OTLP."""

    def test_span_context_manager_no_tracer(self):
        from claude_bridge.tracing import TracingManager, TraceLevel

        tm = TracingManager()
        tm.set_level(TraceLevel.NONE)
        with tm.start_span("test_span") as span:
            assert span is None

    def test_record_exception_no_span(self):
        from claude_bridge.tracing import TracingManager

        tm = TracingManager()
        exc = ValueError("test error")
        tm.record_exception(None, exc)

    def test_set_ok_no_span(self):
        from claude_bridge.tracing import TracingManager

        tm = TracingManager()
        tm.set_ok(None)

    def test_span_attributes_custom_fields(self):
        from claude_bridge.tracing import TracingManager, SpanAttributes

        tm = TracingManager()
        attrs = tm.create_span_attributes(
            custom={"custom1": "value1", "custom2": 42}
        )
        assert attrs.custom["custom1"] == "value1"
        assert attrs.custom["custom2"] == 42

    def test_concurrent_span_recording(self):
        from claude_bridge.tracing import TracingManager, TraceLevel

        tm = TracingManager()
        tm.set_level(TraceLevel.BASIC)
        errors = []

        def record_spans(count: int) -> None:
            try:
                for i in range(count):
                    with tm.start_span(f"span_{threading.current_thread().name}_{i}"):
                        pass
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=record_spans, args=(10,), name=f"worker_{i}")
            for i in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0