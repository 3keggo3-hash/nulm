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
from typing import Any, Callable, cast
from urllib.parse import parse_qs, unquote, urlparse

from claude_bridge.control_plane import (
    ControlPlaneApproval,
    ControlPlaneTask,
    TaskStatus,
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
_DASHBOARD_RECORD_LIMIT = 50
_RECENT_TOOL_CALL_LIMIT = 30
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
_DASHBOARD_WEB_ROOT = Path(__file__).resolve().parents[2] / "web"
_DASHBOARD_INDEX = "index.html"
_TASK_STATUSES: set[str] = {
    "pending",
    "queued",
    "planning",
    "running",
    "in_progress",
    "blocked",
    "approval_pending",
    "testing",
    "failed",
    "completed",
    "cancelled",
}


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
        "schema_version": "control_plane.dashboard.v2",
        "state_dir": str(control_plane_dir()),
        "summary": summarize_tasks(),
        "tasks": tasks,
        "approvals": approvals,
        "messages": list_messages(limit=limit),
        "workspace": _dashboard_workspace(),
        "activity": _safe_dashboard_section(_dashboard_activity, "activity"),
        "usage": _safe_dashboard_section(_dashboard_usage, "usage"),
        "recent_tool_calls": _safe_dashboard_section(
            _dashboard_recent_tool_calls,
            "recent_tool_calls",
        ),
        "health": {
            "available": True,
            "task_limit": limit,
            "recent_tool_call_limit": _RECENT_TOOL_CALL_LIMIT,
        },
    }


def apply_dashboard_action(
    action: str,
    record_id: str,
    *,
    reason: str = "",
    status: str = "",
) -> ControlPlaneTask | ControlPlaneApproval | dict[str, Any]:
    """Apply a supported dashboard mutation to a task or approval."""
    if action == "update-task-status":
        if status not in _TASK_STATUSES:
            raise ControlPlaneDashboardError(f"Unsupported task status '{status}'")
        task = update_task_status(
            record_id,
            cast(TaskStatus, status),
            summary=reason or None,
            metadata=(
                {"dashboard_reason": reason, "updated_by": "dashboard"}
                if reason
                else {"updated_by": "dashboard"}
            ),
        )
        if task is None:
            raise ControlPlaneDashboardError(f"Task '{record_id}' not found")
        return task
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
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "tasks":
                _, collection, record_id, action = parts
                if collection == "tasks" and action == "status":
                    reason = _string_body_value(body, "reason")
                    status_value = _string_body_value(body, "status")
                    try:
                        action_record = apply_dashboard_action(
                            "update-task-status",
                            record_id,
                            reason=reason,
                            status=status_value,
                        )
                    except ControlPlaneDashboardError as exc:
                        error_status = 400 if "Unsupported task status" in str(exc) else 404
                        self._send_json({"error": str(exc)}, status=error_status)
                        return
                    self._send_json({"ok": True, "record": action_record})
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


def _dashboard_workspace() -> dict[str, Any]:
    from claude_bridge.config import current_config

    config = current_config()
    return {
        "available": True,
        "active_project_dir": str(config.get("project_dir", "")),
        "allowed_roots": [str(root) for root in config.get("allowed_roots", [])],
        "approval": {
            "auto_approve": bool(config.get("auto_approve", False)),
            "client_managed_approval": bool(config.get("client_managed_approval", False)),
            "approval_preset": str(config.get("approval_preset", "")),
            "auto_approve_risk_level": str(config.get("auto_approve_risk_level", "")),
        },
        "profile": {
            "tool_profile": str(config.get("tool_profile", "")),
            "context_budget_profile": str(config.get("context_budget_profile", "")),
            "max_parallel": int(config.get("max_parallel", 0) or 0),
        },
    }


def _dashboard_activity() -> dict[str, Any]:
    from claude_bridge.audit import summarize_session

    summary = summarize_session(limit=_DASHBOARD_RECORD_LIMIT)
    return {
        "available": True,
        "session_id": summary.get("session_id", ""),
        "total_records": summary.get("total_records", 0),
        "returned_records": summary.get("returned_records", 0),
        "failure_count": summary.get("failure_count", 0),
        "tool_counts": summary.get("tool_counts", {}),
        "activity": summary.get("activity", {}),
        "anomaly_counts": summary.get("anomaly_counts", {}),
    }


def _dashboard_usage() -> dict[str, Any]:
    from claude_bridge.audit import summarize_session

    summary = summarize_session(limit=_DASHBOARD_RECORD_LIMIT)
    telemetry = summary.get("telemetry", {})
    top_tools: list[dict[str, Any]] = []
    if isinstance(telemetry, dict):
        token_totals = telemetry.get("tool_estimated_tokens", {})
        if isinstance(token_totals, dict):
            top_tools = [
                {"tool_name": str(tool_name), "estimated_tokens": int(tokens)}
                for tool_name, tokens in sorted(
                    token_totals.items(),
                    key=lambda item: int(item[1]),
                    reverse=True,
                )
            ][:10]
    return {
        "available": True,
        "session_id": summary.get("session_id", ""),
        "telemetry": telemetry if isinstance(telemetry, dict) else {},
        "top_cost_tools": top_tools,
    }


def _dashboard_recent_tool_calls() -> dict[str, Any]:
    from claude_bridge.audit import get_recent_tool_calls

    recent = get_recent_tool_calls(limit=_RECENT_TOOL_CALL_LIMIT)
    records = recent.get("records", [])
    safe_records = [_summarize_tool_call(record) for record in records if isinstance(record, dict)]
    return {
        "available": True,
        "session_id": recent.get("session_id", ""),
        "total_records": recent.get("total_records", 0),
        "returned_records": len(safe_records),
        "query_strategy": recent.get("query_strategy", ""),
        "records": safe_records,
    }


def _summarize_tool_call(record: dict[str, Any]) -> dict[str, Any]:
    result = record.get("result", {})
    result_summary = result if isinstance(result, dict) else {}
    telemetry = record.get("telemetry", {})
    telemetry_summary = telemetry if isinstance(telemetry, dict) else {}
    return {
        "record_id": record.get("record_id", ""),
        "timestamp": record.get("timestamp", ""),
        "session_id": record.get("session_id", ""),
        "tool_name": record.get("tool_name", "unknown"),
        "duration_ms": record.get("duration_ms", 0),
        "ok": result_summary.get("ok"),
        "message": result_summary.get("message", ""),
        "code": result_summary.get("code", ""),
        "decision_action": record.get("decision_action", ""),
        "decision_source": record.get("decision_source", ""),
        "decision_risk_level": record.get("decision_risk_level", ""),
        "telemetry": {
            "estimated_total_tokens": telemetry_summary.get("estimated_total_tokens", 0),
            "result_truncated": bool(telemetry_summary.get("result_truncated", False)),
        },
    }


def _safe_dashboard_section(builder: Callable[[], dict[str, Any]], name: str) -> dict[str, Any]:
    try:
        section = builder()
    except Exception as exc:  # pragma: no cover - defensive local dashboard resilience
        return {"available": False, "name": name, "error": str(exc)}
    if isinstance(section, dict):
        return section
    return {"available": False, "name": name, "error": "invalid_dashboard_section"}


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
