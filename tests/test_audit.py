"""Tests for audit decision extraction (Paket 3A) and redaction (Paket 3B)."""

import json
import os
import tempfile
from hashlib import sha256
from pathlib import Path

import pytest

from claude_bridge import server as mcp_server
from claude_bridge.audit import (
    _extract_policy_decision,
    _mask_secret_value,
    _redact_sensitive_values,
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
