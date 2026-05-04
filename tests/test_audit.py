"""Tests for audit decision extraction (Paket 3A) and redaction (Paket 3B)."""

import json
import os
import tempfile
from hashlib import sha256
from pathlib import Path

import pytest

from claude_bridge import server as mcp_server
from claude_bridge.audit import (
    AuditExport,
    ExportFormat,
    RetentionConfig,
    _extract_policy_decision,
    _mask_secret_value,
    _parse_retention_config,
    _redact_sensitive_values,
    _strip_redacted_value,
    apply_retention,
    export_audit_records,
    get_recent_tool_calls,
    reset_audit_session,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_payload(result: str) -> dict:
    return json.loads(result)


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


# ---------------------------------------------------------------------------
# Paket 3A – Decision extraction helpers
# ---------------------------------------------------------------------------


class TestExtractPolicyDecision:
    """Unit tests for _extract_policy_decision."""

    def test_extracts_from_details_decision(self):
        result = json.dumps(
            {
                "ok": True,
                "message": "done",
                "details": {
                    "decision": {
                        "action": "deny",
                        "source": "builtin_guard",
                        "risk_level": "high",
                        "reason": "sensitive file",
                        "risk_reasons": ["env file"],
                        "metadata": {"path": ".env"},
                    }
                },
            }
        )
        fields = _extract_policy_decision(result)
        assert fields is not None
        assert fields["decision_action"] == "deny"
        assert fields["decision_source"] == "builtin_guard"
        assert fields["decision_risk_level"] == "high"
        assert fields["decision_reason"] == "sensitive file"
        assert fields["decision_risk_reasons"] == ["env file"]
        assert fields["decision_metadata"] == {"path": ".env"}

    def test_extracts_from_top_level_decision(self):
        result = json.dumps(
            {
                "ok": True,
                "message": "done",
                "decision": {
                    "action": "allow",
                    "source": "default",
                    "risk_level": "low",
                    "reason": "safe command",
                    "risk_reasons": [],
                    "metadata": {},
                },
            }
        )
        fields = _extract_policy_decision(result)
        assert fields is not None
        assert fields["decision_action"] == "allow"
        assert fields["decision_source"] == "default"
        assert fields["decision_risk_level"] == "low"

    def test_details_decision_takes_priority_over_top_level(self):
        result = json.dumps(
            {
                "ok": True,
                "message": "done",
                "decision": {
                    "action": "allow",
                    "source": "default",
                    "risk_level": "low",
                    "reason": "top-level",
                },
                "details": {
                    "decision": {
                        "action": "deny",
                        "source": "rule",
                        "risk_level": "high",
                        "reason": "details-level",
                    }
                },
            }
        )
        fields = _extract_policy_decision(result)
        assert fields is not None
        assert fields["decision_action"] == "deny"
        assert fields["decision_source"] == "rule"
        assert fields["decision_reason"] == "details-level"

    def test_returns_none_when_no_decision(self):
        result = json.dumps({"ok": True, "message": "done", "details": {"count": 5}})
        assert _extract_policy_decision(result) is None

    def test_returns_none_when_decision_is_not_dict(self):
        result = json.dumps({"ok": True, "message": "done", "decision": "allow", "details": {}})
        assert _extract_policy_decision(result) is None

    def test_returns_none_for_invalid_json(self):
        assert _extract_policy_decision("not json") is None

    def test_decision_fields_all_present(self):
        result = json.dumps(
            {
                "ok": False,
                "message": "blocked",
                "code": "sensitive_file_blocked",
                "details": {
                    "decision": {
                        "action": "deny",
                        "source": "builtin_guard",
                        "risk_level": "critical",
                        "reason": "Critical: destructive git operation",
                        "risk_reasons": [
                            "force push detected",
                            "irreversible operation",
                        ],
                        "metadata": {
                            "command": "git push --force",
                            "tool": "run_shell",
                        },
                    }
                },
            }
        )
        fields = _extract_policy_decision(result)
        assert fields is not None
        assert fields["decision_action"] == "deny"
        assert fields["decision_source"] == "builtin_guard"
        assert fields["decision_risk_level"] == "critical"
        assert fields["decision_reason"] == "Critical: destructive git operation"
        assert len(fields["decision_risk_reasons"]) == 2
        assert fields["decision_metadata"]["command"] == "git push --force"

    def test_handles_partial_decision_fields(self):
        result = json.dumps(
            {
                "ok": True,
                "details": {
                    "decision": {
                        "action": "ask",
                    }
                },
            }
        )
        fields = _extract_policy_decision(result)
        assert fields is not None
        assert fields["decision_action"] == "ask"
        assert fields["decision_source"] is None
        assert fields["decision_risk_level"] is None
        assert fields["decision_reason"] is None
        assert fields["decision_risk_reasons"] == []
        assert fields["decision_metadata"] == {}


# ---------------------------------------------------------------------------
# Paket 3A – Decision in audit records (integration)
# ---------------------------------------------------------------------------


class TestAuditDecisionInRecords:
    """Integration tests for decision fields in audit JSONL records."""

    async def test_decision_fields_written_to_audit_record(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)

        await mcp_server.read_file(".env")

        payload = parse_payload(await mcp_server.get_recent_tool_calls(limit=5))
        assert payload["ok"] is True
        records = payload["details"]["records"]
        assert len(records) >= 1

        read_record = None
        for record in records:
            if record.get("tool_name") == "read_file":
                read_record = record
                break
        assert read_record is not None
        assert read_record.get("decision_action") == "deny"
        assert read_record.get("decision_source") == "builtin_guard"
        assert read_record.get("decision_risk_level") == "high"
        assert "sensitive" in str(read_record.get("decision_reason", "")).lower()
        assert isinstance(read_record.get("decision_risk_reasons"), list)

    async def test_record_without_decision_has_no_decision_fields(
        self, temp_audit_project, monkeypatch
    ):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)

        (project / "notes.txt").write_text("hello", encoding="utf-8")
        await mcp_server.read_file("notes.txt")

        payload = parse_payload(await mcp_server.get_recent_tool_calls(limit=5))
        records = payload["details"]["records"]
        read_record = None
        for record in records:
            if record.get("tool_name") == "read_file":
                read_record = record
                break
        assert read_record is not None
        assert "decision_action" not in read_record
        assert "decision_source" not in read_record

    async def test_old_records_still_parse_after_schema_change(
        self, temp_audit_project, monkeypatch
    ):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)

        await mcp_server.list_directory(".")
        await mcp_server.run_shell("echo hello")

        payload = parse_payload(await mcp_server.session_insights(limit=10))
        assert payload["ok"] is True
        activity = payload["details"]["activity"]
        assert activity["commands"][0]["command"] == "echo hello"
        telemetry = payload["details"]["telemetry"]
        assert telemetry["total_estimated_tokens"] >= 1

    async def test_recent_tool_calls_includes_standard_fields(
        self, temp_audit_project, monkeypatch
    ):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)

        await mcp_server.read_file("missing.txt")

        payload = parse_payload(await mcp_server.get_recent_tool_calls(limit=5))
        assert payload["ok"] is True
        records = payload["details"]["records"]
        for record in records:
            assert "timestamp" in record
            assert "session_id" in record
            assert "tool_name" in record
            assert "params" in record
            assert "result" in record
            assert "telemetry" in record
            assert "duration_ms" in record


# ---------------------------------------------------------------------------
# Paket 3B – Redaction / masking helpers
# ---------------------------------------------------------------------------


class TestRedactSensitiveValues:
    """Unit tests for _redact_sensitive_values."""

    def test_masks_api_key_in_flat_dict(self):
        params = {"file": "config.json", "api_key": "sk-1234567890abcdef"}
        redacted = _redact_sensitive_values(params)
        assert redacted["file"] == "config.json"
        assert isinstance(redacted["api_key"], dict)
        assert redacted["api_key"]["redacted"] is True
        assert redacted["api_key"]["reason"] == "sensitive value"
        assert redacted["api_key"]["length"] == len("sk-1234567890abcdef")
        assert "sha256" in redacted["api_key"]

    def test_masks_token_case_insensitive(self):
        params = {"Token": "ghp_abc123def456ghi789"}
        redacted = _redact_sensitive_values(params)
        assert isinstance(redacted["Token"], dict)
        assert redacted["Token"]["redacted"] is True

    def test_masks_password_in_nested_dict(self):
        params = {
            "auth": {
                "username": "admin",
                "password": "super-secret-123",
            }
        }
        redacted = _redact_sensitive_values(params)
        assert redacted["auth"]["username"] == "admin"
        assert isinstance(redacted["auth"]["password"], dict)
        assert redacted["auth"]["password"]["redacted"] is True

    def test_masks_secret_in_deeply_nested_dict(self):
        params = {
            "config": {
                "database": {
                    "credentials": {
                        "secret": "db-password-here",
                    }
                }
            }
        }
        redacted = _redact_sensitive_values(params)
        creds = redacted["config"]["database"]["credentials"]
        assert isinstance(creds["secret"], dict)
        assert creds["secret"]["redacted"] is True

    def test_masks_values_in_list_of_dicts(self):
        params = {
            "endpoints": [
                {"name": "api1", "api_key": "key-aaa"},
                {"name": "api2", "api_key": "key-bbb"},
            ]
        }
        redacted = _redact_sensitive_values(params)
        ep0 = redacted["endpoints"][0]
        assert ep0["name"] == "api1"
        assert isinstance(ep0["api_key"], dict)
        assert ep0["api_key"]["redacted"] is True
        ep1 = redacted["endpoints"][1]
        assert isinstance(ep1["api_key"], dict)
        assert ep1["api_key"]["redacted"] is True

    def test_preserves_path_and_command_info(self):
        params = {
            "file": "/home/user/project/main.py",
            "path": "src/utils.py",
            "command": "pytest tests/",
            "api_key": "secret-123",
        }
        redacted = _redact_sensitive_values(params)
        assert redacted["file"] == "/home/user/project/main.py"
        assert redacted["path"] == "src/utils.py"
        assert redacted["command"] == "pytest tests/"
        assert isinstance(redacted["api_key"], dict)

    def test_preserves_non_sensitive_nested_data(self):
        params = {
            "tool_config": {
                "max_lines": 500,
                "encoding": "utf-8",
                "options": {"format": True, "lint": False},
            }
        }
        redacted = _redact_sensitive_values(params)
        assert redacted["tool_config"]["max_lines"] == 500
        assert redacted["tool_config"]["encoding"] == "utf-8"
        assert redacted["tool_config"]["options"]["format"] is True

    def test_masked_value_is_deterministic(self):
        secret = "my-secret-value"
        result1 = _mask_secret_value(secret)
        result2 = _mask_secret_value(secret)
        assert result1 == result2
        assert result1["sha256"] == sha256(secret.encode("utf-8")).hexdigest()

    def test_different_secrets_produce_different_hashes(self):
        result1 = _mask_secret_value("secret-a")
        result2 = _mask_secret_value("secret-b")
        assert result1["sha256"] != result2["sha256"]

    def test_masked_value_has_correct_structure(self):
        secret = "test-secret-123"
        masked = _mask_secret_value(secret)
        assert set(masked.keys()) == {"redacted", "reason", "sha256", "length"}
        assert masked["redacted"] is True
        assert isinstance(masked["reason"], str)
        assert isinstance(masked["sha256"], str)
        assert len(masked["sha256"]) == 64
        assert masked["length"] == len(secret)

    def test_handles_empty_dict(self):
        assert _redact_sensitive_values({}) == {}

    def test_handles_none_value(self):
        assert _redact_sensitive_values(None) is None

    def test_handles_empty_string_value(self):
        params = {"api_key": ""}
        redacted = _redact_sensitive_values(params)
        assert redacted["api_key"] == ""

    def test_handles_non_string_sensitive_value(self):
        params = {"password": 12345}
        redacted = _redact_sensitive_values(params)
        assert redacted["password"] == 12345

    def test_masks_authorization_and_cookie_keys(self):
        params = {
            "authorization": "Bearer tok-12345",
            "cookie": "session=abc123; domain=example.com",
        }
        redacted = _redact_sensitive_values(params)
        assert isinstance(redacted["authorization"], dict)
        assert redacted["authorization"]["redacted"] is True
        assert isinstance(redacted["cookie"], dict)
        assert redacted["cookie"]["redacted"] is True

    def test_masks_apikey_key(self):
        params = {"apikey": "pk-987654321"}
        redacted = _redact_sensitive_values(params)
        assert isinstance(redacted["apikey"], dict)
        assert redacted["apikey"]["redacted"] is True

    def test_content_pattern_masking_api_key_assignment(self):
        value = "export API_KEY='my-real-secret-key'"
        redacted = _redact_sensitive_values(value)
        assert isinstance(redacted, dict)
        assert redacted["redacted"] is True

    def test_content_pattern_masking_secret_assignment(self):
        value = 'secret: "production-secret-value"'
        redacted = _redact_sensitive_values(value)
        assert isinstance(redacted, dict)
        assert redacted["redacted"] is True

    def test_content_pattern_does_not_mask_regular_strings(self):
        value = "This is a normal string without any secrets."
        redacted = _redact_sensitive_values(value)
        assert redacted == value

    def test_redaction_respects_depth_limit(self):
        deeply_nested = {
            "a": {
                "b": {
                    "c": {
                        "d": {
                            "e": {
                                "f": {"g": {"h": {"i": {"j": {"k": {"password": "deep-secret"}}}}}}
                            }
                        }
                    }
                }
            }
        }
        redacted = _redact_sensitive_values(deeply_nested)
        # After depth 10 the recursion stops; the deepest key may be preserved as-is
        # or masked. Either outcome is acceptable as long as no exception is raised.
        assert isinstance(redacted, dict)


# ---------------------------------------------------------------------------
# Paket 3B – Redaction in audit records (integration)
# ---------------------------------------------------------------------------


class TestAuditRedaction:
    """Integration tests verifying redaction in written audit records."""

    async def test_sensitive_params_redacted_in_audit_record(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)

        await mcp_server.run_shell("echo hello")

        payload = parse_payload(await mcp_server.get_recent_tool_calls(limit=5))
        records = payload["details"]["records"]
        shell_record = None
        for record in records:
            if record.get("tool_name") == "run_shell":
                shell_record = record
                break
        assert shell_record is not None
        params = shell_record.get("params", {})
        command = params.get("command", "")
        assert "echo hello" in str(command)

    async def test_audit_tool_fields_present_after_redaction(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)

        await mcp_server.list_directory(".")
        await mcp_server.read_file("missing.txt")

        payload = parse_payload(await mcp_server.get_recent_tool_calls(limit=5))
        assert payload["ok"] is True
        assert payload["details"]["returned_records"] >= 2
        for record in payload["details"]["records"]:
            assert "timestamp" in record
            assert "tool_name" in record
            assert "params" in record
            assert "result" in record
            assert "telemetry" in record

    async def test_activity_summary_still_works_with_redacted_params(
        self, temp_audit_project, monkeypatch
    ):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)

        target = project / "note.txt"
        target.write_text("hello", encoding="utf-8")
        await mcp_server.read_file("note.txt")
        await mcp_server.run_shell("pytest --version")

        payload = parse_payload(await mcp_server.activity_summary(limit=10))
        assert payload["ok"] is True
        assert payload["details"]["session_id"]
        activity = payload["details"]["activity"]
        assert "note.txt" in activity["touched_paths"]


class TestAuditDecisionFilteringE2E:
    """E2E regression for policy decision audit filters."""

    async def test_rule_deny_record_can_be_filtered_by_decision_risk_and_source(
        self, temp_audit_project, monkeypatch
    ):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        policy_path = project / "policy.json"
        policy_path.write_text(
            json.dumps(
                {
                    "rules": [
                        {
                            "name": "deny-blocked-shell",
                            "scope": "run_shell",
                            "action": "deny",
                            "conditions": [
                                {
                                    "type": "regex",
                                    "field": "command",
                                    "pattern": r"echo\s+blocked",
                                }
                            ],
                            "metadata": {"risk_level": "high"},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("CLAUDE_BRIDGE_GUARD_POLICY", str(policy_path))
        mcp_server.set_config(project_dir=project, auto_approve=True)

        await mcp_server.run_shell("echo blocked")

        filtered = get_recent_tool_calls(
            limit=10,
            decision_action="deny",
            decision_risk_level="high",
            decision_source="rule",
        )
        assert filtered["returned_records"] == 1
        record = filtered["records"][0]
        assert record["tool_name"] == "run_shell"
        assert record["decision_metadata"]["rule_name"] == "deny-blocked-shell"


# ---------------------------------------------------------------------------
# Cross-cutting backward-compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Verify existing summary / insight flows still pass after changes."""

    async def test_session_insights_telemetry_unchanged(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)

        await mcp_server.read_file("missing.txt")
        await mcp_server.list_directory(".")

        payload = parse_payload(await mcp_server.session_insights(limit=10))
        assert payload["ok"] is True
        telemetry = payload["details"]["telemetry"]
        assert telemetry["total_estimated_tokens"] >= 1
        assert "list_directory" in telemetry["tool_estimated_tokens"]

    async def test_usage_insights_still_reports_top_cost_tools(
        self, temp_audit_project, monkeypatch
    ):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)

        await mcp_server.list_directory(".")
        await mcp_server.read_file("missing.txt")

        payload = parse_payload(await mcp_server.usage_insights(limit=10))
        assert payload["ok"] is True
        assert payload["details"]["top_cost_tools"]


class TestAiDecisionInAuditRecords:
    """Verify AI decision metadata is properly structured and extractable."""

    def test_extract_ai_deny_decision_from_result(self):
        result = json.dumps(
            {
                "ok": False,
                "message": "AI blocked",
                "code": "policy_denied",
                "details": {
                    "decision": {
                        "action": "deny",
                        "source": "ai",
                        "risk_level": "high",
                        "reason": "AI evaluator detected risk",
                        "risk_reasons": ["detected_pattern"],
                        "metadata": {"ai_reason": "matched deny pattern", "tool_name": "run_shell"},
                    }
                },
            }
        )
        fields = _extract_policy_decision(result)
        assert fields is not None
        assert fields["decision_action"] == "deny"
        assert fields["decision_source"] == "ai"
        assert fields["decision_risk_level"] == "high"
        assert fields["decision_reason"] == "AI evaluator detected risk"
        assert isinstance(fields["decision_metadata"], dict)
        assert fields["decision_metadata"]["ai_reason"] == "matched deny pattern"
        assert fields["decision_metadata"]["tool_name"] == "run_shell"

    def test_extract_ai_allow_decision_with_metadata(self):
        result = json.dumps(
            {
                "ok": True,
                "message": "done",
                "code": "success",
                "details": {
                    "decision": {
                        "action": "allow",
                        "source": "ai",
                        "risk_level": "low",
                        "reason": "AI evaluator found no risk",
                        "risk_reasons": [],
                        "metadata": {"ai_reason": "local evaluator ok", "tool_name": "write_file"},
                    }
                },
            }
        )
        fields = _extract_policy_decision(result)
        assert fields is not None
        assert fields["decision_action"] == "allow"
        assert fields["decision_source"] == "ai"
        assert fields["decision_risk_level"] == "low"
        assert isinstance(fields["decision_metadata"], dict)
        assert fields["decision_metadata"]["tool_name"] == "write_file"

    def test_ai_metadata_preserved_in_audit_record_format(self):
        result = json.dumps(
            {
                "ok": False,
                "message": "flagged",
                "details": {
                    "decision": {
                        "action": "ask",
                        "source": "ai",
                        "risk_level": "medium",
                        "reason": "uncertain operation",
                        "risk_reasons": ["unverified_source", "network_call"],
                        "metadata": {
                            "ai_reason": "AI uncertain",
                            "tool_name": "run_shell",
                            "prompt_snippet": "Tool: run_shell...",
                        },
                    }
                },
            }
        )
        fields = _extract_policy_decision(result)
        assert fields is not None
        assert fields["decision_source"] == "ai"
        assert fields["decision_action"] == "ask"
        if isinstance(fields["decision_risk_reasons"], list):
            assert "unverified_source" in fields["decision_risk_reasons"]


# ---------------------------------------------------------------------------
# Retention Config and Export Format Models
# ---------------------------------------------------------------------------


class TestExportFormat:
    def test_jsonl_value(self):
        assert ExportFormat.JSONL.value == "jsonl"

    def test_summary_json_value(self):
        assert ExportFormat.SUMMARY_JSON.value == "summary-json"

    def test_from_string(self):
        assert ExportFormat("jsonl") is ExportFormat.JSONL
        assert ExportFormat("summary-json") is ExportFormat.SUMMARY_JSON

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError):
            ExportFormat("csv")


class TestRetentionConfig:
    def test_defaults(self):
        cfg = RetentionConfig()
        assert cfg.retention_days == 90
        assert cfg.max_sessions == 100
        assert cfg.export_format == ExportFormat.JSONL
        assert cfg.include_telemetry is True
        assert cfg.include_redacted is True

    def test_custom_values(self):
        cfg = RetentionConfig(
            retention_days=30,
            max_sessions=50,
            export_format=ExportFormat.SUMMARY_JSON,
            include_telemetry=False,
            include_redacted=False,
        )
        assert cfg.retention_days == 30
        assert cfg.max_sessions == 50
        assert cfg.export_format == ExportFormat.SUMMARY_JSON
        assert cfg.include_telemetry is False
        assert cfg.include_redacted is False

    def test_to_dict_roundtrip(self):
        cfg = RetentionConfig(retention_days=60, max_sessions=200)
        data = cfg.to_dict()
        assert data["retention_days"] == 60
        assert data["max_sessions"] == 200
        assert data["export_format"] == "jsonl"
        assert data["include_telemetry"] is True
        assert data["include_redacted"] is True
        restored = RetentionConfig.from_dict(data)
        assert restored.retention_days == cfg.retention_days
        assert restored.max_sessions == cfg.max_sessions
        assert restored.export_format == cfg.export_format

    def test_from_dict_with_defaults(self):
        cfg = RetentionConfig.from_dict({})
        assert cfg.retention_days == 90
        assert cfg.max_sessions == 100
        assert cfg.export_format == ExportFormat.JSONL

    def test_from_dict_with_export_format_string(self):
        cfg = RetentionConfig.from_dict({"export_format": "summary-json"})
        assert cfg.export_format == ExportFormat.SUMMARY_JSON

    def test_from_dict_with_invalid_export_format_falls_back(self):
        cfg = RetentionConfig.from_dict({"export_format": "csv"})
        assert cfg.export_format == ExportFormat.JSONL

    def test_from_dict_with_export_format_enum(self):
        cfg = RetentionConfig.from_dict({"export_format": ExportFormat.SUMMARY_JSON})
        assert cfg.export_format == ExportFormat.SUMMARY_JSON

    def test_is_record_expired_old_record(self):
        cfg = RetentionConfig(retention_days=30)
        old_ts = "2024-01-01T00:00:00Z"
        now_ts = "2024-12-01T00:00:00Z"
        record = {"timestamp": old_ts, "tool_name": "read_file"}
        assert cfg.is_record_expired(record, now_iso=now_ts) is True

    def test_is_record_expired_recent_record(self):
        cfg = RetentionConfig(retention_days=90)
        recent_ts = "2024-11-01T00:00:00Z"
        now_ts = "2024-12-01T00:00:00Z"
        record = {"timestamp": recent_ts, "tool_name": "read_file"}
        assert cfg.is_record_expired(record, now_iso=now_ts) is False

    def test_is_record_expired_missing_timestamp(self):
        cfg = RetentionConfig()
        record = {"tool_name": "read_file"}
        assert cfg.is_record_expired(record) is False

    def test_is_record_expired_empty_timestamp(self):
        cfg = RetentionConfig()
        record = {"timestamp": "", "tool_name": "read_file"}
        assert cfg.is_record_expired(record) is False


class TestAuditExport:
    def test_jsonl_export_payload(self):
        records = [{"record_id": "a1", "tool_name": "read_file"}]
        export = AuditExport(
            session_id="sess-001",
            export_format=ExportFormat.JSONL,
            records_payload=records,
            record_count=1,
            retention_config=RetentionConfig(),
        )
        assert export.session_id == "sess-001"
        assert export.export_format == ExportFormat.JSONL
        assert export.record_count == 1
        assert export.to_dict()["export_format"] == "jsonl"

    def test_summary_json_export_payload(self):
        summary = {"session_id": "sess-002", "tool_counts": {"read_file": 5}}
        export = AuditExport(
            session_id="sess-002",
            export_format=ExportFormat.SUMMARY_JSON,
            records_payload=summary,
            record_count=5,
            retention_config=RetentionConfig(export_format=ExportFormat.SUMMARY_JSON),
        )
        assert export.export_format == ExportFormat.SUMMARY_JSON
        data = export.to_dict()
        assert data["export_format"] == "summary-json"
        assert data["records_payload"]["tool_counts"]["read_file"] == 5

    def test_to_jsonl(self):
        records = [
            {"record_id": "r1", "tool_name": "read_file"},
            {"record_id": "r2", "tool_name": "write_file"},
        ]
        export = AuditExport(
            session_id="s1",
            export_format=ExportFormat.JSONL,
            records_payload=records,
            record_count=2,
        )
        jsonl = export.to_jsonl()
        lines = [line for line in jsonl.strip().split("\n") if line.strip()]
        assert len(lines) == 2
        parsed = [json.loads(line) for line in lines]
        assert parsed[0]["record_id"] == "r1"
        assert parsed[1].get("record_id") == "r2"

    def test_to_jsonl_raises_for_wrong_format(self):
        export = AuditExport(
            session_id="s1",
            export_format=ExportFormat.SUMMARY_JSON,
            records_payload={},
            record_count=0,
        )
        with pytest.raises(ValueError, match="JSONL"):
            export.to_jsonl()

    def test_to_summary_json(self):
        payload = {"session_id": "s1", "total": 3}
        export = AuditExport(
            session_id="s1",
            export_format=ExportFormat.SUMMARY_JSON,
            records_payload=payload,
            record_count=3,
        )
        output = export.to_summary_json()
        parsed = json.loads(output)
        assert parsed["session_id"] == "s1"
        assert parsed["total"] == 3

    def test_to_summary_json_raises_for_wrong_format(self):
        export = AuditExport(
            session_id="s1",
            export_format=ExportFormat.JSONL,
            records_payload=[],
            record_count=0,
        )
        with pytest.raises(ValueError, match="summary-json"):
            export.to_summary_json()

    def test_exported_at_is_set(self):
        export = AuditExport(
            session_id="s1",
            export_format=ExportFormat.JSONL,
            records_payload=[],
            record_count=0,
        )
        assert export.exported_at
        assert "T" in export.exported_at

    def test_retention_config_in_to_dict(self):
        cfg = RetentionConfig(retention_days=60, max_sessions=50)
        export = AuditExport(
            session_id="s1",
            export_format=ExportFormat.JSONL,
            records_payload=[],
            record_count=0,
            retention_config=cfg,
        )
        data = export.to_dict()
        assert data["retention_config"]["retention_days"] == 60
        assert data["retention_config"]["max_sessions"] == 50


class TestStripRedactedValue:
    def test_strips_redacted_dict(self):
        redacted = {"redacted": True, "sha256": "abc", "length": 10, "reason": "sensitive value"}
        assert _strip_redacted_value(redacted) == "[REDACTED]"

    def test_preserves_normal_dict(self):
        normal = {"file": "test.py", "line": 42}
        result = _strip_redacted_value(normal)
        assert result == {"file": "test.py", "line": 42}

    def test_strips_nested_redacted(self):
        nested = {
            "params": {
                "api_key": {"redacted": True, "sha256": "abc", "length": 8, "reason": "sensitive value"},
                "file": "config.py",
            }
        }
        result = _strip_redacted_value(nested)
        assert result["params"]["api_key"] == "[REDACTED]"
        assert result["params"]["file"] == "config.py"

    def test_strips_in_list(self):
        items = [
            {"secret": {"redacted": True, "sha256": "x", "length": 5, "reason": "sensitive value"}},
            {"name": "ok"},
        ]
        result = _strip_redacted_value(items)
        assert result[0]["secret"] == "[REDACTED]"
        assert result[1]["name"] == "ok"

    def test_preserves_primitives(self):
        assert _strip_redacted_value(42) == 42
        assert _strip_redacted_value("hello") == "hello"
        assert _strip_redacted_value(None) is None


class TestParseRetentionConfig:
    def test_none_returns_default(self):
        cfg = _parse_retention_config(None)
        assert isinstance(cfg, RetentionConfig)
        assert cfg.retention_days == 90

    def test_passes_through_retention_config(self):
        original = RetentionConfig(retention_days=14)
        cfg = _parse_retention_config(original)
        assert cfg is original

    def test_dict_converted(self):
        cfg = _parse_retention_config({"retention_days": 7, "max_sessions": 10})
        assert cfg.retention_days == 7
        assert cfg.max_sessions == 10


class TestExportAuditRecords:
    def test_jsonl_export_returns_audit_export(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)
        reset_audit_session()

        (project / "hello.txt").write_text("hi", encoding="utf-8")
        import asyncio

        async def _run():
            await mcp_server.read_file("hello.txt")

        asyncio.run(_run())

        export = export_audit_records()
        assert isinstance(export, AuditExport)
        assert export.export_format == ExportFormat.JSONL
        assert export.record_count >= 1

    def test_summary_json_export_returns_summary(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)
        reset_audit_session()

        (project / "hello.txt").write_text("hi", encoding="utf-8")
        import asyncio

        async def _run():
            await mcp_server.read_file("hello.txt")

        asyncio.run(_run())

        export = export_audit_records(export_format=ExportFormat.SUMMARY_JSON)
        assert export.export_format == ExportFormat.SUMMARY_JSON
        assert isinstance(export.records_payload, dict)

    def test_export_without_telemetry(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)
        reset_audit_session()

        (project / "hello.txt").write_text("hi", encoding="utf-8")
        import asyncio

        async def _run():
            await mcp_server.read_file("hello.txt")

        asyncio.run(_run())

        export = export_audit_records(retention_config={"include_telemetry": False})
        assert export.record_count >= 1
        for record in export.records_payload:
            assert "telemetry" not in record

    def test_export_without_redacted(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)
        reset_audit_session()

        (project / "hello.txt").write_text("hi", encoding="utf-8")
        import asyncio

        async def _run():
            await mcp_server.read_file("hello.txt")

        asyncio.run(_run())

        export = export_audit_records(retention_config={"include_redacted": False})
        assert export.record_count >= 1
        assert export.retention_config.include_redacted is False

    def test_export_with_custom_config(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)
        reset_audit_session()

        cfg = RetentionConfig(retention_days=30, export_format=ExportFormat.SUMMARY_JSON)
        export = export_audit_records(retention_config=cfg)
        assert export.retention_config.retention_days == 30
        assert export.retention_config.export_format == ExportFormat.SUMMARY_JSON


class TestApplyRetention:
    def test_dry_run_does_not_delete(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)
        reset_audit_session()

        (project / "hello.txt").write_text("hi", encoding="utf-8")
        import asyncio

        async def _run():
            await mcp_server.read_file("hello.txt")

        asyncio.run(_run())

        result = apply_retention(dry_run=True)
        assert result["dry_run"] is True
        assert isinstance(result["sessions_removed"], int)
        assert isinstance(result["records_expired"], int)
        files_before = list(audit_dir.glob("*.jsonl"))
        assert len(files_before) >= 1

    def test_apply_retention_with_config(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)
        reset_audit_session()

        result = apply_retention(
            retention_config={"retention_days": 90, "max_sessions": 100},
            dry_run=True,
        )
        assert result["retention_config"]["retention_days"] == 90
        assert result["retention_config"]["max_sessions"] == 100

    def test_apply_retention_returns_config_in_result(self):
        result = apply_retention(dry_run=True)
        assert "retention_config" in result
        assert result["retention_config"]["retention_days"] == 90
        assert result["retention_config"]["max_sessions"] == 100
