"""Direct unit tests for tool_utils.py helper functions."""

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
            DecisionAction, DecisionSource, PolicyDecision, RiskLevel
        )
        decision = PolicyDecision(
            action=DecisionAction.DENY,
            source=DecisionSource.BUILTIN_GUARD,
            risk_level=RiskLevel.HIGH,
            reason="blocked",
            risk_reasons=["pattern: sudo"],
        )
        result = tu.json_response(
            False, "blocked", decision=decision, decision_in_details=True
        )
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
        decision = tu.path_guard_decision(
            ".env", "write", sensitive_reason=".env pattern"
        )
        assert decision.action == DecisionAction.DENY

    def test_normal_path_allows(self):
        if not _HAS_POLICY:
            pytest.skip("guard_policy not available")
        decision = tu.path_guard_decision("normal.py", "read")
        assert decision.action == DecisionAction.ALLOW

    def test_outside_workspace_denies(self):
        if not _HAS_POLICY:
            pytest.skip("guard_policy not available")
        decision = tu.path_guard_decision(
            "secret", "read", outside_workspace=True
        )
        assert decision.action == DecisionAction.DENY
