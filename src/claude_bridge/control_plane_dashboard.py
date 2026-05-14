"""Local-only HTTP dashboard for the control plane."""

from __future__ import annotations

import hmac
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from claude_bridge.control_plane import (
    ControlPlaneApproval,
    ControlPlaneTask,
    control_plane_dir,
    list_approvals,
    list_tasks,
    resolve_approval,
    summarize_tasks,
    update_task_status,
)

DEFAULT_DASHBOARD_HOST = "127.0.0.1"
DEFAULT_DASHBOARD_PORT = 8765
MAX_ACTION_BODY_BYTES = 8192
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


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
    }


def apply_dashboard_action(
    action: str,
    record_id: str,
    *,
    reason: str = "",
) -> ControlPlaneTask | ControlPlaneApproval:
    """Apply a supported dashboard mutation to a task or approval."""
    if action == "cancel-task":
        task = update_task_status(
            record_id,
            "cancelled",
            summary=reason or None,
            metadata={"dashboard_reason": reason} if reason else None,
        )
        if task is None:
            raise ControlPlaneDashboardError(f"Task '{record_id}' not found")
        return task
    if action == "approve":
        approval = resolve_approval(
            record_id,
            "approved",
            reason=reason,
            metadata={"dashboard_reason": reason} if reason else None,
        )
        if approval is None:
            raise ControlPlaneDashboardError(f"Approval '{record_id}' not found")
        return approval
    if action == "reject":
        approval = resolve_approval(
            record_id,
            "denied",
            reason=reason,
            metadata={"dashboard_reason": reason} if reason else None,
        )
        if approval is None:
            raise ControlPlaneDashboardError(f"Approval '{record_id}' not found")
        return approval
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
                self._send_html(_dashboard_html(token))
                return
            if parsed.path == "/api/status":
                if not self._is_authorized(parsed.query):
                    self._send_json({"error": "unauthorized"}, status=401)
                    return
                self._send_json(build_dashboard_payload())
                return
            self._send_json({"error": "not_found"}, status=404)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if not self._is_authorized(parsed.query):
                self._send_json({"error": "unauthorized"}, status=401)
                return
            parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
            if len(parts) != 4 or parts[0] != "api":
                self._send_json({"error": "not_found"}, status=404)
                return
            _, collection, record_id, action = parts
            reason = self._read_reason()
            try:
                if collection == "tasks" and action == "cancel":
                    record = apply_dashboard_action("cancel-task", record_id, reason=reason)
                elif collection == "approvals" and action == "approve":
                    record = apply_dashboard_action("approve", record_id, reason=reason)
                elif collection == "approvals" and action == "reject":
                    record = apply_dashboard_action("reject", record_id, reason=reason)
                else:
                    self._send_json({"error": "unsupported_action"}, status=400)
                    return
            except ControlPlaneDashboardError as exc:
                self._send_json({"error": str(exc)}, status=404)
                return
            self._send_json({"ok": True, "record": record})

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _is_authorized(self, query: str) -> bool:
            supplied = self.headers.get("X-Claude-Bridge-Token", "")
            if not supplied:
                supplied = parse_qs(query).get("token", [""])[0]
            return bool(supplied) and hmac.compare_digest(supplied, token)

        def _read_reason(self) -> str:
            raw_length = self.headers.get("Content-Length", "0")
            try:
                length = min(int(raw_length), MAX_ACTION_BODY_BYTES)
            except ValueError:
                length = 0
            if length <= 0:
                return ""
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            if "application/json" in self.headers.get("Content-Type", ""):
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    return ""
                if isinstance(body, dict):
                    reason = body.get("reason", "")
                    return reason if isinstance(reason, str) else ""
                return ""
            return parse_qs(raw).get("reason", [""])[0]

        def _send_html(self, html: str) -> None:
            encoded = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
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

    return ControlPlaneDashboardHandler


def _dashboard_html(token: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Claude Bridge Control Plane</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #f8fafc;
      --fg: #111827;
      --muted: #6b7280;
      --line: #d1d5db;
      --panel: #ffffff;
      --accent: #0f766e;
      --danger: #b91c1c;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #111827;
        --fg: #f9fafb;
        --muted: #9ca3af;
        --line: #374151;
        --panel: #1f2937;
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--fg);
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header, main {{ max-width: 1120px; margin: 0 auto; padding: 20px; }}
    header {{ display: flex; justify-content: space-between; gap: 16px; align-items: center; }}
    h1 {{ font-size: 22px; margin: 0; }}
    h2 {{ font-size: 16px; margin: 0 0 12px; }}
    .muted {{ color: var(--muted); }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-width: 0;
    }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 8px; border-top: 1px solid var(--line); }}
    th {{ color: var(--muted); font-weight: 600; }}
    code {{ overflow-wrap: anywhere; }}
    button {{
      border: 1px solid var(--line);
      border-radius: 6px;
      background: transparent;
      color: var(--fg);
      padding: 5px 8px;
      cursor: pointer;
    }}
    button.primary {{ border-color: var(--accent); color: var(--accent); }}
    button.danger {{ border-color: var(--danger); color: var(--danger); }}
    .actions {{ display: flex; gap: 6px; flex-wrap: wrap; }}
    @media (max-width: 820px) {{
      header {{ display: block; }}
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Control Plane</h1>
      <div class="muted" id="state"></div>
    </div>
    <button onclick="load()">Refresh</button>
  </header>
  <main class="grid">
    <section>
      <h2>Tasks</h2>
      <div id="tasks"></div>
    </section>
    <section>
      <h2>Approvals</h2>
      <div id="approvals"></div>
    </section>
  </main>
  <script>
    const token = {json.dumps(token)};
    async function load() {{
      const res = await fetch('/api/status?token=' + encodeURIComponent(token));
      const data = await res.json();
      document.getElementById('state').textContent = data.state_dir || '';
      renderTasks(data.tasks || []);
      renderApprovals(data.approvals || []);
    }}
    async function post(path) {{
      await fetch(path + '?token=' + encodeURIComponent(token), {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ reason: 'dashboard' }})
      }});
      await load();
    }}
    function esc(value) {{
      return String(value || '').replace(/[&<>"']/g, ch => ({{
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }}[ch]));
    }}
    function renderTasks(tasks) {{
      document.getElementById('tasks').innerHTML = table(tasks, row => `
        <td><code>${{esc(row.id)}}</code></td>
        <td>${{esc(row.status)}}</td>
        <td>${{esc(row.title)}}</td>
        <td class="actions">
          <button class="danger" onclick="post('/api/tasks/${{esc(row.id)}}/cancel')">Cancel</button>
        </td>`);
    }}
    function renderApprovals(approvals) {{
      document.getElementById('approvals').innerHTML = table(approvals, row => `
        <td><code>${{esc(row.id)}}</code></td>
        <td>${{esc(row.status)}}</td>
        <td>${{esc(row.title)}}</td>
        <td class="actions">
          <button class="primary" onclick="post('/api/approvals/${{esc(row.id)}}/approve')">Approve</button>
          <button class="danger" onclick="post('/api/approvals/${{esc(row.id)}}/reject')">Reject</button>
        </td>`);
    }}
    function table(rows, cells) {{
      if (!rows.length) return '<p class="muted">No records.</p>';
      return `<table><thead><tr><th>ID</th><th>Status</th><th>Title</th><th></th></tr></thead>
        <tbody>${{rows.map(row => `<tr>${{cells(row)}}</tr>`).join('')}}</tbody></table>`;
    }}
    load();
  </script>
</body>
</html>"""
