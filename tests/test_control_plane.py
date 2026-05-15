"""Tests for local control-plane state."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from typer.testing import CliRunner

from claude_bridge import cli
from claude_bridge import control_plane
from claude_bridge import control_plane_dashboard
from claude_bridge import server as mcp_server

runner = CliRunner()


def test_control_plane_create_list_show_and_summary(monkeypatch, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    monkeypatch.setenv(control_plane.CONTROL_PLANE_ENV_VAR, str(state_dir))

    task = control_plane.create_task("Fix flaky test", summary="Investigate timeout")
    approval = control_plane.create_approval(
        "Run command",
        tool="run_shell",
        command="pytest tests/test_control_plane.py",
        reason="Validate control-plane state",
    )

    assert control_plane.control_plane_dir() == state_dir.resolve()
    assert (state_dir / "tasks.jsonl").exists()
    assert (state_dir / "approvals.jsonl").exists()
    assert control_plane.get_task(task["id"]) == task
    assert control_plane.get_approval(approval["id"]) == approval
    assert control_plane.list_tasks(status="pending") == [task]
    assert control_plane.list_approvals(status="pending") == [approval]

    cancelled = control_plane.update_task_status(task["id"], "cancelled")
    approved = control_plane.resolve_approval(approval["id"], "approved")

    assert cancelled is not None
    assert cancelled["status"] == "cancelled"
    assert control_plane.get_task(task["id"]) == cancelled
    assert control_plane.list_tasks(status="pending") == []
    assert control_plane.list_tasks(status="cancelled") == [cancelled]
    assert approved is not None
    assert approved["status"] == "approved"
    assert control_plane.get_approval(approval["id"]) == approved
    assert control_plane.list_approvals(status="pending") == []
    assert control_plane.list_approvals(status="approved") == [approved]

    summary = control_plane.summarize_tasks()
    assert summary["total"] == 1
    assert summary["by_status"]["cancelled"] == 1


def test_control_plane_messages(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(control_plane.CONTROL_PLANE_ENV_VAR, str(tmp_path / "state"))

    message = control_plane.create_message("Please check the dashboard", metadata={"source": "t"})
    acknowledged = control_plane.update_message_status(
        message["id"],
        "acknowledged",
        response="seen",
    )

    assert (tmp_path / "state" / "messages.jsonl").exists()
    assert control_plane.list_messages(status="queued") == []
    assert acknowledged is not None
    assert acknowledged["status"] == "acknowledged"
    assert acknowledged["response"] == "seen"
    assert control_plane.list_messages(status="acknowledged")[0]["id"] == message["id"]


def test_control_plane_cli_lists_tasks_and_approvals(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(control_plane.CONTROL_PLANE_ENV_VAR, str(tmp_path / "state"))
    task = control_plane.create_task("Document state")
    approval = control_plane.create_approval("Approve shell", tool="run_shell")

    task_result = runner.invoke(cli.app, ["control-plane", "tasks", "list", "--json"])
    approval_result = runner.invoke(cli.app, ["control-plane", "approvals", "list", "--json"])
    top_level_task_result = runner.invoke(cli.app, ["tasks", "list", "--json"])
    top_level_approval_result = runner.invoke(cli.app, ["approvals", "list", "--json"])

    assert task_result.exit_code == 0
    task_payload = json.loads(task_result.stdout)
    assert task_payload["schema_version"] == "control_plane.tasks.v1"
    assert task_payload["tasks"][0]["id"] == task["id"]
    assert top_level_task_result.exit_code == 0
    assert json.loads(top_level_task_result.stdout)["tasks"][0]["id"] == task["id"]

    assert approval_result.exit_code == 0
    approval_payload = json.loads(approval_result.stdout)
    assert approval_payload["schema_version"] == "control_plane.approvals.v1"
    assert approval_payload["approvals"][0]["id"] == approval["id"]
    assert top_level_approval_result.exit_code == 0
    assert json.loads(top_level_approval_result.stdout)["approvals"][0]["id"] == approval["id"]


def test_control_plane_cli_cancels_tasks_and_resolves_approvals(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(control_plane.CONTROL_PLANE_ENV_VAR, str(tmp_path / "state"))
    task = control_plane.create_task("Run release gate")
    approval = control_plane.create_approval("Approve shell", tool="run_shell")

    cancel_result = runner.invoke(cli.app, ["tasks", "cancel", task["id"], "--json"])
    approve_result = runner.invoke(cli.app, ["approvals", "approve", approval["id"], "--json"])

    assert cancel_result.exit_code == 0
    assert json.loads(cancel_result.stdout)["task"]["status"] == "cancelled"
    assert approve_result.exit_code == 0
    assert json.loads(approve_result.stdout)["approval"]["status"] == "approved"


def test_control_plane_cli_show_reports_missing_record(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(control_plane.CONTROL_PLANE_ENV_VAR, str(tmp_path / "state"))

    result = runner.invoke(
        cli.app,
        ["control-plane", "tasks", "show", "task_missing", "--json"],
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"] == "Task 'task_missing' not found"


async def test_control_plane_mcp_tools_list_tasks_and_approvals(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(control_plane.CONTROL_PLANE_ENV_VAR, str(tmp_path / "state"))
    task = control_plane.create_task("Watch release")
    approval = control_plane.create_approval("Approve validation", tool="run_shell")

    tasks_payload = json.loads(await mcp_server.list_tasks())
    task_payload = json.loads(await mcp_server.task_status(task["id"]))
    approvals_payload = json.loads(await mcp_server.list_pending_approvals())
    approved_payload = json.loads(await mcp_server.approve_pending_action(approval["id"]))

    assert tasks_payload["ok"] is True
    assert tasks_payload["details"]["tasks"][0]["id"] == task["id"]
    assert task_payload["details"]["task"]["id"] == task["id"]
    assert approvals_payload["details"]["approvals"][0]["id"] == approval["id"]
    assert approved_payload["details"]["approval"]["status"] == "approved"


async def test_control_plane_mcp_tools_messages(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(control_plane.CONTROL_PLANE_ENV_VAR, str(tmp_path / "state"))
    message = control_plane.create_message("Run validation when free")

    messages_payload = json.loads(await mcp_server.list_user_messages())
    ack_payload = json.loads(await mcp_server.ack_user_message(message["id"], "working"))
    complete_payload = json.loads(await mcp_server.complete_user_message(message["id"], "done"))

    assert messages_payload["ok"] is True
    assert messages_payload["details"]["messages"][0]["id"] == message["id"]
    assert ack_payload["details"]["message"]["status"] == "acknowledged"
    assert complete_payload["details"]["message"]["status"] == "completed"


def test_control_plane_dashboard_payload_and_actions(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(control_plane.CONTROL_PLANE_ENV_VAR, str(tmp_path / "state"))
    task = control_plane.create_task("Watch background job")
    approval = control_plane.create_approval("Approve release gate")

    payload = control_plane_dashboard.build_dashboard_payload()
    json.dumps(payload)
    assert payload["schema_version"] == "control_plane.dashboard.v1"
    assert payload["tasks"][0]["id"] == task["id"]
    assert payload["approvals"][0]["id"] == approval["id"]
    assert payload["messages"] == []

    cancelled = control_plane_dashboard.apply_dashboard_action(
        "cancel-task",
        task["id"],
        reason="done from dashboard",
    )
    approved = control_plane_dashboard.apply_dashboard_action("approve", approval["id"])

    assert cancelled["status"] == "cancelled"
    assert approved["status"] == "approved"


def test_control_plane_dashboard_http_requires_token(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(control_plane.CONTROL_PLANE_ENV_VAR, str(tmp_path / "state"))
    control_plane.create_task("Watch dashboard")
    try:
        server, token = control_plane_dashboard.create_dashboard_server(port=0)
    except PermissionError as exc:
        pytest.skip(f"local socket unavailable in this sandbox: {exc}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(f"{base_url}/api/status?token={token}", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["tasks"][0]["title"] == "Watch dashboard"
        assert "messages" in payload

        message_request = Request(
            f"{base_url}/api/messages?token={token}",
            data=json.dumps({"message": "dashboard validation"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(message_request, timeout=2) as response:
            message_payload = json.loads(response.read().decode("utf-8"))
        assert message_payload["ok"] is True
        assert message_payload["record"]["status"] == "queued"
        assert message_payload["record"]["message"] == "dashboard validation"

        with urlopen(f"{base_url}/api/messages?token={token}", timeout=2) as response:
            messages_payload = json.loads(response.read().decode("utf-8"))
        assert messages_payload["messages"][0]["message"] == "dashboard validation"

        request = Request(f"{base_url}/api/status", method="GET")
        try:
            urlopen(request, timeout=2)
        except HTTPError as exc:
            assert exc.code == 401
        else:  # pragma: no cover - defensive assertion branch
            raise AssertionError("Dashboard API accepted a missing token")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_control_plane_dashboard_rejects_network_bind() -> None:
    try:
        control_plane_dashboard.create_dashboard_server(host="0.0.0.0", port=0)
    except ValueError as exc:
        assert "loopback" in str(exc)
    else:  # pragma: no cover - defensive assertion branch
        raise AssertionError("Dashboard accepted a non-loopback bind")


def test_approval_has_expires_at_field(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(control_plane.CONTROL_PLANE_ENV_VAR, str(tmp_path / "state"))
    approval = control_plane.create_approval("Test approval", tool="run_shell", command="ls")
    assert "expires_at" in approval
    expected_expiry = datetime.now(timezone.utc) + timedelta(minutes=30)
    actual_expiry = datetime.strptime(approval["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    delta = abs((actual_expiry - expected_expiry).total_seconds())
    assert delta < 5


def test_approval_custom_expiry(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(control_plane.CONTROL_PLANE_ENV_VAR, str(tmp_path / "state"))
    custom_expiry = "2025-01-01T00:00:00Z"
    approval = control_plane.create_approval(
        "Test approval", tool="run_shell", command="ls", expires_at=custom_expiry
    )
    assert approval["expires_at"] == custom_expiry


def test_resolve_approval_rejects_expired(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(control_plane.CONTROL_PLANE_ENV_VAR, str(tmp_path / "state"))
    past_expiry = "2020-01-01T00:00:00Z"
    approval = control_plane.create_approval(
        "Expired approval", tool="run_shell", command="ls", expires_at=past_expiry
    )
    result = control_plane.resolve_approval(approval["id"], "approved")
    assert result is None


def test_resolve_approval_accepts_valid(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(control_plane.CONTROL_PLANE_ENV_VAR, str(tmp_path / "state"))
    future_expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    approval = control_plane.create_approval(
        "Valid approval", tool="run_shell", command="ls", expires_at=future_expiry
    )
    result = control_plane.resolve_approval(approval["id"], "approved")
    assert result is not None
    assert result["status"] == "approved"


def test_check_approval_expiry(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(control_plane.CONTROL_PLANE_ENV_VAR, str(tmp_path / "state"))
    past_expiry = "2020-01-01T00:00:00Z"
    approval = control_plane.create_approval(
        "Expiring approval", tool="run_shell", command="ls", expires_at=past_expiry
    )
    assert control_plane.check_approval_expiry(approval["id"]) is True
    updated = control_plane.get_approval(approval["id"])
    assert updated is not None
    assert updated["status"] == "expired"


def test_check_approval_expiry_not_expired(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(control_plane.CONTROL_PLANE_ENV_VAR, str(tmp_path / "state"))
    future_expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    approval = control_plane.create_approval(
        "Not expired approval", tool="run_shell", command="ls", expires_at=future_expiry
    )
    assert control_plane.check_approval_expiry(approval["id"]) is False
    updated = control_plane.get_approval(approval["id"])
    assert updated is not None
    assert updated["status"] == "pending"
