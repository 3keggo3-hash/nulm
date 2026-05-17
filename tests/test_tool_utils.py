"""Direct unit tests for tool_utils.py helper functions."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from claude_bridge import server as mcp_server
from claude_bridge import tool_utils as tu

try:
    from claude_bridge.guard_policy import DecisionAction

    _HAS_POLICY = True
except ImportError:
    _HAS_POLICY = False


def parse_payload(result: str) -> dict:
    return json.loads(result)


@pytest.fixture
def temp_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        mcp_server.set_config(project_dir=project, auto_approve=True)
        yield project


# ---------------------------------------------------------------------------
# json_response
# ---------------------------------------------------------------------------


class TestJsonResponse:
    def test_ok_basic(self):
        result = tu.json_response(True, "done")
        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert parsed["message"] == "done"

    def test_failure_with_code(self):
        result = tu.json_response(False, "error", code="oops")
        parsed = json.loads(result)
        assert parsed["ok"] is False
        assert parsed["code"] == "oops"

    def test_with_details(self):
        result = tu.json_response(True, "ok", details={"key": "val"})
        parsed = json.loads(result)
        assert parsed["details"]["key"] == "val"

    def test_with_decision_in_details(self):
        if not _HAS_POLICY:
            pytest.skip("guard_policy not available")
        from claude_bridge.guard_policy import (
            DecisionAction,
            DecisionSource,
            PolicyDecision,
            RiskLevel,
        )

        decision = PolicyDecision(
            action=DecisionAction.DENY,
            source=DecisionSource.BUILTIN_GUARD,
            risk_level=RiskLevel.HIGH,
            reason="blocked",
            risk_reasons=["pattern: sudo"],
        )
        result = tu.json_response(False, "blocked", decision=decision, decision_in_details=True)
        parsed = json.loads(result)
        assert parsed["details"]["decision"]["action"] == "deny"
        assert parsed["details"]["decision"]["source"] == "builtin_guard"


# ---------------------------------------------------------------------------
# find_secret_patterns
# ---------------------------------------------------------------------------


class TestFindSecretPatterns:
    def test_api_key_detected(self):
        patterns = tu.find_secret_patterns("api_key = 'sk-abc123'")
        assert "api_key_assignment" in patterns

    def test_password_detected(self):
        patterns = tu.find_secret_patterns('password = "secret123"')
        assert "password_assignment" in patterns

    def test_token_detected(self):
        patterns = tu.find_secret_patterns("token: 'ghp_abcdef'")
        assert any("token" in p for p in patterns)

    def test_clean_content(self):
        patterns = tu.find_secret_patterns("def foo():\n    return 42\n")
        assert patterns == []

    def test_empty_string(self):
        patterns = tu.find_secret_patterns("")
        assert patterns == []

    def test_aws_key_detected(self):
        patterns = tu.find_secret_patterns("AWS_ACCESS_KEY_ID = AKIAIOSFODNN7EXAMPLE")
        assert any("aws" in p.lower() for p in patterns) or len(patterns) > 0


# ---------------------------------------------------------------------------
# is_binary_bytes
# ---------------------------------------------------------------------------


class TestIsBinaryBytes:
    def test_text_is_not_binary(self):
        assert tu.is_binary_bytes(b"hello world\n") is False

    def test_null_byte_is_binary(self):
        assert tu.is_binary_bytes(b"hello\x00world") is True

    def test_empty_bytes(self):
        assert tu.is_binary_bytes(b"") is False


# ---------------------------------------------------------------------------
# is_within_root
# ---------------------------------------------------------------------------


class TestIsWithinRoot:
    def test_inside(self, temp_project):
        child = temp_project / "sub" / "file.txt"
        child.parent.mkdir()
        child.touch()
        assert tu.is_within_root(child, temp_project) is True

    def test_outside(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        other = tmp_path / "other"
        other.mkdir()
        assert tu.is_within_root(other, root) is False

    def test_same_path(self):
        p = Path("/tmp")
        assert tu.is_within_root(p, p) is True


# ---------------------------------------------------------------------------
# resolve_path
# ---------------------------------------------------------------------------


class TestResolvePath:
    def test_relative_path_resolves(self, temp_project):
        (temp_project / "foo.txt").write_text("hi")
        resolved = tu.resolve_path("foo.txt")
        assert resolved == (temp_project / "foo.txt").resolve()

    def test_absolute_path_resolves(self, temp_project):
        (temp_project / "bar.txt").write_text("hi")
        resolved = tu.resolve_path(str(temp_project / "bar.txt"))
        assert resolved == (temp_project / "bar.txt").resolve()

    def test_path_outside_project(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        mcp_server.set_config(project_dir=root, auto_approve=True)
        other = tmp_path / "other"
        other.mkdir()
        with pytest.raises(PermissionError):
            tu.resolve_path(str(other))

    def test_dot_resolves(self, temp_project):
        resolved = tu.resolve_path(".")
        assert resolved == temp_project.resolve()


# ---------------------------------------------------------------------------
# safe_read_text
# ---------------------------------------------------------------------------


class TestSafeReadText:
    def test_reads_valid_file(self, temp_project):
        target = temp_project / "data.txt"
        target.write_text("hello")
        assert tu.safe_read_text(target) == "hello"

    def test_missing_file(self, temp_project):
        with pytest.raises(FileNotFoundError):
            tu.safe_read_text(temp_project / "missing.txt")

    def test_binary_file_reads_gracefully(self, temp_project):
        target = temp_project / "bin.dat"
        target.write_bytes(b"\x89PNG\r\n\x1a\n")
        text = tu.safe_read_text(target)
        assert len(text) > 0


# ---------------------------------------------------------------------------
# sensitive_path_reason
# ---------------------------------------------------------------------------


class TestSensitivePathReason:
    def test_env_file_sensitive(self, temp_project):
        env = temp_project / ".env"
        env.write_text("KEY=val")
        reason = tu.sensitive_path_reason(env)
        assert reason is not None
        assert ".env" in reason

    def test_regular_file_not_sensitive(self, temp_project):
        f = temp_project / "normal.py"
        f.write_text("x=1")
        reason = tu.sensitive_path_reason(f)
        assert reason is None

    def test_pem_file_sensitive(self, temp_project):
        pem = temp_project / "key.pem"
        pem.write_text("-----BEGIN KEY-----")
        reason = tu.sensitive_path_reason(pem)
        assert reason is not None


# ---------------------------------------------------------------------------
# infer_project_root
# ---------------------------------------------------------------------------


class TestInferProjectRoot:
    def test_returns_set_root(self, temp_project):
        root = tu.infer_project_root(temp_project / "sub" / "file.txt")
        assert root.resolve() == temp_project.resolve()

    def test_returns_existing_root(self, temp_project):
        root = tu.infer_project_root(temp_project)
        assert root.resolve() == temp_project.resolve()


# ---------------------------------------------------------------------------
# path_guard_decision
# ---------------------------------------------------------------------------


class TestPathGuardDecision:
    def test_sensitive_path_denies(self):
        if not _HAS_POLICY:
            pytest.skip("guard_policy not available")
        decision = tu.path_guard_decision(".env", "write", sensitive_reason=".env pattern")
        assert decision.action == DecisionAction.DENY

    def test_normal_path_allows(self):
        if not _HAS_POLICY:
            pytest.skip("guard_policy not available")
        decision = tu.path_guard_decision("normal.py", "read")
        assert decision.action == DecisionAction.ALLOW

    def test_outside_workspace_denies(self):
        if not _HAS_POLICY:
            pytest.skip("guard_policy not available")
        decision = tu.path_guard_decision("secret", "read", outside_workspace=True)
        assert decision.action == DecisionAction.DENY


# ---------------------------------------------------------------------------
# PermissionCard
# ---------------------------------------------------------------------------


class TestPermissionCard:
    def test_basic_card_creation(self):
        card = tu.PermissionCard(
            agent="test_agent",
            action="Test action",
            reason="Testing permission card",
            risk=25,
        )
        assert card.agent == "test_agent"
        assert card.action == "Test action"
        assert card.reason == "Testing permission card"
        assert card.risk == 25
        assert card.files == []

    def test_card_with_files(self):
        card = tu.PermissionCard(
            agent="shell_agent",
            action="Read files",
            reason="Reading config",
            risk=10,
            files=["/etc/config", "/home/user/.config"],
        )
        assert len(card.files) == 2
        assert "/etc/config" in card.files

    def test_risk_category_safe(self):
        card = tu.PermissionCard(agent="test", action="test", reason="test", risk=15)
        assert card.risk_category == "Safe"
        assert card.risk_emoji == "🔒"

    def test_risk_category_low(self):
        card = tu.PermissionCard(agent="test", action="test", reason="test", risk=35)
        assert card.risk_category == "Low Risk"
        assert card.risk_emoji == "🔓"

    def test_risk_category_medium(self):
        card = tu.PermissionCard(agent="test", action="test", reason="test", risk=55)
        assert card.risk_category == "Medium"
        assert card.risk_emoji == "⚠️"

    def test_risk_category_high(self):
        card = tu.PermissionCard(agent="test", action="test", reason="test", risk=75)
        assert card.risk_category == "High"
        assert card.risk_emoji == "🚨"

    def test_risk_category_critical(self):
        card = tu.PermissionCard(agent="test", action="test", reason="test", risk=95)
        assert card.risk_category == "Critical"
        assert card.risk_emoji == "🚨"

    def test_risk_category_blocked(self):
        card = tu.PermissionCard(agent="test", action="test", reason="test", risk=100)
        assert card.risk_category == "Blocked"
        assert card.risk_emoji == "🚫"

    def test_format_card(self):
        card = tu.PermissionCard(
            agent="shell_agent",
            action="Run command",
            reason="Testing format",
            risk=30,
            files=["/tmp/test"],
        )
        formatted = card.format_card()
        assert "Permission Card" in formatted
        assert "shell_agent" in formatted
        assert "Run command" in formatted
        assert "30/100" in formatted

    def test_to_dict(self):
        card = tu.PermissionCard(
            agent="test_agent",
            action="Test",
            reason="Reason",
            risk=20,
            files=["/path/file.txt"],
            tool_name="run_shell",
            params={"key": "value"},
        )
        d = card.to_dict()
        assert d["agent"] == "test_agent"
        assert d["action"] == "Test"
        assert d["risk"] == 20
        assert d["risk_category"] == "Safe"
        assert d["files"] == ["/path/file.txt"]
        assert d["tool_name"] == "run_shell"
        assert d["params"] == {"key": "value"}


# ---------------------------------------------------------------------------
# Turkish labels
# ---------------------------------------------------------------------------


class TestTurkishLabels:
    def test_tr_labels_exist(self):
        assert "permission_card_title" in tu._TR_LABELS
        assert "agent" in tu._TR_LABELS
        assert tu._TR_LABELS["permission_card_title"] == "İzin Kartı"

    def test_risk_categories_exist(self):
        assert "Safe" in tu._RISK_CATEGORIES
        assert "Low Risk" in tu._RISK_CATEGORIES
        assert tu._RISK_CATEGORIES["Safe"] == "Güvenli"
        assert tu._RISK_CATEGORIES["High"] == "Yüksek"


# ---------------------------------------------------------------------------
# _extract_files_from_command (in _shell_run)
# ---------------------------------------------------------------------------


class TestExtractFilesFromCommand:
    def test_extract_absolute_paths(self):
        from claude_bridge._shell_run import _extract_files_from_command

        files = _extract_files_from_command("cat /etc/config /home/user/file.txt")
        assert "/etc/config" in files
        assert "/home/user/file.txt" in files

    def test_extract_relative_paths(self):
        from claude_bridge._shell_run import _extract_files_from_command

        files = _extract_files_from_command("python src/main.py tests/test.py")
        assert "src/main.py" in files
        assert "tests/test.py" in files

    def test_extract_tilde_paths(self):
        from claude_bridge._shell_run import _extract_files_from_command

        files = _extract_files_from_command("cat ~/Documents/file.txt")
        assert "~/Documents/file.txt" in files

    def test_ignores_flags(self):
        from claude_bridge._shell_run import _extract_files_from_command

        files = _extract_files_from_command("rm -rf /tmp/old_files --force")
        assert "-rf" not in files
        assert "--force" not in files

    def test_empty_command(self):
        from claude_bridge._shell_run import _extract_files_from_command

        files = _extract_files_from_command("")
        assert files == []

    def test_no_paths(self):
        from claude_bridge._shell_run import _extract_files_from_command

        files = _extract_files_from_command("git status")
        assert files == []


# ---------------------------------------------------------------------------
# request_approval with card
# ---------------------------------------------------------------------------


class TestRequestApprovalWithCard:
    @pytest.mark.asyncio
    async def test_request_approval_with_card_auto_approve(self, temp_project, monkeypatch):
        monkeypatch.setattr(tu, "approval_mode", lambda: (True, False))
        card = tu.PermissionCard(agent="test", action="test", reason="test", risk=10)
        result = await tu.request_approval("test_tool", {"key": "val"}, card=card)
        assert result is True

    @pytest.mark.asyncio
    async def test_request_approval_without_card(self, temp_project, monkeypatch):
        monkeypatch.setattr(tu, "approval_mode", lambda: (False, False))
        import sys
        from io import StringIO

        old_stderr = sys.stderr
        sys.stderr = StringIO()
        card = tu.PermissionCard(agent="test", action="test", reason="test", risk=10)
        result = await tu.request_approval("test_tool", {"key": "val"}, card=card)
        assert result is False
        stderr_output = sys.stderr.getvalue()
        assert "Permission Card" in stderr_output
        sys.stderr = old_stderr
