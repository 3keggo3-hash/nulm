"""Control-plane Typer command registration."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import shutil
import socket
import subprocess
from typing import Any
from urllib.parse import urlencode

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from typer import Typer


def register_control_plane_cli(
    *,
    app: Typer,
    tasks_app: Typer,
    approvals_app: Typer,
    console: Console,
) -> None:
    """Register control-plane related CLI commands."""

    @app.command("dashboard")
    def control_plane_dashboard(
        host: str = typer.Option("127.0.0.1", "--host", help="Host or interface to bind"),
        port: int = typer.Option(8765, "--port", help="Local dashboard port"),
        token: str | None = typer.Option(None, "--token", help="Optional dashboard token"),
        json_output: bool = typer.Option(
            False, "--json", help="Print machine-readable startup info"
        ),
        lan: bool = typer.Option(
            False,
            "--lan",
            help="Expose dashboard only on the local network",
        ),
        vpn: bool = typer.Option(
            False,
            "--vpn",
            help="Expose dashboard only on the local Tailscale VPN address",
        ),
        tunnel: bool = typer.Option(
            False,
            "--tunnel",
            "--public",
            help="Expose dashboard through a temporary Cloudflare tunnel",
        ),
    ) -> None:
        """Serve the local control-plane dashboard on a loopback address."""
        from claude_bridge._tunnel_manager import TunnelManager
        from claude_bridge.control_plane_dashboard import create_dashboard_server

        selected_modes = [name for name, enabled in (("lan", lan), ("vpn", vpn), ("public", tunnel)) if enabled]
        if len(selected_modes) > 1:
            _dashboard_start_error(
                f"Choose only one remote access mode: {', '.join(selected_modes)}",
                json_output,
                console,
            )
        access_mode = selected_modes[0] if selected_modes else "local"
        bind_host = host
        if lan and host == "127.0.0.1":
            bind_host = "0.0.0.0"
        if vpn and host == "127.0.0.1":
            try:
                bind_host = _tailscale_ipv4()
            except RuntimeError as exc:
                _dashboard_start_error(str(exc), json_output, console)

        try:
            server, resolved_token = create_dashboard_server(
                host=bind_host,
                port=port,
                token=token,
                expose_token_in_config=access_mode == "local",
                allow_network_bind=access_mode in {"lan", "vpn"},
            )
        except ValueError as exc:
            _dashboard_start_error(str(exc), json_output, console, cause=exc)
        actual_port = server.server_address[1]
        local_url = _dashboard_url(f"http://127.0.0.1:{actual_port}/", resolved_token)
        lan_url: str | None = None
        vpn_url: str | None = None
        tunnel_url: str | None = None
        public_url: str | None = None
        if access_mode == "lan":
            lan_host = _best_lan_display_host(bind_host)
            lan_url = _dashboard_url(f"http://{lan_host}:{actual_port}/", resolved_token)
            display_url = lan_url
        elif access_mode == "vpn":
            vpn_url = _dashboard_url(f"http://{bind_host}:{actual_port}/", resolved_token)
            display_url = vpn_url
        elif access_mode == "public":
            try:
                with TunnelManager() as tm:
                    tunnel_url = tm.start(actual_port)
                    public_url = _dashboard_url(tunnel_url, resolved_token)
                    display_url = public_url
            except RuntimeError as exc:
                if json_output:
                    console.print_json(data={"error": str(exc)})
                else:
                    console.print(f"[red]Tunnel error:[/red] {exc}")
                raise typer.Exit(code=1) from exc
        else:
            display_url = local_url
        if json_output:
            console.print_json(
                data={
                    "schema_version": "control_plane.dashboard_start.v1",
                    "host": host,
                    "bind_host": bind_host,
                    "port": actual_port,
                    "access_mode": access_mode,
                    "url": display_url,
                    "local_url": local_url,
                    "lan_url": lan_url,
                    "vpn_url": vpn_url,
                    "tunnel_url": tunnel_url,
                    "public_url": public_url,
                    "token_required": True,
                }
            )
        else:
            if access_mode == "public" and tunnel_url:
                console.print(
                    Panel.fit(
                        f"[bold link={display_url}]Phone URL:[/bold link] "
                        f"[cyan]{display_url}[/cyan]\n\n"
                        f"[dim]Local URL:[/dim] {local_url}\n\n"
                        "[yellow]Keep this URL private; it can control this local dashboard.[/yellow]\n\n"
                        "Press Ctrl-C to stop.",
                        title="Tunnel Active",
                        border_style="green",
                    )
                )
            elif access_mode == "lan":
                console.print(
                    Panel.fit(
                        f"[bold link={display_url}]LAN URL:[/bold link] "
                        f"[cyan]{display_url}[/cyan]\n\n"
                        f"[dim]Local URL:[/dim] {local_url}\n\n"
                        "[yellow]Only use on trusted Wi-Fi. Keep this URL private.[/yellow]\n\n"
                        "Press Ctrl-C to stop.",
                        title="LAN Dashboard",
                        border_style="yellow",
                    )
                )
            elif access_mode == "vpn":
                console.print(
                    Panel.fit(
                        f"[bold link={display_url}]VPN URL:[/bold link] "
                        f"[cyan]{display_url}[/cyan]\n\n"
                        f"[dim]Local URL:[/dim] {local_url}\n\n"
                        "[green]Recommended for remote access; not exposed to the public internet.[/green]\n\n"
                        "Press Ctrl-C to stop.",
                        title="VPN Dashboard",
                        border_style="green",
                    )
                )
            else:
                console.print(f"Control-plane dashboard: [cyan]{escape(display_url)}[/cyan]")
                console.print("Press Ctrl-C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()

    @tasks_app.command("list")
    def control_plane_tasks_list(
        status: str | None = typer.Option(None, "--status", help="Filter by task status"),
        limit: int = typer.Option(20, "--limit", help="Maximum tasks to show; 0 means all"),
        json_output: bool = typer.Option(
            False, "--json", help="Print machine-readable JSON output"
        ),
    ) -> None:
        """List durable local control-plane tasks."""
        from claude_bridge.control_plane import control_plane_dir, list_tasks

        tasks = list_tasks(status=status, limit=limit)
        payload = {
            "schema_version": "control_plane.tasks.v1",
            "state_dir": str(control_plane_dir()),
            "tasks": tasks,
        }
        if json_output:
            console.print_json(data=payload)
            return
        if not tasks:
            console.print("No control-plane tasks found.")
            return
        for task in tasks:
            console.print(
                f"[bold]{escape(task['id'])}[/bold] "
                f"{escape(task.get('status', 'pending'))} {escape(task['title'])}"
            )
            summary = task.get("summary", "")
            if summary:
                console.print(f"  {escape(summary)}")

    @tasks_app.command("show")
    def control_plane_tasks_show(
        task_id: str,
        json_output: bool = typer.Option(
            False, "--json", help="Print machine-readable JSON output"
        ),
    ) -> None:
        """Show one durable local control-plane task."""
        from claude_bridge.control_plane import get_task

        task = get_task(task_id)
        if task is None:
            error_payload = {"error": f"Task '{task_id}' not found"}
            if json_output:
                console.print_json(data=error_payload)
            else:
                console.print(f"[red]{escape(error_payload['error'])}[/red]")
            raise typer.Exit(code=1)
        payload: dict[str, Any] = {"schema_version": "control_plane.task.v1", "task": task}
        if json_output:
            console.print_json(data=payload)
            return
        console.print(Panel.fit(json.dumps(task, indent=2), title=task_id))

    @tasks_app.command("summary")
    def control_plane_tasks_summary(
        json_output: bool = typer.Option(
            False, "--json", help="Print machine-readable JSON output"
        ),
    ) -> None:
        """Summarize durable local control-plane tasks."""
        from claude_bridge.control_plane import control_plane_dir, summarize_tasks

        summary = summarize_tasks()
        payload = {
            "schema_version": "control_plane.task_summary.v1",
            "state_dir": str(control_plane_dir()),
            "summary": summary,
        }
        if json_output:
            console.print_json(data=payload)
            return
        console.print(Panel.fit(f"Tasks: {summary['total']}", title="Control Plane"))
        for status, count in summary["by_status"].items():
            console.print(f"{escape(status)}: {count}")

    @tasks_app.command("cancel")
    def control_plane_tasks_cancel(
        task_id: str,
        reason: str = typer.Option("", "--reason", help="Optional cancellation reason"),
        json_output: bool = typer.Option(
            False, "--json", help="Print machine-readable JSON output"
        ),
    ) -> None:
        """Mark one durable local control-plane task as cancelled."""
        from claude_bridge.control_plane import update_task_status

        task = update_task_status(
            task_id,
            "cancelled",
            summary=reason or None,
            metadata={"cancel_reason": reason} if reason else None,
        )
        if task is None:
            error_payload = {"error": f"Task '{task_id}' not found"}
            if json_output:
                console.print_json(data=error_payload)
            else:
                console.print(f"[red]{escape(error_payload['error'])}[/red]")
            raise typer.Exit(code=1)
        payload: dict[str, Any] = {"schema_version": "control_plane.task.v1", "task": task}
        if json_output:
            console.print_json(data=payload)
            return
        console.print(f"[green]Cancelled[/green] {escape(task['id'])}")

    @approvals_app.command("list")
    def control_plane_approvals_list(
        status: str | None = typer.Option(None, "--status", help="Filter by approval status"),
        limit: int = typer.Option(20, "--limit", help="Maximum approvals to show; 0 means all"),
        json_output: bool = typer.Option(
            False, "--json", help="Print machine-readable JSON output"
        ),
    ) -> None:
        """List durable local control-plane approval requests."""
        from claude_bridge.control_plane import control_plane_dir, list_approvals

        approvals = list_approvals(status=status, limit=limit)
        payload = {
            "schema_version": "control_plane.approvals.v1",
            "state_dir": str(control_plane_dir()),
            "approvals": approvals,
        }
        if json_output:
            console.print_json(data=payload)
            return
        if not approvals:
            console.print("No control-plane approvals found.")
            return
        for approval in approvals:
            console.print(
                f"[bold]{escape(approval['id'])}[/bold] "
                f"{escape(approval.get('status', 'pending'))} {escape(approval['title'])}"
            )
            tool = approval.get("tool", "")
            reason = approval.get("reason", "")
            details = " ".join(part for part in (tool, reason) if part)
            if details:
                console.print(f"  {escape(details)}")

    @approvals_app.command("show")
    def control_plane_approvals_show(
        approval_id: str,
        json_output: bool = typer.Option(
            False, "--json", help="Print machine-readable JSON output"
        ),
    ) -> None:
        """Show one durable local control-plane approval request."""
        from claude_bridge.control_plane import get_approval

        approval = get_approval(approval_id)
        if approval is None:
            error_payload = {"error": f"Approval '{approval_id}' not found"}
            if json_output:
                console.print_json(data=error_payload)
            else:
                console.print(f"[red]{escape(error_payload['error'])}[/red]")
            raise typer.Exit(code=1)
        payload: dict[str, Any] = {
            "schema_version": "control_plane.approval.v1",
            "approval": approval,
        }
        if json_output:
            console.print_json(data=payload)
            return
        console.print(Panel.fit(json.dumps(approval, indent=2), title=approval_id))

    @approvals_app.command("approve")
    def control_plane_approvals_approve(
        approval_id: str,
        reason: str = typer.Option("", "--reason", help="Optional approval reason"),
        json_output: bool = typer.Option(
            False, "--json", help="Print machine-readable JSON output"
        ),
    ) -> None:
        """Mark one durable local control-plane approval request as approved."""
        _resolve_control_plane_approval(approval_id, "approved", reason, json_output, console)

    @approvals_app.command("reject")
    def control_plane_approvals_reject(
        approval_id: str,
        reason: str = typer.Option("", "--reason", help="Optional rejection reason"),
        json_output: bool = typer.Option(
            False, "--json", help="Print machine-readable JSON output"
        ),
    ) -> None:
        """Mark one durable local control-plane approval request as denied."""
        _resolve_control_plane_approval(approval_id, "denied", reason, json_output, console)


def _resolve_control_plane_approval(
    approval_id: str,
    status: str,
    reason: str,
    json_output: bool,
    console: Console,
) -> None:
    from typing import Literal, cast

    from claude_bridge.control_plane import resolve_approval

    approval = resolve_approval(
        approval_id,
        cast(Literal["approved", "denied"], status),
        reason=reason,
        metadata={"decision_reason": reason} if reason else None,
    )
    if approval is None:
        error_payload = {"error": f"Approval '{approval_id}' not found"}
        if json_output:
            console.print_json(data=error_payload)
        else:
            console.print(f"[red]{escape(error_payload['error'])}[/red]")
        raise typer.Exit(code=1)
    payload: dict[str, Any] = {
        "schema_version": "control_plane.approval.v1",
        "approval": approval,
    }
    if json_output:
        console.print_json(data=payload)
        return
    console.print(f"[green]{escape(status)}[/green] {escape(approval['id'])}")


def _dashboard_url(base_url: str, token: str) -> str:
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urlencode({'token': token})}"


def _dashboard_start_error(
    message: str,
    json_output: bool,
    console: Console,
    *,
    cause: Exception | None = None,
) -> None:
    if json_output:
        console.print_json(data={"error": message})
    else:
        console.print(f"[red]{escape(message)}[/red]")
    raise typer.Exit(code=1) from cause


def _best_lan_display_host(bind_host: str) -> str:
    if bind_host not in {"0.0.0.0", "::"}:
        return bind_host
    detected = _detect_lan_ipv4()
    return detected or "localhost"


def _detect_lan_ipv4() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        address = str(sock.getsockname()[0])
    except OSError:
        return None
    finally:
        sock.close()
    if address.startswith("127."):
        return None
    return address


def _tailscale_ipv4() -> str:
    if shutil.which("tailscale") is None:
        raise RuntimeError(
            "Tailscale is not installed. Install it, connect this computer and phone to the "
            "same tailnet, then run 'nulm dashboard --vpn'."
        )
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=3,
            shell=False,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Could not read Tailscale IPv4 address") from exc
    address = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    if result.returncode != 0 or not address:
        raise RuntimeError(
            "Tailscale is not connected. Connect this computer and phone to the same tailnet, "
            "then run 'nulm dashboard --vpn'."
        )
    return address
