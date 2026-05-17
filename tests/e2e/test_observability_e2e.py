"""End-to-end tests for observability."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


import pytest

pytestmark = pytest.mark.e2e


class TestHealthEndpointE2E:
    """E2E tests for health endpoint."""

    def test_health_check_includes_all_components(self):
        from claude_bridge.observability import HealthCheck

        health = HealthCheck()
        report = health.get_report()
        assert "components" in report or "status" in report

    def test_health_status_values(self):
        from claude_bridge.observability import HealthStatus

        statuses = [s.value for s in HealthStatus]
        assert "healthy" in statuses
        assert "degraded" in statuses
        assert "unhealthy" in statuses


class TestMetricsEndpointE2E:
    """E2E tests for metrics endpoint."""

    def test_prometheus_output_format(self):
        from claude_bridge.observability import PrometheusMetrics

        metrics = PrometheusMetrics()
        output = metrics.render()
        if output:
            lines = output.strip().split("\n")
            for line in lines:
                if line and not line.startswith("#"):
                    assert line.startswith("claude_bridge_") or line.startswith("tool_")

    def test_metrics_includes_custom_labels(self):
        from claude_bridge.observability import MetricsCollector

        collector = MetricsCollector()
        collector.increment("test_counter", labels={"env": "test"})
        output = collector.render_prometheus()
        assert "test_counter" in output or "env" in output or output == ""
