"""Health probe and metrics HTTP server for Kubernetes probes and Prometheus scraping."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import hmac
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

DEFAULT_HEALTH_HOST = "127.0.0.1"
DEFAULT_HEALTH_PORT = 8766
_HEALTH_CONFIG: dict[str, dict[str, Any]] = {
    "CLAUDE_BRIDGE_HEALTH_HOST": {"key": "host", "default": "127.0.0.1"},
    "CLAUDE_BRIDGE_HEALTH_PORT": {"key": "port", "default": 8766},
}
_LIVENESS_CHECK_INTERVAL = 5.0
_process_lock = threading.Lock()
_last_maintained: float = time.time()


def _load_health_config_from_env() -> dict[str, Any]:
    config: dict[str, Any] = {}
    for env_var, spec in _HEALTH_CONFIG.items():
        value: Any = os.environ.get(env_var)
        if value is None:
            value = spec["default"]
        else:
            if spec["key"] == "port":
                value = int(value)
        config[spec["key"]] = value
    return config


def _mark_alive() -> None:
    global _last_maintained
    with _process_lock:
        _last_maintained = time.time()


def _is_live() -> bool:
    with _process_lock:
        return (time.time() - _last_maintained) < (_LIVENESS_CHECK_INTERVAL * 3)


class HealthServerError(Exception):
    """Raised when health server cannot start."""


def generate_health_token() -> str:
    """Return a URL-safe bearer token for health endpoint authentication."""
    return secrets.token_urlsafe(24)


def create_health_server(
    *,
    host: str = DEFAULT_HEALTH_HOST,
    port: int = DEFAULT_HEALTH_PORT,
    token: str | None = None,
) -> tuple[ThreadingHTTPServer, str]:
    resolved_token = token or generate_health_token()
    handler = _make_handler(resolved_token)
    try:
        server = ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        raise HealthServerError(f"Cannot bind to {host}:{port}: {exc}") from exc
    return server, resolved_token


def _make_handler(token: str) -> type[BaseHTTPRequestHandler]:
    class HealthServerHandler(BaseHTTPRequestHandler):
        server_version = "ClaudeBridgeHealth/1.0"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/healthz/live":
                self._handle_liveness()
                return
            if parsed.path == "/healthz/ready" or parsed.path == "/healthz":
                self._handle_readiness()
                return
            if parsed.path == "/metrics":
                self._handle_metrics()
                return
            if parsed.path == "/api/traces":
                self._handle_traces()
                return
            self._send_json({"error": "not_found"}, status=404)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _is_authorized(self, query: str) -> bool:
            supplied = self.headers.get("X-Claude-Bridge-Token", "")
            if not supplied:
                supplied = parse_qs(query).get("token", [""])[0]
            return bool(supplied) and hmac.compare_digest(supplied, token)

        def _handle_liveness(self) -> None:
            if _is_live():
                self._send_json({"status": "alive", "timestamp": time.time()})
            else:
                self._send_json({"status": "deadlocked", "timestamp": time.time()}, status=503)

        def _handle_readiness(self) -> None:
            try:
                from claude_bridge.observability import get_health_checker

                checker = get_health_checker()
                report = checker.get_report()
                overall = report.get("status", "unknown")
                if overall == "healthy":
                    self._send_json(report)
                elif overall == "degraded":
                    self._send_json(report, status=200)
                else:
                    self._send_json(report, status=503)
            except Exception as exc:
                self._send_json(
                    {
                        "status": "unhealthy",
                        "error": str(exc),
                        "components": {},
                    },
                    status=503,
                )

        def _handle_metrics(self) -> None:
            try:
                from claude_bridge.observability import get_metrics_collector

                collector = get_metrics_collector()
                metrics_text = collector.render_prometheus()
                encoded = metrics_text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
            except Exception as exc:
                self._send_json({"error": f"metrics_unavailable: {exc}"}, status=500)

        def _handle_traces(self) -> None:
            if not self._is_authorized(self.path):
                self._send_json({"error": "unauthorized"}, status=401)
                return
            try:
                from claude_bridge.tracing import get_tracing_manager

                manager = get_tracing_manager()
                spans = manager.get_recent_spans(limit=100)
                self._send_json(
                    {
                        "schema_version": "tracing.spans.v1",
                        "count": len(spans),
                        "spans": spans,
                    }
                )
            except Exception as exc:
                self._send_json({"error": f"traces_unavailable: {exc}"}, status=500)

        def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return HealthServerHandler


def start_health_server(
    *,
    host: str | None = None,
    port: int | None = None,
    token: str | None = None,
) -> tuple[ThreadingHTTPServer, str]:
    env_config = _load_health_config_from_env()
    resolved_host = host or env_config.get("host", DEFAULT_HEALTH_HOST)
    resolved_port = port or env_config.get("port", DEFAULT_HEALTH_PORT)
    server, health_token = create_health_server(
        host=resolved_host,
        port=resolved_port,
        token=token,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, health_token
