"""Tests for appeal data models and audit logging."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


import json
import os
import tempfile
from pathlib import Path

import pytest

from claude_bridge import server as mcp_server
from claude_bridge.audit import (
    AppealRequest,
    AppealResult,
    get_appeal_history,
    log_appeal_event,
    log_tool_call,
    process_appeal,
    reset_audit_session,
    validate_appeal_justification,
)


class TestAppealRequest:
    """Unit tests for AppealRequest dataclass."""

    def test_create_appeal_request_with_valid_justification(self):
        request = AppealRequest.create(
            original_record_id="record-123",
            justification="This decision was incorrect because the file is not sensitive.",
        )
        assert request.appeal_id
        assert request.original_record_id == "record-123"
        assert (
            request.justification
            == "This decision was incorrect because the file is not sensitive."
        )
        assert request.metadata == {}

    def test_create_appeal_request_with_metadata(self):
        metadata = {"tool_name": "read_file", "path": ".env"}
        request = AppealRequest.create(
            original_record_id="record-456",
            justification="Need access for debugging",
            metadata=metadata,
        )
        assert request.metadata == metadata

    def test_create_appeal_request_strips_whitespace(self):
        request = AppealRequest.create(
            original_record_id="record-789",
            justification="  Valid justification with spaces  ",
        )
        assert request.justification == "Valid justification with spaces"

    def test_create_appeal_request_rejects_empty_justification(self):
        with pytest.raises(ValueError, match="justification cannot be empty"):
            AppealRequest.create(
                original_record_id="record-000",
                justification="",
            )

    def test_create_appeal_request_rejects_whitespace_only_justification(self):
        with pytest.raises(ValueError, match="justification cannot be empty"):
            AppealRequest.create(
                original_record_id="record-001",
                justification="   ",
            )

    def test_to_dict_serialization(self):
        request = AppealRequest.create(
            original_record_id="record-abc",
            justification="Test reason",
            metadata={"key": "value"},
        )
        data = request.to_dict()
        assert data["appeal_id"] == request.appeal_id
        assert data["original_record_id"] == "record-abc"
        assert data["justification"] == "Test reason"
        assert data["metadata"] == {"key": "value"}

    def test_appeal_id_is_unique(self):
        request1 = AppealRequest.create(original_record_id="rec-1", justification="reason 1")
        request2 = AppealRequest.create(original_record_id="rec-2", justification="reason 2")
        assert request1.appeal_id != request2.appeal_id


class TestAppealResult:
    """Unit tests for AppealResult dataclass."""

    def test_create_appeal_result(self):
        result = AppealResult(
            appeal_id="appeal-123",
            status="approved",
            reviewed_by="admin",
            decision_reason="Justification was valid",
        )
        assert result.appeal_id == "appeal-123"
        assert result.status == "approved"
        assert result.reviewed_by == "admin"
        assert result.decision_reason == "Justification was valid"
        assert result.metadata == {}
        assert result.timestamp

    def test_create_appeal_result_with_metadata(self):
        metadata = {"escalation_level": 2, "reviewer_notes": "Checked with team"}
        result = AppealResult(
            appeal_id="appeal-456",
            status="rejected",
            reviewed_by="senior_admin",
            decision_reason="Policy violation confirmed",
            metadata=metadata,
        )
        assert result.metadata == metadata

    def test_to_dict_serialization(self):
        result = AppealResult(
            appeal_id="appeal-789",
            status="pending",
            reviewed_by="ai",
            decision_reason="Awaiting human review",
            metadata={"auto_flagged": True},
            timestamp="2025-01-15T10:30:00Z",
        )
        data = result.to_dict()
        assert data["appeal_id"] == "appeal-789"
        assert data["status"] == "pending"
        assert data["reviewed_by"] == "ai"
        assert data["decision_reason"] == "Awaiting human review"
        assert data["metadata"] == {"auto_flagged": True}
        assert data["timestamp"] == "2025-01-15T10:30:00Z"

    def test_from_dict_deserialization(self):
        data = {
            "appeal_id": "appeal-xyz",
            "status": "approved",
            "reviewed_by": "user123",
            "decision_reason": "Approved after review",
            "metadata": {"priority": "high"},
            "timestamp": "2025-01-16T08:00:00Z",
        }
        result = AppealResult.from_dict(data)
        assert result.appeal_id == "appeal-xyz"
        assert result.status == "approved"
        assert result.reviewed_by == "user123"
        assert result.decision_reason == "Approved after review"
        assert result.metadata == {"priority": "high"}
        assert result.timestamp == "2025-01-16T08:00:00Z"

    def test_from_dict_handles_missing_fields(self):
        data = {"appeal_id": "appeal-minimal"}
        result = AppealResult.from_dict(data)
        assert result.appeal_id == "appeal-minimal"
        assert result.status == "pending"
        assert result.reviewed_by == "unknown"
        assert result.decision_reason == ""
        assert result.metadata == {}


class TestValidateAppealJustification:
    """Unit tests for validate_appeal_justification helper."""

    def test_valid_justification(self):
        is_valid, error = validate_appeal_justification("This is a valid reason")
        assert is_valid is True
        assert error is None

    def test_empty_string_rejected(self):
        is_valid, error = validate_appeal_justification("")
        assert is_valid is False
        assert error == "justification cannot be empty"

    def test_whitespace_only_rejected(self):
        is_valid, error = validate_appeal_justification("   ")
        assert is_valid is False
        assert error == "justification cannot be empty"

    def test_newline_only_rejected(self):
        is_valid, error = validate_appeal_justification("\n\n")
        assert is_valid is False
        assert error == "justification cannot be empty"

    def test_justification_with_leading_trailing_whitespace(self):
        is_valid, error = validate_appeal_justification("  valid reason  ")
        assert is_valid is True
        assert error is None


class TestLogAppealEvent:
    """Integration tests for log_appeal_event function."""

    @pytest.fixture
    def temp_audit_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            audit_dir = project / ".audit"
            os.environ["CLAUDE_BRIDGE_AUDIT_DIR"] = str(audit_dir)
            mcp_server.set_config(project_dir=project, auto_approve=True)
            reset_audit_session()
            yield project, audit_dir
            try:
                del os.environ["CLAUDE_BRIDGE_AUDIT_DIR"]
            except KeyError:
                pass
            reset_audit_session()

    async def test_log_appeal_request_without_result(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))

        request = AppealRequest.create(
            original_record_id="record-test-1",
            justification="Testing appeal logging",
        )
        log_appeal_event(request)

        payload = json.loads(await mcp_server.get_recent_tool_calls(limit=5))
        assert payload["ok"] is True
        records = payload["details"]["records"]
        appeal_record = None
        for record in records:
            if record.get("tool_name") == "appeal_event":
                appeal_record = record
                break
        assert appeal_record is not None
        assert appeal_record.get("appeal_id") == request.appeal_id
        assert appeal_record.get("original_record_id") == "record-test-1"
        assert "appeal_status" not in appeal_record

    async def test_log_appeal_with_result(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))

        request = AppealRequest.create(
            original_record_id="record-test-2",
            justification="Need access for production debugging",
        )
        result = AppealResult(
            appeal_id=request.appeal_id,
            status="approved",
            reviewed_by="admin",
            decision_reason="Verified user has proper clearance",
        )
        log_appeal_event(request, result)

        payload = json.loads(await mcp_server.get_recent_tool_calls(limit=5))
        records = payload["details"]["records"]
        appeal_record = None
        for record in records:
            if record.get("tool_name") == "appeal_event":
                appeal_record = record
                break
        assert appeal_record is not None
        assert appeal_record.get("appeal_status") == "approved"
        assert appeal_record.get("appeal_reviewed_by") == "admin"

    async def test_appeal_event_has_standard_audit_fields(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))

        request = AppealRequest.create(
            original_record_id="record-test-3",
            justification="Test justification",
        )
        log_appeal_event(request)

        payload = json.loads(await mcp_server.get_recent_tool_calls(limit=5))
        records = payload["details"]["records"]
        appeal_record = None
        for record in records:
            if record.get("tool_name") == "appeal_event":
                appeal_record = record
                break
        assert appeal_record is not None
        assert "timestamp" in appeal_record
        assert "session_id" in appeal_record
        assert "params" in appeal_record
        assert "result" in appeal_record
        assert "telemetry" in appeal_record
        assert "record_id" in appeal_record


class TestGetAppealHistory:
    """Tests for get_appeal_history function."""

    @pytest.fixture
    def temp_audit_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            audit_dir = project / ".audit"
            os.environ["CLAUDE_BRIDGE_AUDIT_DIR"] = str(audit_dir)
            mcp_server.set_config(project_dir=project, auto_approve=True)
            reset_audit_session()
            yield project, audit_dir
            try:
                del os.environ["CLAUDE_BRIDGE_AUDIT_DIR"]
            except KeyError:
                pass
            reset_audit_session()

    def test_get_appeal_history_empty(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))

        history = get_appeal_history("nonexistent-record-id")
        assert history == []

    def test_get_appeal_history_returns_appeals_for_record(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))

        record_id = "test-record-123"
        request1 = AppealRequest.create(
            original_record_id=record_id,
            justification="First appeal",
        )
        request2 = AppealRequest.create(
            original_record_id=record_id,
            justification="Second appeal",
        )
        log_appeal_event(request1)
        log_appeal_event(request2)

        history = get_appeal_history(record_id)
        assert len(history) == 2
        assert all(a.get("original_record_id") == record_id for a in history)
        assert all(a.get("tool_name") == "appeal_event" for a in history)

    def test_get_appeal_history_filters_by_record_id(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))

        request_a = AppealRequest.create(
            original_record_id="record-A",
            justification="Appeal for A",
        )
        request_b = AppealRequest.create(
            original_record_id="record-B",
            justification="Appeal for B",
        )
        log_appeal_event(request_a)
        log_appeal_event(request_b)

        history_a = get_appeal_history("record-A")
        history_b = get_appeal_history("record-B")
        assert len(history_a) == 1
        assert len(history_b) == 1
        assert history_a[0]["appeal_id"] == request_a.appeal_id
        assert history_b[0]["appeal_id"] == request_b.appeal_id


class TestProcessAppeal:
    """Tests for process_appeal function."""

    @pytest.fixture
    def temp_audit_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            audit_dir = project / ".audit"
            os.environ["CLAUDE_BRIDGE_AUDIT_DIR"] = str(audit_dir)
            mcp_server.set_config(project_dir=project, auto_approve=True)
            reset_audit_session()
            yield project, audit_dir
            try:
                del os.environ["CLAUDE_BRIDGE_AUDIT_DIR"]
            except KeyError:
                pass
            reset_audit_session()

    def test_process_appeal_rejects_empty_justification(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))

        with pytest.raises(ValueError, match="justification cannot be empty"):
            process_appeal("some-record-id", "")

    def test_process_appeal_rejects_missing_record(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))

        with pytest.raises(ValueError, match="original record not found"):
            process_appeal("nonexistent-record-id", "Valid justification")

    async def test_process_appeal_succeeds_with_valid_record(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))

        log_tool_call(
            tool_name="run_shell",
            params={"command": "echo hello"},
            result=json.dumps(
                {
                    "ok": True,
                    "message": "done",
                    "details": {},
                }
            ),
            duration_ms=5.0,
        )

        payload = json.loads(await mcp_server.get_recent_tool_calls(limit=5))
        records = payload["details"]["records"]
        assert len(records) >= 1
        record_id = records[0]["record_id"]

        result = process_appeal(record_id, "This should be allowed")

        assert "appeal_request" in result
        assert "appeal_result" in result
        assert "original_record" in result
        assert "replay_result" in result
        assert "appeal_history_count" in result
        assert result["appeal_history_count"] >= 1
        assert result["original_record"]["record_id"] == record_id

    async def test_process_appeal_chained_to_audit_log(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))

        log_tool_call(
            tool_name="read_file",
            params={"path": "test.txt"},
            result=json.dumps(
                {
                    "ok": True,
                    "message": "read ok",
                    "details": {},
                }
            ),
            duration_ms=3.0,
        )

        payload = json.loads(await mcp_server.get_recent_tool_calls(limit=5))
        record_id = payload["details"]["records"][0]["record_id"]

        process_appeal(record_id, "Need access for debugging")

        history = get_appeal_history(record_id)
        assert len(history) >= 1

        appeal_record = history[0]
        assert appeal_record["tool_name"] == "appeal_event"
        assert appeal_record["original_record_id"] == record_id
        assert appeal_record.get("appeal_status") in ("allow", "deny", "ask")
        assert appeal_record.get("appeal_reviewed_by") == "user"

    async def test_process_appeal_multiple_appeals_accumulate(
        self, temp_audit_project, monkeypatch
    ):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))

        log_tool_call(
            tool_name="write_file",
            params={"path": "config.json", "content": "{}"},
            result=json.dumps(
                {
                    "ok": True,
                    "message": "written",
                    "details": {},
                }
            ),
            duration_ms=10.0,
        )

        payload = json.loads(await mcp_server.get_recent_tool_calls(limit=5))
        record_id = payload["details"]["records"][0]["record_id"]

        process_appeal(record_id, "First justification")
        process_appeal(record_id, "Second justification")

        history = get_appeal_history(record_id)
        assert len(history) >= 2

        result = process_appeal(record_id, "Third justification")
        assert result["appeal_history_count"] >= 3

    async def test_process_appeal_e2e_deny_to_audit_chain(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))

        # Log a tool call that results in a deny decision
        log_tool_call(
            tool_name="run_shell",
            params={"command": "sudo rm -rf /"},
            result=json.dumps(
                {
                    "ok": False,
                    "message": "Command blocked for safety",
                    "code": "blocked_command",
                    "details": {
                        "decision": {
                            "action": "deny",
                            "source": "builtin_guard",
                            "risk_level": "critical",
                            "reason": "Blocked dangerous command",
                        }
                    },
                }
            ),
            duration_ms=2.0,
        )

        # Get the record id
        payload = json.loads(await mcp_server.get_recent_tool_calls(limit=1))
        record_id = payload["details"]["records"][0]["record_id"]

        # Appeal the decision
        result = process_appeal(record_id, "I need this for a specific recovery task")

        # Verify appeal result structure
        assert result["appeal_result"]["status"] in ("allow", "deny", "ask")
        assert result["original_record"]["record_id"] == record_id
        assert result["original_record"]["decision_action"] == "deny"

        # Verify audit event was logged
        history = get_appeal_history(record_id)
        assert len(history) >= 1
        assert history[0]["tool_name"] == "appeal_event"
        assert history[0]["original_record_id"] == record_id
