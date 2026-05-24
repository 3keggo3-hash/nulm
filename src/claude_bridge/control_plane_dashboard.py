"""Local-only HTTP dashboard for the control plane."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import mimetypes
import os
import secrets
import shlex
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, cast
from urllib.parse import parse_qs, unquote, urlparse

from claude_bridge.control_plane import (
    ControlPlaneApproval,
    MessageStatus,
    ControlPlaneTask,
    TaskStatus,
    create_message,
    control_plane_dir,
    list_approvals,
    list_messages,
    list_tasks,
    resolve_approval,
    summarize_tasks,
    update_message_status,
    update_task_status,
)
from claude_bridge.config import update_runtime_config

try:
    import websockets
except ImportError:
    websockets = None

_SSE_CLIENTS: set[Any] = set()
_SSE_CLIENTS_LOCK = threading.Lock()
_SSE_BROADCAST_EVENT = threading.Event()
_PENDING_EVENTS: list[tuple[str, dict[str, Any]]] = []
_PENDING_EVENTS_LOCK = threading.Lock()


def _queue_event(event_name: str, data: dict[str, Any]) -> None:
    with _PENDING_EVENTS_LOCK:
        _PENDING_EVENTS.append((event_name, data))
    _SSE_BROADCAST_EVENT.set()


def _consume_pending_events() -> list[tuple[str, dict[str, Any]]]:
    with _PENDING_EVENTS_LOCK:
        events = list(_PENDING_EVENTS)
        _PENDING_EVENTS.clear()
    return events


DEFAULT_DASHBOARD_HOST = "127.0.0.1"
DEFAULT_DASHBOARD_PORT = 8765
MAX_ACTION_BODY_BYTES = 8192
_DASHBOARD_RECORD_LIMIT = 50
_RECENT_TOOL_CALL_LIMIT = 30
_CLI_TIMEOUT_SECONDS = 20
_CLI_OUTPUT_LIMIT = 12000
_STREAMING_POLL_INTERVAL = 0.3
_ACTIVE_CLI_SESSIONS: dict[str, dict[str, Any]] = {}
_ACTIVE_CLI_SESSIONS_LOCK = threading.Lock()
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
_UNSPECIFIED_HOSTS = {"0.0.0.0", "::"}
_TAILSCALE_NETWORK = ipaddress.ip_network("100.64.0.0/10")
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
_ALLOWED_CLI_TOP_LEVEL: set[str] = {
    "--help",
    "--version",
    "version",
    "doctor",
    "envdoctor",
    "policy",
    "control-plane",
    "tasks",
    "approvals",
    "skill",
    "audit",
    "anomaly",
    "sessions",
    "workflow-preview",
}
_ALLOWED_SKILL_SUBCOMMANDS: set[str] = {
    "list",
    "trust-levels",
    "inspect",
    "recommend",
    "packages",
    "package-inspect",
}
_ALLOWED_AUDIT_SUBCOMMANDS: set[str] = {"summary", "export"}
_ALLOWED_ANOMALY_SUBCOMMANDS: set[str] = {"scan"}

CLI_PERMISSION_LEVELS: dict[str, set[str]] = {
    "read_only": {"version", "--version", "--help", "doctor", "envdoctor", "policy", "sessions"},
    "safe_local": {"control-plane", "tasks", "approvals"},
    "needs_approval": {"skill", "audit", "anomaly"},
}

_COMMANDS_BY_LEVEL: dict[str, set[str]] = {
    "read_only": CLI_PERMISSION_LEVELS["read_only"],
    "safe_local": CLI_PERMISSION_LEVELS["safe_local"],
    "needs_approval": CLI_PERMISSION_LEVELS["needs_approval"],
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
        _queue_event("approval", {"id": record_id, "status": "approved", "action": action})
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
        _queue_event("approval", {"id": record_id, "status": "denied", "action": action})
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
        _queue_event(
            "approval",
            {"id": record_id, "status": "approved", "action": action, "allow_always": True},
        )
        return {"approval": resolved, "pattern": {"tool": tool, "pattern": pattern}}
    raise ControlPlaneDashboardError(f"Unsupported dashboard action '{action}'")


def run_dashboard_cli_command(command: str, *, background: bool = False) -> dict[str, Any]:
    """Run a guarded Nulm CLI command submitted from the dashboard."""
    message = create_message(
        command,
        metadata={"source": "dashboard", "kind": "cli"},
    )
    try:
        args = _dashboard_cli_args(command)
        acknowledged = update_message_status(
            message["id"],
            "acknowledged",
            response="Running...",
            metadata={"source": "dashboard", "kind": "cli", "argv": args},
        )
        if background:
            session_id = message["id"]
            with _ACTIVE_CLI_SESSIONS_LOCK:
                _ACTIVE_CLI_SESSIONS[session_id] = {
                    "message_id": message["id"],
                    "command": command,
                    "argv": args,
                    "status": "running",
                    "stdout_chunks": [],
                    "stderr_chunks": [],
                    "output": "",
                    "returncode": None,
                    "started_at": time.time(),
                    "updated_at": time.time(),
                }
            threading.Thread(
                target=_run_cli_background,
                args=(session_id, command, args),
                daemon=True,
            ).start()
            return {"ok": True, "session_id": session_id, "record": acknowledged or message}
        result = subprocess.run(
            [sys.executable, "-m", "claude_bridge", *args],
            cwd=Path.cwd(),
            env=dict(os.environ),
            capture_output=True,
            text=True,
            timeout=_CLI_TIMEOUT_SECONDS,
            shell=False,
            check=False,
        )
        output = _format_cli_output(result.returncode, result.stdout, result.stderr)
        status = cast(MessageStatus, "completed" if result.returncode == 0 else "failed")
        completed = update_message_status(
            message["id"],
            status,
            response=output,
            metadata={
                "source": "dashboard",
                "kind": "cli",
                "argv": args,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )
        return {"ok": result.returncode == 0, "record": completed or acknowledged or message}
    except (ControlPlaneDashboardError, ValueError) as exc:
        failed = update_message_status(
            message["id"],
            "failed",
            response=str(exc),
            metadata={"source": "dashboard", "kind": "cli"},
        )
        return {"ok": False, "record": failed or message, "error": str(exc)}
    except subprocess.TimeoutExpired:
        failed = update_message_status(
            message["id"],
            "failed",
            response=f"Command timed out after {_CLI_TIMEOUT_SECONDS} seconds.",
            metadata={
                "source": "dashboard",
                "kind": "cli",
                "timeout_seconds": _CLI_TIMEOUT_SECONDS,
            },
        )
        return {"ok": False, "record": failed or message, "error": "command_timeout"}


def _run_cli_background(session_id: str, command: str, args: list[str]) -> None:
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "claude_bridge", *args],
            cwd=Path.cwd(),
            env=dict(os.environ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )
        session = _ACTIVE_CLI_SESSIONS.get(session_id)
        if session is None:
            proc.kill()
            return
        session["process"] = proc
        while True:
            poll = proc.poll()
            if poll is not None:
                break
            time.sleep(_STREAMING_POLL_INTERVAL)
        time.sleep(0.1)
        stdout, stderr = proc.communicate()
        if session is None:
            return
        with _ACTIVE_CLI_SESSIONS_LOCK:
            session["returncode"] = proc.returncode
            session["stdout"] = stdout
            session["stderr"] = stderr
            session["output"] = _format_cli_output(proc.returncode, stdout, stderr)
            session["updated_at"] = time.time()
            if session["status"] == "running":
                session["status"] = "completed"
        output = _format_cli_output(proc.returncode, stdout, stderr)
        status = cast(MessageStatus, "completed" if proc.returncode == 0 else "failed")
        update_message_status(
            session["message_id"],
            status,
            response=output,
            metadata={
                "source": "dashboard",
                "kind": "cli",
                "argv": args,
                "returncode": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
            },
        )
    except Exception as exc:
        msg_id: str | None = None
        with _ACTIVE_CLI_SESSIONS_LOCK:
            session = _ACTIVE_CLI_SESSIONS.get(session_id)
            if session:
                session["status"] = "failed"
                session["output"] = str(exc)
                session["updated_at"] = time.time()
                msg_id = session.get("message_id")
        if msg_id:
            try:
                update_message_status(
                    msg_id,
                    "failed",
                    response=str(exc),
                    metadata={"source": "dashboard", "kind": "cli"},
                )
            except Exception:
                pass


def _dashboard_cli_args(command: str) -> list[str]:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise ControlPlaneDashboardError(f"Could not parse command: {exc}") from exc
    if not parts:
        raise ControlPlaneDashboardError("Command is required")
    executable = Path(parts[0]).name
    if executable not in {"nulm", "claude-bridge"}:
        raise ControlPlaneDashboardError(
            "Only 'nulm ...' and 'claude-bridge ...' commands run here"
        )
    args = parts[1:] or ["--help"]
    _validate_dashboard_cli_args(args)
    return args


def _validate_dashboard_cli_args(args: list[str]) -> str:
    top_level = args[0]
    level = _get_command_permission_level(top_level)
    if level is None:
        raise ControlPlaneDashboardError(
            f"Command '{top_level}' is blocked from dashboard execution"
        )
    if level == "needs_approval":
        raise ControlPlaneDashboardError(
            f"Command '{top_level}' requires approval. Use the Approvals tab first."
        )
    if top_level == "skill" and len(args) > 1 and args[1] not in _ALLOWED_SKILL_SUBCOMMANDS:
        raise ControlPlaneDashboardError(f"Unsupported dashboard skill command '{args[1]}'")
    if top_level == "audit" and len(args) > 1 and args[1] not in _ALLOWED_AUDIT_SUBCOMMANDS:
        raise ControlPlaneDashboardError(f"Unsupported dashboard audit command '{args[1]}'")
    if top_level == "anomaly" and len(args) > 1 and args[1] not in _ALLOWED_ANOMALY_SUBCOMMANDS:
        raise ControlPlaneDashboardError(f"Unsupported dashboard anomaly command '{args[1]}'")
    return level


def _get_command_permission_level(command: str) -> str | None:
    for level, commands in _COMMANDS_BY_LEVEL.items():
        if command in commands:
            return level
    return None


def _format_cli_output(returncode: int, stdout: str, stderr: str) -> str:
    sections = [f"exit={returncode}"]
    if stdout.strip():
        sections.append(stdout.strip())
    if stderr.strip():
        sections.append("stderr:\n" + stderr.strip())
    output = "\n\n".join(sections)
    if len(output) > _CLI_OUTPUT_LIMIT:
        return output[:_CLI_OUTPUT_LIMIT] + "\n\n[output truncated]"
    return output


def _get_cli_session_status(session_id: str) -> dict[str, Any]:
    with _ACTIVE_CLI_SESSIONS_LOCK:
        session = _ACTIVE_CLI_SESSIONS.get(session_id)
    if session is None:
        return {"error": "session_not_found", "status": "unknown"}
    return {
        "session_id": session_id,
        "status": session["status"],
        "output": session.get("output", ""),
        "stdout": session.get("stdout", ""),
        "stderr": session.get("stderr", ""),
        "returncode": session.get("returncode"),
        "updated_at": session.get("updated_at"),
    }


def create_dashboard_server(
    *,
    host: str = DEFAULT_DASHBOARD_HOST,
    port: int = DEFAULT_DASHBOARD_PORT,
    token: str | None = None,
    expose_token_in_config: bool = True,
    allow_network_bind: bool = False,
) -> tuple[ThreadingHTTPServer, str]:
    """Create a local-only dashboard server and return it with the active token."""
    if not _dashboard_host_allowed(host, allow_network_bind=allow_network_bind):
        raise ValueError(
            "Control-plane dashboard binds to loopback by default. Use --lan, --vpn, "
            "or --public for explicit remote access."
        )
    resolved_token = token or generate_dashboard_token()
    handler = _make_handler(resolved_token, expose_token_in_config=expose_token_in_config)
    http_server = ThreadingHTTPServer((host, port), handler)
    _start_terminal_ws(host, port + 1, resolved_token)
    return http_server, resolved_token


def _start_terminal_ws(host: str, port: int, token: str) -> None:
    if websockets is None:
        return
    from claude_bridge.web.terminal import create_terminal_session

    async def _ws_handler(websocket: Any, path: str) -> None:
        if path != "/api/terminal":
            await websocket.close(4004, "Invalid path")
            return
        auth_header = websocket.request_headers.get("X-Claude-Bridge-Token", "")
        if not auth_header or not hmac.compare_digest(auth_header, token):
            await websocket.close(4003, "Unauthorized")
            return
        session_id = str(id(websocket))
        session = create_terminal_session(session_id, token)
        if not session.start():
            await websocket.close(4005, "Failed to start shell")
            return
        output_thread = threading.Thread(
            target=_read_ws_output,
            args=(session, websocket),
            daemon=True,
        )
        output_thread.start()
        try:
            async for message in websocket:
                if isinstance(message, bytes):
                    session.write(message)
                else:
                    try:
                        data = json.loads(message)
                        if data.get("type") == "resize":
                            rows = data.get("rows", 24)
                            cols = data.get("cols", 80)
                            session.resize(rows, cols)
                        elif data.get("type") == "input":
                            input_data = data.get("data", "")
                            if isinstance(input_data, str):
                                session.write(input_data.encode("utf-8"))
                            elif isinstance(input_data, bytes):
                                session.write(input_data)
                    except (json.JSONDecodeError, KeyError):
                        session.write(
                            message.encode("utf-8") if isinstance(message, str) else message
                        )
        except Exception:
            pass
        finally:
            from claude_bridge.web.terminal import close_terminal_session

            close_terminal_session(session_id)

    def _read_ws_output(session: Any, websocket: Any) -> None:
        while session.is_alive():
            data = session.read(timeout=0.05)
            if data:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(websocket.send(data))
                    else:
                        loop.run_until_complete(websocket.send(data))
                except Exception:
                    pass

    async def _run_ws() -> None:
        async with websockets.serve(_ws_handler, host, port):
            await asyncio.Future()

    def _bg_ws() -> None:
        asyncio.run(_run_ws())

    thread = threading.Thread(target=_bg_ws, daemon=True)
    thread.start()


def _dashboard_host_allowed(host: str, *, allow_network_bind: bool) -> bool:
    if host in _LOOPBACK_HOSTS:
        return True
    if not allow_network_bind:
        return False
    if host in _UNSPECIFIED_HOSTS:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address in _TAILSCALE_NETWORK
    )


def _make_handler(
    token: str,
    *,
    expose_token_in_config: bool,
) -> type[BaseHTTPRequestHandler]:
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
            if parsed.path.startswith("/api/cli/"):
                parts = parsed.path.strip("/").split("/")
                if len(parts) == 4 and parts[2] == "stream":
                    if not self._is_authorized(parsed.query):
                        self._send_json({"error": "unauthorized"}, status=401)
                        return
                    session_id = parts[3]
                    self._send_json(_get_cli_session_status(session_id))
                    return
            if parsed.path.startswith("/api/agent/"):
                parts = parsed.path.strip("/").split("/")
                if len(parts) == 3 and parts[1] == "task":
                    if not self._is_authorized(parsed.query):
                        self._send_json({"error": "unauthorized"}, status=401)
                        return
                    task_id = parts[2]
                    from claude_bridge._dashboard_task_runner import get_dashboard_task_status

                    self._send_json(get_dashboard_task_status(task_id))
                    return
            if parsed.path == "/api/events":
                if not self._is_authorized(parsed.query):
                    self._send_json({"error": "unauthorized"}, status=401)
                    return
                self._send_sse_stream()
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
            if len(parts) == 2 and parts == ["api", "cli"]:
                command = body.get("command", "")
                if not isinstance(command, str) or not command.strip():
                    self._send_json({"error": "command_required"}, status=400)
                    return
                background = body.get("background", False)
                self._send_json(run_dashboard_cli_command(command.strip(), background=background))
                return
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "tasks":
                _, collection, record_id, action = parts
                if collection == "tasks" and action == "status":
                    reason = _string_body_value(body, "reason")
                    status_value = _string_body_value(body, "status")
                    try:
                        task_action_record = apply_dashboard_action(
                            "update-task-status",
                            record_id,
                            reason=reason,
                            status=status_value,
                        )
                    except ControlPlaneDashboardError as exc:
                        error_status = 400 if "Unsupported task status" in str(exc) else 404
                        self._send_json({"error": str(exc)}, status=error_status)
                        return
                    self._send_json({"ok": True, "record": task_action_record})
                    return
            if len(parts) == 3 and parts[0] == "api" and parts[1] == "agent":
                task = body.get("task", "")
                mode = body.get("mode", "agent_loop")
                if not isinstance(task, str) or not task.strip():
                    self._send_json({"error": "task_required"}, status=400)
                    return
                from claude_bridge._dashboard_task_runner import run_dashboard_task

                self._send_json(run_dashboard_task(task.strip(), mode=mode))
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

        def _send_sse_stream(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            client = self.wfile
            with _SSE_CLIENTS_LOCK:
                _SSE_CLIENTS.add(client)
            try:
                while True:
                    if _SSE_BROADCAST_EVENT.wait(timeout=30):
                        _SSE_BROADCAST_EVENT.clear()
                        events = _consume_pending_events()
                        for event_name, event_data in events:
                            encoded = (
                                f"event: {event_name}\ndata: {json.dumps(event_data)}\n\n".encode(
                                    "utf-8"
                                )
                            )
                            try:
                                client.write(encoded)
                                client.flush()
                            except OSError:
                                break
            except OSError:
                pass
            finally:
                with _SSE_CLIENTS_LOCK:
                    _SSE_CLIENTS.discard(client)

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
                "token": token if expose_token_in_config else "",
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
        "agent_runs": summary.get("agent_runs", {}),
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
