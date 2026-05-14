"""Observability module for Claude Bridge: health checks, metrics, and monitoring."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    import prometheus_client as prometheus  # type: ignore[import-not-found]
    from prometheus_client import Counter, Gauge, Histogram  # type: ignore[import-not-found]
except ImportError:
    prometheus = None
    Counter = Gauge = Histogram = None


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthCheckResult:
    component: str
    status: HealthStatus
    message: str | None = None
    latency_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class HealthCheck:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_check: dict[str, HealthCheckResult] = {}
        self._last_check_time: float = 0.0

    def check_components(self) -> dict[str, HealthCheckResult]:
        results: dict[str, HealthCheckResult] = {}
        results["config"] = self._check_config()
        results["audit"] = self._check_audit()
        results["indexing"] = self._check_indexing()
        results["shell"] = self._check_shell()
        with self._lock:
            self._last_check = results
            self._last_check_time = time.time()
        return results

    def _check_config(self) -> HealthCheckResult:
        try:
            from claude_bridge.config import current_config

            config = current_config()
            return HealthCheckResult(
                component="config",
                status=HealthStatus.HEALTHY,
                message="Configuration loaded",
                metadata={"tool_profile": config.get("tool_profile")},
            )
        except Exception as e:
            return HealthCheckResult(
                component="config",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )

    def _check_audit(self) -> HealthCheckResult:
        try:
            from claude_bridge.audit import get_recent_tool_calls

            calls = get_recent_tool_calls()
            return HealthCheckResult(
                component="audit",
                status=HealthStatus.HEALTHY,
                message="Audit system operational",
                metadata={"recent_calls": len(calls)},
            )
        except Exception as e:
            return HealthCheckResult(
                component="audit",
                status=HealthStatus.DEGRADED,
                message=str(e),
            )

    def _check_indexing(self) -> HealthCheckResult:
        try:
            return HealthCheckResult(
                component="indexing",
                status=HealthStatus.HEALTHY,
                message="Indexing system operational",
            )
        except Exception as e:
            return HealthCheckResult(
                component="indexing",
                status=HealthStatus.DEGRADED,
                message=str(e),
            )

    def _check_shell(self) -> HealthCheckResult:
        try:
            return HealthCheckResult(
                component="shell",
                status=HealthStatus.HEALTHY,
                message="Shell system operational",
            )
        except Exception as e:
            return HealthCheckResult(
                component="shell",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )

    def get_report(self) -> dict[str, Any]:
        if not self._last_check or (time.time() - self._last_check_time) > 60:
            self.check_components()
        with self._lock:
            overall = HealthStatus.HEALTHY
            for result in self._last_check.values():
                if result.status == HealthStatus.UNHEALTHY:
                    overall = HealthStatus.UNHEALTHY
                elif result.status == HealthStatus.DEGRADED and overall == HealthStatus.HEALTHY:
                    overall = HealthStatus.DEGRADED
            return {
                "status": overall.value,
                "timestamp": self._last_check_time,
                "components": {
                    k: {
                        "status": v.status.value,
                        "message": v.message,
                        "latency_ms": v.latency_ms,
                        "metadata": v.metadata,
                    }
                    for k, v in self._last_check.items()
                },
            }


class MetricsCollector:
    _instance: MetricsCollector | None = None
    _lock = threading.Lock()

    def __new__(cls) -> "MetricsCollector":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._counters: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}
        self._gauges: dict[str, float] = {}
        self._labels: dict[str, dict[str, str]] = {}
        self._lock_metrics = threading.Lock()
        self._last_update: float = time.time()
        self._initialized: bool = True

    def increment(
        self, name: str, value: float = 1.0, labels: dict[str, str] | None = None
    ) -> None:
        key = self._make_key(name, labels)
        with self._lock_metrics:
            self._counters[key] = self._counters.get(key, 0.0) + value
            self._last_update = time.time()

    def get(self, name: str, labels: dict[str, str] | None = None) -> float:
        key = self._make_key(name, labels)
        with self._lock_metrics:
            return self._counters.get(key, 0.0)

    def get_rate(self, name: str, labels: dict[str, str] | None = None) -> float:
        key = self._make_key(name, labels)
        with self._lock_metrics:
            count = self._counters.get(key, 0.0)
            elapsed = time.time() - self._last_update
            if elapsed <= 0:
                return 0.0
            return count / elapsed

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        key = self._make_key(name, labels)
        with self._lock_metrics:
            if key not in self._histograms:
                self._histograms[key] = []
            self._histograms[key].append(value)
            self._last_update = time.time()

    def get_histogram(self, name: str, labels: dict[str, str] | None = None) -> float:
        key = self._make_key(name, labels)
        with self._lock_metrics:
            values = self._histograms.get(key, [])
            return sum(values) / len(values) if values else 0.0

    def get_percentile(
        self, name: str, percentile: float, labels: dict[str, str] | None = None
    ) -> float:
        key = self._make_key(name, labels)
        with self._lock_metrics:
            values = self._histograms.get(key, [])
            if not values:
                return 0.0
            sorted_values = sorted(values)
            idx = int(len(sorted_values) * percentile / 100.0)
            idx = min(idx, len(sorted_values) - 1)
            return sorted_values[idx]

    def get_histogram_stats(
        self, name: str, labels: dict[str, str] | None = None
    ) -> dict[str, float]:
        key = self._make_key(name, labels)
        with self._lock_metrics:
            values = self._histograms.get(key, [])
            if not values:
                return {"count": 0, "sum": 0, "avg": 0, "min": 0, "max": 0}
            return {
                "count": len(values),
                "sum": sum(values),
                "avg": sum(values) / len(values),
                "min": min(values),
                "max": max(values),
                "p50": self._percentile(sorted(values), 50),
                "p95": self._percentile(sorted(values), 95),
                "p99": self._percentile(sorted(values), 99),
            }

    def _percentile(self, sorted_values: list[float], p: float) -> float:
        if not sorted_values:
            return 0.0
        idx = int(len(sorted_values) * p / 100.0)
        idx = min(idx, len(sorted_values) - 1)
        return sorted_values[idx]

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        key = self._make_key(name, labels)
        with self._lock_metrics:
            self._gauges[key] = value
            self._last_update = time.time()

    def get_gauge(self, name: str, labels: dict[str, str] | None = None) -> float:
        key = self._make_key(name, labels)
        with self._lock_metrics:
            return self._gauges.get(key, 0.0)

    def reset(self) -> None:
        with self._lock_metrics:
            self._counters.clear()
            self._histograms.clear()
            self._gauges.clear()
            self._last_update = time.time()

    def _make_key(self, name: str, labels: dict[str, str] | None) -> str:
        if not labels:
            return name
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock_metrics:
            for key, value in self._counters.items():
                if "{" in key:
                    name = key.split("{")[0]
                    lines.append(f'{name}{{instance="claude-bridge"}} {value}')
                else:
                    lines.append(f"{key} {value}")
            for key, values in self._histograms.items():
                if values:
                    avg = sum(values) / len(values)
                    sorted_vals = sorted(values)
                    p50 = self._percentile(sorted_vals, 50)
                    p95 = self._percentile(sorted_vals, 95)
                    p99 = self._percentile(sorted_vals, 99)
                    if "{" in key:
                        name = key.split("{")[0]
                        lines.append(f'{name}_sum{{instance="claude-bridge"}} {avg}')
                        lines.append(f'{name}_count{{instance="claude-bridge"}} {len(values)}')
                        lines.append(f'{name}_p50{{instance="claude-bridge"}} {p50}')
                        lines.append(f'{name}_p95{{instance="claude-bridge"}} {p95}')
                        lines.append(f'{name}_p99{{instance="claude-bridge"}} {p99}')
                    else:
                        lines.append(f"{key}_sum {avg}")
                        lines.append(f"{key}_count {len(values)}")
                        lines.append(f"{key}_p50 {p50}")
                        lines.append(f"{key}_p95 {p95}")
                        lines.append(f"{key}_p99 {p99}")
            for key, value in self._gauges.items():
                if "{" in key:
                    name = key.split("{")[0]
                    lines.append(f'{name}{{instance="claude-bridge"}} {value}')
                else:
                    lines.append(f"{key} {value}")
        return "\n".join(lines)


class PrometheusMetrics:
    def __init__(self) -> None:
        self._collector = MetricsCollector()

    def render(self) -> str:
        return self._collector.render_prometheus()


_HEALTH_CHECKER: HealthCheck | None = None


def get_health_checker() -> HealthCheck:
    global _HEALTH_CHECKER
    if _HEALTH_CHECKER is None:
        _HEALTH_CHECKER = HealthCheck()
    return _HEALTH_CHECKER


def get_metrics_collector() -> MetricsCollector:
    return MetricsCollector()
