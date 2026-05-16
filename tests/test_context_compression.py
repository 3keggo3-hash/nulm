"""Tests for context compression utilities."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


import json
import os
import tempfile
from pathlib import Path

import pytest

from claude_bridge import server as mcp_server
from claude_bridge._audit_core import current_session_id, reset_audit_session
from claude_bridge._context_compression import (
    compress_session,
    get_session_stats,
    summarize_audit_records,
)


@pytest.fixture
def temp_audit_project():
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


class TestCompressSession:
    def test_returns_no_records_for_unknown_session(self):
        result = compress_session("nonexistent-session-123")
        assert "no records found" in result

    def test_includes_session_id_in_summary(self, temp_audit_project):
        session_id = current_session_id()
        result = compress_session(session_id)
        assert session_id in result

    def test_empty_session_returns_no_records(self):
        reset_audit_session()
        session_id = current_session_id()
        result = compress_session(session_id)
        assert "no records found" in result


class TestSummarizeAuditRecords:
    def test_empty_records_returns_no_records(self):
        result = summarize_audit_records([])
        assert "No records" in result

    def test_single_tool_call_summarized(self):
        records = [
            {
                "tool_name": "read_file",
                "params": {"path": "test.py"},
                "result": {"ok": True},
                "telemetry": {
                    "input_chars": 100,
                    "output_chars": 500,
                    "estimated_total_tokens": 50,
                },
            }
        ]
        result = summarize_audit_records(records)
        assert "Records: 1" in result
        assert "Failures: 0" in result
        assert "read_file" in result

    def test_failure_counted(self):
        records = [
            {
                "tool_name": "read_file",
                "params": {},
                "result": {"ok": False, "message": "not found"},
                "telemetry": {},
            }
        ]
        result = summarize_audit_records(records)
        assert "Failures: 1" in result

    def test_paths_extracted(self):
        records = [
            {
                "tool_name": "read_file",
                "params": {"path": "src/main.py"},
                "result": {"ok": True},
                "telemetry": {},
            }
        ]
        result = summarize_audit_records(records)
        assert "src/main.py" in result

    def test_commands_extracted(self):
        records = [
            {
                "tool_name": "run_shell",
                "params": {"command": "pytest tests/"},
                "result": {"ok": True},
                "telemetry": {},
            }
        ]
        result = summarize_audit_records(records)
        assert "pytest tests/" in result

    def test_token_totals_included(self):
        records = [
            {
                "tool_name": "read_file",
                "params": {},
                "result": {"ok": True},
                "telemetry": {
                    "input_chars": 100,
                    "output_chars": 200,
                    "estimated_total_tokens": 30,
                },
            }
        ]
        result = summarize_audit_records(records)
        assert "100" in result
        assert "200" in result
        assert "30" in result


class TestGetSessionStats:
    def test_unknown_session_returns_empty_stats(self):
        stats = get_session_stats("nonexistent-session-456")
        assert stats["session_id"] == "nonexistent-session-456"
        assert stats["total_records"] == 0
        assert stats["tool_counts"] == {}

    def test_stats_structure(self, temp_audit_project):
        session_id = current_session_id()
        stats = get_session_stats(session_id)
        assert "session_id" in stats
        assert "total_records" in stats
        assert "tool_counts" in stats
        assert "failures" in stats
        assert "truncated_results" in stats
        assert "duration_ms" in stats
        assert "telemetry" in stats
        assert "anomaly_counts" in stats

    def test_telemetry_substructure(self):
        stats = get_session_stats("")
        telemetry = stats["telemetry"]
        assert "total_input_chars" in telemetry
        assert "total_output_chars" in telemetry
        assert "total_estimated_tokens" in telemetry
        assert "avg_tokens_per_record" in telemetry
        assert "tool_estimated_tokens" in telemetry
        assert "tool_input_chars" in telemetry
        assert "tool_output_chars" in telemetry


class TestCompressContextTool:
    async def test_compress_context_returns_summary(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)

        session_id = current_session_id()
        result = await mcp_server.compress_context(session_id=session_id)
        payload = json.loads(result)
        assert payload["ok"] is True
        assert "compact_summary" in payload["details"]
        assert "session_stats" in payload["details"]
        stats = payload["details"]["session_stats"]
        assert stats["session_id"] == session_id

    async def test_compress_context_empty_session(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)

        session_id = current_session_id()
        result = await mcp_server.compress_context(session_id=session_id)
        payload = json.loads(result)
        assert payload["ok"] is True
        summary = payload["details"]["compact_summary"]
        assert "no records found" in summary


class TestEdgeCases:
    """Edge case tests for context compression."""

    def test_compress_empty_session_no_crash(self):
        """Empty session should not crash compress_session."""
        reset_audit_session()
        session_id = current_session_id()
        result = compress_session(session_id)
        assert "no records found" in result

    def test_summarize_audit_records_large_session(self):
        """Handles sessions with >10000 records without crashing."""
        large_records = []
        for i in range(10500):
            large_records.append({
                "tool_name": "read_file",
                "params": {"path": f"src/file_{i % 100}.py"},
                "result": {"ok": True},
                "telemetry": {
                    "input_chars": 100,
                    "output_chars": 500,
                    "estimated_total_tokens": 50,
                },
            })
        result = summarize_audit_records(large_records)
        assert "Records: 10500" in result
        assert "Failures: 0" in result

    def test_summarize_audit_records_malformed_records(self):
        """Gracefully handles malformed/missing fields in records."""
        malformed_records = [
            {},  # empty record
            {"tool_name": "test"},  # missing params/result/telemetry
            {"params": {}, "result": {"ok": True}},  # missing tool_name
            {"tool_name": 123, "params": "bad"},  # wrong types
            {"tool_name": "run_shell", "params": {}, "result": {}, "telemetry": None},
        ]
        # Should not crash, should process valid fields
        result = summarize_audit_records(malformed_records)
        assert "Records:" in result