"""Integration tests for observability endpoints."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


import pytest

pytestmark = pytest.mark.integration


class TestHealthCheck:
    """Tests for health check functionality."""

    def test_health_endpoint_structure(self):
        from claude_bridge.observability import HealthCheck, HealthStatus

        health = HealthCheck()
        report = health.get_report()
        assert "status" in report
        assert report["status"] in {s.value for s in HealthStatus}

    def test_health_check_components(self):
        from claude_bridge.observability import HealthCheck

        health = HealthCheck()
        assert hasattr(health, "check_components")
        result = health.check_components()
        assert isinstance(result, dict)

    def test_prometheus_metrics_format(self):
        from claude_bridge.observability import PrometheusMetrics

        metrics = PrometheusMetrics()
        output = metrics.render()
        assert "claude_bridge_" in output or output == ""


class TestMetricsCollection:
    """Tests for metrics collection."""

    def test_request_counter(self):
        from claude_bridge.observability import MetricsCollector

        collector = MetricsCollector()
        collector.increment("tool_calls", labels={"tool": "read_file"})
        count = collector.get("tool_calls", labels={"tool": "read_file"})
        assert count == 1

    def test_request_latency(self):
        from claude_bridge.observability import MetricsCollector

        collector = MetricsCollector()
        collector.observe("latency_ms", 50.0, labels={"operation": "shell"})
        value = collector.get_histogram("latency_ms", labels={"operation": "shell"})
        assert value >= 50.0

    def test_metrics_reset(self):
        from claude_bridge.observability import MetricsCollector

        collector = MetricsCollector()
        collector.increment("tool_calls", labels={"tool": "write_file"})
        collector.reset()
        count = collector.get("tool_calls", labels={"tool": "write_file"})
        assert count == 0

    async def test_audited_tool_call_records_metrics(self, temp_project):
        from claude_bridge import server as mcp_server
        from claude_bridge.observability import MetricsCollector

        collector = MetricsCollector()
        collector.reset()

        await mcp_server.workspace_status()
        await mcp_server.workspace_status()

        assert (
            collector.get(
                "claude_bridge_tool_calls_total",
                labels={"tool": "workspace_status"},
            )
            == 2
        )
        assert (
            collector.get_histogram(
                "claude_bridge_tool_call_duration_ms",
                labels={"tool": "workspace_status"},
            )
            >= 0
        )
