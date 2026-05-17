"""Unit tests for the guard policy decision model (Paket 1A)."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json

import pytest

from claude_bridge.guard_policy import (
    DecisionAction,
    DecisionSource,
    PolicyDecision,
    RiskLevel,
    ToolRequestContext,
)

# ---------------------------------------------------------------------------
# DecisionAction
# ---------------------------------------------------------------------------


class TestDecisionAction:
    def test_allow_value(self) -> None:
        assert DecisionAction.ALLOW.value == "allow"
        assert DecisionAction.ALLOW == "allow"

    def test_deny_value(self) -> None:
        assert DecisionAction.DENY.value == "deny"
        assert DecisionAction.DENY == "deny"

    def test_ask_value(self) -> None:
        assert DecisionAction.ASK.value == "ask"
        assert DecisionAction.ASK == "ask"

    def test_invalid_value_raises(self) -> None:
        with pytest.raises(ValueError):
            DecisionAction("invalid")

    def test_iteration_yields_three_members(self) -> None:
        values = list(DecisionAction)
        assert len(values) == 3
        assert DecisionAction.ALLOW in values
        assert DecisionAction.DENY in values
        assert DecisionAction.ASK in values

    def test_from_string_matches_value(self) -> None:
        assert DecisionAction("allow") is DecisionAction.ALLOW
        assert DecisionAction("deny") is DecisionAction.DENY
        assert DecisionAction("ask") is DecisionAction.ASK


# ---------------------------------------------------------------------------
# DecisionSource
# ---------------------------------------------------------------------------


class TestDecisionSource:
    def test_members_exist(self) -> None:
        assert DecisionSource.DEFAULT.value == "default"
        assert DecisionSource.BUILTIN_GUARD.value == "builtin_guard"
        assert DecisionSource.RULE.value == "rule"
        assert DecisionSource.APPROVAL.value == "approval"
        assert DecisionSource.AI.value == "ai"

    def test_invalid_value_raises(self) -> None:
        with pytest.raises(ValueError):
            DecisionSource("unknown_source")

    def test_five_members(self) -> None:
        assert len(list(DecisionSource)) == 5


# ---------------------------------------------------------------------------
# RiskLevel
# ---------------------------------------------------------------------------


class TestRiskLevel:
    def test_members_exist(self) -> None:
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value == "high"
        assert RiskLevel.CRITICAL.value == "critical"

    def test_invalid_value_raises(self) -> None:
        with pytest.raises(ValueError):
            RiskLevel("unknown")

    def test_four_members(self) -> None:
        assert len(list(RiskLevel)) == 4


# ---------------------------------------------------------------------------
# PolicyDecision
# ---------------------------------------------------------------------------


class TestPolicyDecision:
    def test_construction_minimal(self) -> None:
        d = PolicyDecision(
            action=DecisionAction.ALLOW,
            source=DecisionSource.DEFAULT,
        )
        assert d.action is DecisionAction.ALLOW
        assert d.source is DecisionSource.DEFAULT
        assert d.risk_level is RiskLevel.LOW
        assert d.reason == ""
        assert d.risk_reasons == []
        assert d.metadata == {}

    def test_construction_full(self) -> None:
        d = PolicyDecision(
            action=DecisionAction.DENY,
            source=DecisionSource.BUILTIN_GUARD,
            risk_level=RiskLevel.HIGH,
            reason="blocked pattern: rm -rf",
            risk_reasons=["destructive operation", "no approval"],
            metadata={"blocked_pattern": "rm -r", "guard_name": "shell"},
        )
        assert d.action is DecisionAction.DENY
        assert d.risk_level is RiskLevel.HIGH
        assert d.reason == "blocked pattern: rm -rf"
        assert len(d.risk_reasons) == 2
        assert d.metadata["blocked_pattern"] == "rm -r"

    def test_to_dict_minimal(self) -> None:
        d = PolicyDecision(action=DecisionAction.ALLOW, source=DecisionSource.DEFAULT)
        result = d.to_dict()
        assert result == {
            "action": "allow",
            "source": "default",
            "risk_level": "low",
            "reason": "",
            "risk_reasons": [],
            "metadata": {},
        }

    def test_to_dict_full(self) -> None:
        d = PolicyDecision(
            action=DecisionAction.DENY,
            source=DecisionSource.BUILTIN_GUARD,
            risk_level=RiskLevel.CRITICAL,
            reason="sensitive path",
            risk_reasons=["key file", ".env"],
            metadata={"path": "/secret/.env"},
        )
        result = d.to_dict()
        assert result["action"] == "deny"
        assert result["source"] == "builtin_guard"
        assert result["risk_level"] == "critical"
        assert result["reason"] == "sensitive path"
        assert result["risk_reasons"] == ["key file", ".env"]
        assert result["metadata"] == {"path": "/secret/.env"}

    def test_to_dict_is_json_serializable(self) -> None:
        d = PolicyDecision(
            action=DecisionAction.ASK,
            source=DecisionSource.RULE,
            risk_level=RiskLevel.MEDIUM,
            reason="needs confirmation",
        )
        raw = json.dumps(d.to_dict())
        parsed = json.loads(raw)
        assert parsed["action"] == "ask"
        assert parsed["source"] == "rule"

    def test_from_dict_roundtrip(self) -> None:
        original = PolicyDecision(
            action=DecisionAction.DENY,
            source=DecisionSource.APPROVAL,
            risk_level=RiskLevel.HIGH,
            reason="user rejected",
            risk_reasons=["r1", "r2"],
            metadata={"key": "val"},
        )
        restored = PolicyDecision.from_dict(original.to_dict())
        assert restored.action is original.action
        assert restored.source is original.source
        assert restored.risk_level is original.risk_level
        assert restored.reason == original.reason
        assert restored.risk_reasons == original.risk_reasons
        assert restored.metadata == original.metadata

    def test_from_dict_missing_fields_safe_defaults(self) -> None:
        d = PolicyDecision.from_dict({})
        assert d.action is DecisionAction.DENY
        assert d.source is DecisionSource.BUILTIN_GUARD
        assert d.risk_level is RiskLevel.MEDIUM
        assert d.reason == ""
        assert d.risk_reasons == []

    def test_from_dict_partial(self) -> None:
        d = PolicyDecision.from_dict({"action": "allow", "source": "ai", "reason": "ok"})
        assert d.action is DecisionAction.ALLOW
        assert d.source is DecisionSource.AI
        assert d.reason == "ok"

    def test_from_dict_invalid_action_falls_back(self) -> None:
        d = PolicyDecision.from_dict({"action": "bogus"})
        assert d.action is DecisionAction.DENY

    def test_risk_reasons_are_independent(self) -> None:
        d = PolicyDecision(
            action=DecisionAction.ALLOW,
            source=DecisionSource.DEFAULT,
            risk_reasons=["a"],
        )
        d.risk_reasons.append("b")
        snapshot = d.to_dict()
        # snapshot must reflect the appended reason
        assert snapshot["risk_reasons"] == ["a", "b"]
        # mutating the returned list must not mutate the original
        snapshot["risk_reasons"].append("c")
        assert d.risk_reasons == ["a", "b"]


# ---------------------------------------------------------------------------
# ToolRequestContext
# ---------------------------------------------------------------------------


class TestToolRequestContext:
    def test_construction_minimal(self) -> None:
        ctx = ToolRequestContext(tool_name="run_shell")
        assert ctx.tool_name == "run_shell"
        assert ctx.params == {}
        assert ctx.project_dir is None
        assert ctx.allowed_roots == []

    def test_construction_full(self) -> None:
        ctx = ToolRequestContext(
            tool_name="write_file",
            params={"path": "out.txt", "content": "hi"},
            project_dir="/home/user/project",
            allowed_roots=["/home/user/project", "/tmp"],
        )
        assert ctx.tool_name == "write_file"
        assert ctx.params["path"] == "out.txt"
        assert ctx.project_dir == "/home/user/project"
        assert len(ctx.allowed_roots) == 2

    def test_to_dict(self) -> None:
        ctx = ToolRequestContext(
            tool_name="read_file",
            params={"path": "README.md"},
            project_dir="/app",
            allowed_roots=["/app"],
        )
        result = ctx.to_dict()
        assert result == {
            "tool_name": "read_file",
            "params": {"path": "README.md"},
            "project_dir": "/app",
            "allowed_roots": ["/app"],
        }

    def test_to_dict_is_json_serializable(self) -> None:
        ctx = ToolRequestContext(tool_name="test", params={"a": 1})
        raw = json.dumps(ctx.to_dict())
        parsed = json.loads(raw)
        assert parsed["tool_name"] == "test"
        assert parsed["params"] == {"a": 1}

    def test_params_copy_independent(self) -> None:
        p = {"x": [1]}
        ctx = ToolRequestContext(tool_name="t", params=p)
        p["x"].append(2)
        # to_dict snapshot reflects the original params value at construction time
        assert ctx.to_dict()["params"] == {"x": [1, 2]}

    def test_construction_with_role(self) -> None:
        ctx = ToolRequestContext(tool_name="run_shell", role="senior")
        assert ctx.role == "senior"
        assert ctx.user is None

    def test_construction_with_user(self) -> None:
        ctx = ToolRequestContext(tool_name="run_shell", user="alice")
        assert ctx.user == "alice"
        assert ctx.role is None

    def test_construction_with_role_and_user(self) -> None:
        ctx = ToolRequestContext(
            tool_name="run_shell",
            role="ci",
            user="bot-42",
        )
        assert ctx.role == "ci"
        assert ctx.user == "bot-42"

    def test_to_dict_with_role(self) -> None:
        ctx = ToolRequestContext(
            tool_name="write_file",
            role="contractor",
            user="ext-1",
        )
        result = ctx.to_dict()
        assert result["role"] == "contractor"
        assert result["user"] == "ext-1"

    def test_to_dict_without_role_omits_key(self) -> None:
        ctx = ToolRequestContext(tool_name="read_file")
        result = ctx.to_dict()
        assert "role" not in result
        assert "user" not in result

    def test_to_dict_json_serializable_with_role(self) -> None:
        ctx = ToolRequestContext(tool_name="test", role="junior", user="dev-1")
        raw = json.dumps(ctx.to_dict())
        parsed = json.loads(raw)
        assert parsed["role"] == "junior"
        assert parsed["user"] == "dev-1"


class TestLoadGuardPolicyCache:
    def test_cache_invalidated_on_file_change(self, tmp_path, monkeypatch):
        import time
        from claude_bridge.guard_policy import (
            _invalidate_policy_cache,
            load_guard_policy,
        )

        policy_file = tmp_path / ".claude-bridge-guard.json"
        policy_file.write_text('{"blocked_shell_patterns": ["old"]}')
        monkeypatch.setenv("CLAUDE_BRIDGE_GUARD_POLICY", str(policy_file))
        _invalidate_policy_cache()

        first = load_guard_policy()
        assert "old" in first["blocked_shell_patterns"]

        # Wait briefly so mtime changes, then update file
        time.sleep(0.05)
        policy_file.write_text('{"blocked_shell_patterns": ["new"]}')
        _invalidate_policy_cache()

        second = load_guard_policy()
        assert "new" in second["blocked_shell_patterns"]
        assert "old" not in second["blocked_shell_patterns"]
