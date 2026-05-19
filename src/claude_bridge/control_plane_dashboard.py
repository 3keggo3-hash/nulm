"""Local-only HTTP dashboard for the control plane."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import hmac
import json
import mimetypes
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from claude_bridge.control_plane import (
    ControlPlaneApproval,
    ControlPlaneTask,
    create_message,
    control_plane_dir,
    list_approvals,
    list_messages,
    list_tasks,
    resolve_approval,
    summarize_tasks,
    update_task_status,
)
from claude_bridge.config import update_runtime_config

DEFAULT_DASHBOARD_HOST = "127.0.0.1"
DEFAULT_DASHBOARD_PORT = 8765
MAX_ACTION_BODY_BYTES = 8192
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
_DASHBOARD_WEB_ROOT = Path(__file__).resolve().parents[2] / "web"
_DASHBOARD_INDEX = "index.html"


class ControlPlaneDashboardError(ValueError):
    """Raised when a dashboard action cannot be applied."""


def generate_dashboard_token() -> str:
    """Return a URL-safe bearer token for the local dashboard session."""
    return secrets.token_urlsafe(24)


def build_dashboard_payload(*, limit: int = 50) -> dict[str, Any]:
    """Return the dashboard's read model."""
    tasks = list_tasks(limit=limit)
    approvals = list_approvals(limit=limit)
    return {
        "schema_version": "control_plane.dashboard.v1",
        "state_dir": str(control_plane_dir()),
        "summary": summarize_tasks(),
        "tasks": tasks,
        "approvals": approvals,
        "messages": list_messages(limit=limit),
    }


def apply_dashboard_action(
    action: str,
    record_id: str,
    *,
    reason: str = "",
) -> ControlPlaneTask | ControlPlaneApproval | dict[str, Any]:
    """Apply a supported dashboard mutation to a task or approval."""
    if action == "cancel-task":
        task = update_task_status(
            record_id,
            "cancelled",
            summary=reason or None,
            metadata=(
                {"dashboard_reason": reason, "cancelled_by": "dashboard"}
                if reason
                else {"cancelled_by": "dashboard"}
            ),
        )
        if task is None:
            raise ControlPlaneDashboardError(f"Task '{record_id}' not found")
        return task
    if action == "approve":
        approval = resolve_approval(
            record_id,
            "approved",
            reason=reason,
            metadata=(
                {"dashboard_reason": reason, "decided_by": "dashboard"}
                if reason
                else {"decided_by": "dashboard"}
            ),
        )
        if approval is None:
            raise ControlPlaneDashboardError(f"Approval '{record_id}' not found")
        return approval
    if action == "reject":
        approval = resolve_approval(
            record_id,
            "denied",
            reason=reason,
            metadata=(
                {"dashboard_reason": reason, "decided_by": "dashboard"}
                if reason
                else {"decided_by": "dashboard"}
            ),
        )
        if approval is None:
            raise ControlPlaneDashboardError(f"Approval '{record_id}' not found")
        return approval
    if action == "allow_always":
        from claude_bridge.control_plane import get_approval
        from claude_bridge.config import auto_approve_patterns

        approval = get_approval(record_id)
        if approval is None:
            raise ControlPlaneDashboardError(f"Approval '{record_id}' not found")
        tool = approval.get("tool", "")
        command = approval.get("command", "")
        if not tool or not command:
            raise ControlPlaneDashboardError(
                f"Approval '{record_id}' has no tool/command for pattern extraction"
            )
        pattern = command.split()[0] if command.split() else command
        if not pattern:
            raise ControlPlaneDashboardError(f"Could not extract pattern from command '{command}'")
        current_patterns = dict(auto_approve_patterns())
        tool_patterns = list(current_patterns.get(tool, []))
        if pattern not in tool_patterns:
            tool_patterns.append(pattern)
        current_patterns[tool] = tool_patterns
        update_runtime_config("auto_approve_patterns", current_patterns)
        resolved = resolve_approval(
            record_id,
            "approved",
            reason=reason,
            metadata=(
                {
                    "dashboard_reason": reason,
                    "decided_by": "dashboard",
                    "allow_always_pattern": pattern,
                }
                if reason
                else {"decided_by": "dashboard", "allow_always_pattern": pattern}
            ),
        )
        if resolved is None:
            raise ControlPlaneDashboardError(f"Approval '{record_id}' not found")
        return {"approval": resolved, "pattern": {"tool": tool, "pattern": pattern}}
    raise ControlPlaneDashboardError(f"Unsupported dashboard action '{action}'")


def create_dashboard_server(
    *,
    host: str = DEFAULT_DASHBOARD_HOST,
    port: int = DEFAULT_DASHBOARD_PORT,
    token: str | None = None,
) -> tuple[ThreadingHTTPServer, str]:
    """Create a local-only dashboard server and return it with the active token."""
    if host not in _LOOPBACK_HOSTS:
        raise ValueError("Control-plane dashboard only binds to localhost or loopback hosts")
    resolved_token = token or generate_dashboard_token()
    handler = _make_handler(resolved_token)
    return ThreadingHTTPServer((host, port), handler), resolved_token


def _make_handler(token: str) -> type[BaseHTTPRequestHandler]:
    class ControlPlaneDashboardHandler(BaseHTTPRequestHandler):
        server_version = "ClaudeBridgeControlPlane/1.0"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_static_file(_DASHBOARD_INDEX)
                return
            if parsed.path == "/dashboard-config.js":
                self._send_dashboard_config()
                return
            if parsed.path == "/api/status":
                if not self._is_authorized(parsed.query):
                    self._send_json({"error": "unauthorized"}, status=401)
                    return
                self._send_json(build_dashboard_payload())
                return
            if parsed.path == "/api/messages":
                if not self._is_authorized(parsed.query):
                    self._send_json({"error": "unauthorized"}, status=401)
                    return
                self._send_json(
                    {
                        "schema_version": "control_plane.messages.v1",
                        "messages": list_messages(limit=50),
                    }
                )
                return
            if self._send_static_file(parsed.path.lstrip("/")):
                return
            self._send_json({"error": "not_found"}, status=404)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if not self._is_authorized(parsed.query):
                self._send_json({"error": "unauthorized"}, status=401)
                return
            parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
            body = self._read_body()
            if len(parts) == 2 and parts == ["api", "messages"]:
                message = body.get("message", "")
                if not isinstance(message, str) or not message.strip():
                    self._send_json({"error": "message_required"}, status=400)
                    return
                message_record = create_message(
                    message.strip(),
                    metadata={"source": "dashboard"},
                )
                self._send_json({"ok": True, "record": message_record})
                return
            if len(parts) != 4 or parts[0] != "api":
                self._send_json({"error": "not_found"}, status=404)
                return
            _, collection, record_id, action = parts
            reason = _string_body_value(body, "reason")
            action_record: Any
            try:
                if collection == "tasks" and action == "cancel":
                    action_record = apply_dashboard_action(
                        "cancel-task",
                        record_id,
                        reason=reason,
                    )
                elif collection == "approvals" and action == "approve":
                    action_record = apply_dashboard_action("approve", record_id, reason=reason)
                elif collection == "approvals" and action == "reject":
                    action_record = apply_dashboard_action("reject", record_id, reason=reason)
                elif collection == "approvals" and action == "allow_always":
                    action_record = apply_dashboard_action("allow_always", record_id, reason=reason)
                else:
                    self._send_json({"error": "unsupported_action"}, status=400)
                    return
            except ControlPlaneDashboardError as exc:
                self._send_json({"error": str(exc)}, status=404)
                return
            self._send_json({"ok": True, "record": action_record})

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _is_authorized(self, query: str) -> bool:
            supplied = self.headers.get("X-Claude-Bridge-Token", "")
            if not supplied:
                supplied = parse_qs(query).get("token", [""])[0]
            return bool(supplied) and hmac.compare_digest(supplied, token)

        def _read_body(self) -> dict[str, Any]:
            raw_length = self.headers.get("Content-Length", "0")
            try:
                length = min(int(raw_length), MAX_ACTION_BODY_BYTES)
            except ValueError:
                length = 0
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            if "application/json" in self.headers.get("Content-Type", ""):
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    return {}
                if isinstance(body, dict):
                    return body
                return {}
            return {key: values[-1] for key, values in parse_qs(raw).items() if values}

        def _send_html(self, html: str) -> None:
            encoded = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_dashboard_config(self) -> None:
            payload = {
                "token": token,
                "apiBaseUrl": "",
            }
            script = "window.__NULM_DASHBOARD__ = " + json.dumps(payload) + ";\n"
            encoded = script.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_static_file(self, relative_path: str) -> bool:
            path = _resolve_dashboard_asset(relative_path)
            if path is None:
                return False
            content_type, _ = mimetypes.guess_type(path.name)
            if content_type is None:
                content_type = "application/octet-stream"
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return True

    return ControlPlaneDashboardHandler


def _string_body_value(body: dict[str, Any], key: str) -> str:
    value = body.get(key, "")
    return value if isinstance(value, str) else ""


def _resolve_dashboard_asset(relative_path: str) -> Path | None:
    requested = Path(relative_path)
    if requested.is_absolute() or ".." in requested.parts:
        return None
    path = (_DASHBOARD_WEB_ROOT / requested).resolve()
    try:
        path.relative_to(_DASHBOARD_WEB_ROOT.resolve())
    except ValueError:
        return None
    if not path.is_file():
        return None
    return path
