"""Tests for CLI setup and desktop integration helpers."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


import json
import os
from pathlib import Path

from typer.testing import CliRunner

from claude_bridge import cli
from claude_bridge import skill_registry
from claude_bridge.prompt import build_desktop_config, build_target_config, generate_mcp_setup_guide
from claude_bridge import server as mcp_server
from claude_bridge.skill_schema import SkillMeta

runner = CliRunner()


def _reset_skill_registry(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    skill_registry._registry = None


class TestDesktopConfig:
    def test_build_desktop_config_uses_env_based_project_dir(self, tmp_path: Path):
        extra_root = tmp_path.parent / "other-root"
        extra_root.mkdir()
        config = build_desktop_config(
            tmp_path,
            allowed_roots=[tmp_path, extra_root],
            python_executable="/usr/bin/python3",
            package_root=Path("/tmp/fake-project"),
            auto_approve=True,
        )

        server = config["mcpServers"]["claude-bridge"]
        assert server["command"] == "/usr/bin/python3"
        assert server["args"] == ["-m", "claude_bridge.mcp_server"]
        assert server["env"]["CLAUDE_BRIDGE_PROJECT_DIR"] == str(tmp_path.resolve())
        assert server["env"]["CLAUDE_BRIDGE_ALLOWED_ROOTS"] == (
            os.pathsep.join([str(tmp_path.resolve()), str(extra_root.resolve())])
        )
        assert server["env"]["CLAUDE_BRIDGE_AUTO_APPROVE"] == "1"
        assert server["env"]["CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL"] == "0"
        assert server["env"]["CLAUDE_BRIDGE_TOOL_PROFILE"] == "standard"
        assert server["env"]["CLAUDE_BRIDGE_CONTEXT_BUDGET_PROFILE"] == "balanced"
        assert server["env"]["CLAUDE_BRIDGE_ONBOARDING_ENABLED"] == "1"
        assert server["env"]["PYTHONUNBUFFERED"] == "1"

    def test_build_desktop_config_can_explicitly_enable_client_managed_approval(
        self, tmp_path: Path
    ):
        config = build_desktop_config(
            tmp_path,
            python_executable="/usr/bin/python3",
            package_root=Path("/tmp/fake-project"),
            client_managed_approval=True,
        )

        server = config["mcpServers"]["claude-bridge"]
        assert server["env"]["CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL"] == "1"

    def test_build_desktop_config_can_use_low_token_profile(self, tmp_path: Path):
        config = build_desktop_config(
            tmp_path,
            python_executable="/usr/bin/python3",
            package_root=Path("/tmp/fake-project"),
            tool_profile="essential",
            context_budget_profile="low-cost",
        )

        server = config["mcpServers"]["claude-bridge"]
        assert server["env"]["CLAUDE_BRIDGE_TOOL_PROFILE"] == "essential"
        assert server["env"]["CLAUDE_BRIDGE_CONTEXT_BUDGET_PROFILE"] == "low-cost"

    def test_build_desktop_config_includes_approval_preset_when_requested(self, tmp_path: Path):
        config = build_desktop_config(
            tmp_path,
            python_executable="/usr/bin/python3",
            package_root=Path("/tmp/fake-project"),
            approval_preset="dev-safe",
        )

        server = config["mcpServers"]["claude-bridge"]
        assert server["env"]["CLAUDE_BRIDGE_APPROVAL_PRESET"] == "dev-safe"


class TestStartCommand:
    def test_start_uses_run_mcp_server_so_prompts_register(self, monkeypatch, tmp_path: Path):
        calls: list[str] = []

        def fake_server_runtime():
            return (
                lambda: {},
                object(),
                lambda **_kwargs: calls.append("set_config"),
                lambda: calls.append("run_mcp_server"),
            )

        monkeypatch.setattr(cli, "_server_runtime", fake_server_runtime)

        result = runner.invoke(cli.app, ["start", "--project-dir", str(tmp_path)])

        assert result.exit_code == 0
        assert calls == ["set_config", "run_mcp_server"]

    def test_generate_mcp_setup_guide_contains_json_config(self, tmp_path: Path):
        guide = generate_mcp_setup_guide(
            tmp_path,
            python_executable="/usr/bin/python3",
            package_root=Path("/tmp/fake-project"),
        )

        assert "claude_desktop_config.json" in guide
        assert "CLAUDE_BRIDGE_PROJECT_DIR" in guide
        assert '"command": "/usr/bin/python3"' in guide

    def test_build_target_config_supports_generic_stdio(self, tmp_path: Path):
        config = build_target_config(
            tmp_path,
            target="generic-stdio",
            python_executable="/usr/bin/python3",
            package_root=Path("/tmp/fake-project"),
        )

        server = config["servers"]["claude-bridge"]
        assert server["command"] == "/usr/bin/python3"
        assert server["args"] == ["-m", "claude_bridge.mcp_server"]

    def test_generate_mcp_setup_guide_supports_vscode_target(self, tmp_path: Path):
        guide = generate_mcp_setup_guide(tmp_path, target="vscode")

        assert '"mcp"' in guide
        assert '"servers"' in guide
        assert "VS Code" in guide


class TestCLI:
    def test_start_command_keeps_stdout_clean_for_mcp(self, tmp_path: Path, monkeypatch):
        calls: list[str] = []

        def fake_server_runtime():
            return (
                lambda: {},
                object(),
                lambda **_kwargs: None,
                lambda: calls.append("run_mcp_server"),
            )

        monkeypatch.setattr(cli, "_server_runtime", fake_server_runtime)

        result = runner.invoke(cli.app, ["start", "--project-dir", str(tmp_path)])

        assert result.exit_code == 0
        assert result.stdout == ""
        assert calls == ["run_mcp_server"]

    def test_version_option(self):
        result = runner.invoke(cli.app, ["--version"])

        assert result.exit_code == 0
        assert cli.__version__ in result.stdout

    def test_schedule_list_does_not_require_name_or_query(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_CACHE_DIR", str(tmp_path))

        result = runner.invoke(cli.app, ["schedule", "--list"])

        assert result.exit_code == 0
        assert "No schedules defined" in result.stdout

    def test_schedule_create_requires_name_cron_and_query(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_CACHE_DIR", str(tmp_path))

        result = runner.invoke(cli.app, ["schedule"])

        assert result.exit_code == 1
        assert "NAME is required" in result.stdout

    def test_skill_list_json(self, tmp_path: Path, monkeypatch):
        _reset_skill_registry(tmp_path, monkeypatch)
        registry = skill_registry.get_registry()
        registry.register(
            "docs",
            SkillMeta(name="docs", version="1.0", trigger_phrases=["docs"]),
            "def run(ctx): return None",
        )

        result = runner.invoke(cli.app, ["skill", "list", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["schema_version"] == "skill_list.v1"
        assert payload["skills"][0]["meta"]["name"] == "docs"

    def test_skill_recommend_json(self, tmp_path: Path, monkeypatch):
        _reset_skill_registry(tmp_path, monkeypatch)
        registry = skill_registry.get_registry()
        registry.register(
            "release-docs",
            SkillMeta(
                name="release-docs",
                version="1.0",
                trigger_phrases=["release notes"],
                tags=["docs"],
            ),
            "def run(ctx): return None",
        )

        result = runner.invoke(
            cli.app,
            ["skill", "recommend", "write release notes", "--json"],
        )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["schema_version"] == "skill_recommendations.v1"
        assert payload["matches"][0]["name"] == "release-docs"
        assert payload["matches"][0]["score"] > 0

    def test_skill_package_inspect_bad_package_json(self, tmp_path: Path):
        result = runner.invoke(
            cli.app,
            ["skill", "package-inspect", str(tmp_path / "missing.tar.gz"), "--json"],
        )

        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["error"] == "Package inspection failed"

    def test_setup_command_prints_setup_text(self, tmp_path: Path):
        extra_root = tmp_path.parent / "extra"
        extra_root.mkdir()
        result = runner.invoke(
            cli.app,
            ["setup", "--project-dir", str(tmp_path), "--allow-root", str(extra_root)],
        )

        assert result.exit_code == 0
        assert "Claude Desktop Setup" in result.stdout
        assert "System Prompt" in result.stdout
        assert tmp_path.name in result.stdout
        assert "CLAUDE_BRIDGE_PROJECT_DIR" in result.stdout
        assert "CLAUDE_BRIDGE_ALLOWED_ROOTS" in result.stdout

    def test_setup_command_supports_generic_target(self, tmp_path: Path):
        result = runner.invoke(
            cli.app,
            ["setup", "--project-dir", str(tmp_path), "--target", "generic-stdio"],
        )

        assert result.exit_code == 0
        assert "Target: generic-stdio" in result.stdout
        assert '"servers"' in result.stdout

    def test_install_command_writes_claude_desktop_config(self, tmp_path: Path):
        config_path = tmp_path / "claude_desktop_config.json"
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        extra_root = tmp_path / "extra"
        extra_root.mkdir()

        result = runner.invoke(
            cli.app,
            [
                "install",
                "--project-dir",
                str(project_dir),
                "--allow-root",
                str(extra_root),
                "--config-path",
                str(config_path),
                "--simple",
            ],
        )

        assert result.exit_code == 0
        assert "installed for Claude Desktop" in result.stdout
        written = json.loads(config_path.read_text(encoding="utf-8"))
        server = written["mcpServers"]["claude-bridge"]
        assert server["args"] == ["-m", "claude_bridge.mcp_server"]
        assert server["env"]["CLAUDE_BRIDGE_PROJECT_DIR"] == str(project_dir.resolve())
        assert server["env"]["CLAUDE_BRIDGE_ALLOWED_ROOTS"] == (
            os.pathsep.join([str(project_dir.resolve()), str(extra_root.resolve())])
        )
        assert server["env"]["CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL"] == "1"

    def test_install_command_writes_generic_target_config(self, tmp_path: Path):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        config_path = tmp_path / "generic.json"

        result = runner.invoke(
            cli.app,
            [
                "install",
                "--project-dir",
                str(project_dir),
                "--target",
                "generic-stdio",
                "--config-path",
                str(config_path),
                "--simple",
            ],
        )

        assert result.exit_code == 0
        assert "installed for generic-stdio" in result.stdout
        written = json.loads(config_path.read_text(encoding="utf-8"))
        server = written["servers"]["claude-bridge"]
        assert server["args"] == ["-m", "claude_bridge.mcp_server"]

    def test_install_command_uses_default_path_for_vscode_target(self, tmp_path: Path):
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        result = runner.invoke(
            cli.app,
            ["install", "--project-dir", str(project_dir), "--target", "vscode", "--simple"],
        )

        assert result.exit_code == 0
        expected_path = project_dir / ".claude-bridge.vscode.json"
        assert expected_path.exists()
        written = json.loads(expected_path.read_text(encoding="utf-8"))
        assert "mcp" in written

    def test_install_command_accepts_approval_preset(self, tmp_path: Path):
        config_path = tmp_path / "claude_desktop_config.json"
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        result = runner.invoke(
            cli.app,
            [
                "install",
                "--project-dir",
                str(project_dir),
                "--approval-preset",
                "dev-safe",
                "--config-path",
                str(config_path),
                "--simple",
            ],
        )

        assert result.exit_code == 0
        written = json.loads(config_path.read_text(encoding="utf-8"))
        server = written["mcpServers"]["claude-bridge"]
        assert server["env"]["CLAUDE_BRIDGE_APPROVAL_PRESET"] == "dev-safe"
        assert server["env"]["CLAUDE_BRIDGE_AUTO_APPROVE"] == "0"
        assert server["env"]["CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL"] == "1"

    def test_install_command_preserves_other_mcp_servers(self, tmp_path: Path):
        config_path = tmp_path / "claude_desktop_config.json"
        config_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "other-server": {
                            "command": "/usr/bin/other",
                            "args": ["serve"],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        result = runner.invoke(
            cli.app,
            [
                "install",
                "--project-dir",
                str(project_dir),
                "--config-path",
                str(config_path),
                "--simple",
            ],
        )

        assert result.exit_code == 0
        written = json.loads(config_path.read_text(encoding="utf-8"))
        assert "other-server" in written["mcpServers"]
        assert "claude-bridge" in written["mcpServers"]

    def test_install_command_rejects_invalid_json_config(self, tmp_path: Path):
        config_path = tmp_path / "claude_desktop_config.json"
        config_path.write_text("{bad json", encoding="utf-8")
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        result = runner.invoke(
            cli.app,
            [
                "install",
                "--project-dir",
                str(project_dir),
                "--config-path",
                str(config_path),
                "--simple",
            ],
        )

        assert result.exit_code == 1
        assert "Install failed" in result.stdout

    def test_configure_from_env_applies_project_dir(self, monkeypatch, tmp_path: Path):
        extra_root = tmp_path.parent / "extra-root"
        extra_root.mkdir(exist_ok=True)
        monkeypatch.setenv("CLAUDE_BRIDGE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("CLAUDE_BRIDGE_ALLOWED_ROOTS", f"{tmp_path}:{extra_root}")
        monkeypatch.setenv("CLAUDE_BRIDGE_AUTO_APPROVE", "true")
        monkeypatch.setenv("CLAUDE_BRIDGE_UNSAFE_AUTO_APPROVE_CONFIRMED", "1")
        monkeypatch.setenv("CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL", "false")

        mcp_server.configure_from_env()
        current = mcp_server.current_config()

        assert current["project_dir"] == tmp_path.resolve()
        assert current["allowed_roots"] == [tmp_path.resolve(), extra_root.resolve()]
        assert current["auto_approve"] is True
        assert current["client_managed_approval"] is False

    def test_audit_command_prints_latest_session_summary(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(tmp_path / "audit"))
        mcp_server.set_config(project_dir=tmp_path, auto_approve=True)
        target = tmp_path / "note.txt"
        target.write_text("hello", encoding="utf-8")

        import asyncio

        asyncio.run(mcp_server.read_file("note.txt"))
        asyncio.run(mcp_server.patch_file("note.txt", "hello", "hello bridge"))
        asyncio.run(mcp_server.run_shell("echo hello"))

        result = runner.invoke(cli.app, ["audit", "summary", "--last", "--limit", "5"])

        assert result.exit_code == 0
        assert "Audit Session" in result.stdout
        assert "read_file" in result.stdout
        assert "Touched paths" in result.stdout
        assert "note.txt" in result.stdout
        assert "Commands" in result.stdout
        assert "echo hello" in result.stdout
        assert "Validation" in result.stdout
        assert "Changes have not been validated yet" in result.stdout

    def test_audit_command_filters_policy_decisions(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(tmp_path / "audit"))
        policy_path = tmp_path / "policy.json"
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
        mcp_server.set_config(project_dir=tmp_path, auto_approve=True)

        import asyncio

        asyncio.run(mcp_server.run_shell("echo blocked"))

        result = runner.invoke(
            cli.app,
            [
                "audit",
                "summary",
                "--last",
                "--decision",
                "deny",
                "--risk",
                "high",
                "--source",
                "rule",
            ],
        )

        assert result.exit_code == 0
        assert "Policy decisions" in result.stdout
        assert "decision=deny/high/rule" in result.stdout
        assert "deny-blocked-shell" in result.stdout or "Rule matched" in result.stdout

    def test_replay_command_prints_human_readable_result(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(tmp_path / "audit"))
        policy_path = tmp_path / "policy.json"
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
        mcp_server.set_config(project_dir=tmp_path, auto_approve=True)

        import asyncio
        from claude_bridge.audit import get_recent_tool_calls

        asyncio.run(mcp_server.run_shell("echo blocked"))
        record_id = get_recent_tool_calls(limit=1)["records"][0]["record_id"]

        result = runner.invoke(cli.app, ["replay", "--record-id", record_id])

        assert result.exit_code == 0
        assert "Audit Replay" in result.stdout
        assert "Changed: False" in result.stdout
        assert "action=deny source=rule risk=high" in result.stdout

    def test_replay_command_rejects_unknown_record_id(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(tmp_path / "audit"))

        result = runner.invoke(cli.app, ["replay", "--record-id", "does-not-exist"])

        assert result.exit_code == 1
        assert "Audit record not found" in result.stdout

    def test_doctor_command_prints_health_checks(self, tmp_path: Path):
        result = runner.invoke(cli.app, ["doctor", "--project-dir", str(tmp_path)])

        assert result.exit_code == 0
        assert "Claude Bridge" in result.stdout
        assert "doctor" in result.stdout.lower()
        assert "Python version is supported" in result.stdout
        assert "claude_bridge package importable" in result.stdout
        assert "pytest-asyncio plugin available" in result.stdout
        assert "tiktoken package available" in result.stdout

    def test_doctor_security_command_prints_security_checks(self, tmp_path: Path):
        result = runner.invoke(cli.app, ["doctor", "security", "--project-dir", str(tmp_path)])

        assert result.exit_code == 0
        assert "Security Doctor" in result.stdout
        assert "Audit directory writable" in result.stdout
        assert "Guard policy valid" in result.stdout
        assert "Safe config flags" in result.stdout
        assert "Auto-approve warning" in result.stdout

    def test_policy_validate_accepts_valid_policy(self, tmp_path: Path):
        policy_path = tmp_path / "policy.json"
        policy_path.write_text(
            json.dumps(
                {
                    "rules": [
                        {
                            "name": "deny-npm-test",
                            "scope": "run_shell",
                            "action": "deny",
                            "conditions": [
                                {
                                    "type": "regex",
                                    "field": "command",
                                    "pattern": r"npm\s+test",
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        result = runner.invoke(cli.app, ["policy", "validate", "--path", str(policy_path)])

        assert result.exit_code == 0
        assert "Policy valid" in result.stdout
        assert "Rules: 1" in result.stdout
        assert "Errors: 0" in result.stdout

    def test_policy_validate_rejects_invalid_policy(self, tmp_path: Path):
        policy_path = tmp_path / "policy.json"
        policy_path.write_text(
            json.dumps({"rules": [{"name": "", "action": "deny", "conditions": []}]}),
            encoding="utf-8",
        )

        result = runner.invoke(cli.app, ["policy", "validate", "--path", str(policy_path)])

        assert result.exit_code == 1
        assert "Policy invalid" in result.stdout
        assert "Errors:" in result.stdout
        assert "name must not be empty" in result.stdout

    def test_policy_simulate_prints_rule_decision(self, tmp_path: Path):
        policy_path = tmp_path / "policy.json"
        policy_path.write_text(
            json.dumps(
                {
                    "rules": [
                        {
                            "name": "deny-npm-test",
                            "scope": "run_shell",
                            "action": "deny",
                            "risk_level": "high",
                            "conditions": [
                                {
                                    "type": "regex",
                                    "field": "command",
                                    "pattern": r"npm\s+test",
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        result = runner.invoke(
            cli.app,
            [
                "policy",
                "simulate",
                "--path",
                str(policy_path),
                "--tool",
                "run_shell",
                "--param",
                "command=npm test",
            ],
        )

        assert result.exit_code == 0
        assert "Action: deny" in result.stdout
        assert "Source: rule" in result.stdout
        assert "Risk: high" in result.stdout
        assert "Rule: deny-npm-test" in result.stdout

    def test_policy_simulate_rejects_bad_param(self, tmp_path: Path):
        policy_path = tmp_path / "policy.json"
        policy_path.write_text(json.dumps({"rules": []}), encoding="utf-8")

        result = runner.invoke(
            cli.app,
            [
                "policy",
                "simulate",
                "--path",
                str(policy_path),
                "--tool",
                "run_shell",
                "--param",
                "command",
            ],
        )

        assert result.exit_code == 1
        assert "key=value" in result.stdout

    def test_policy_simulate_with_ai_shows_ai_advisor(self, tmp_path: Path):
        policy_path = tmp_path / "policy.json"
        policy_path.write_text(json.dumps({"rules": []}), encoding="utf-8")

        result = runner.invoke(
            cli.app,
            [
                "policy",
                "simulate",
                "--path",
                str(policy_path),
                "--tool",
                "run_shell",
                "--param",
                "command=echo hello",
                "--with-ai",
            ],
        )

        assert result.exit_code == 0
        assert "Policy Decision:" in result.stdout
        assert "AI Advisor:" in result.stdout
        assert "Delta:" in result.stdout
        assert "agrees with policy" in result.stdout

    def test_policy_simulate_with_ai_and_deny_pattern(self, tmp_path: Path):
        policy_path = tmp_path / "policy.json"
        policy_path.write_text(json.dumps({"rules": []}), encoding="utf-8")

        result = runner.invoke(
            cli.app,
            [
                "policy",
                "simulate",
                "--path",
                str(policy_path),
                "--tool",
                "run_shell",
                "--param",
                "command=echo my-dangerous-command",
                "--with-ai",
                "--ai-deny",
                "my-dangerous",
            ],
        )

        assert result.exit_code == 0
        assert "Policy Decision:" in result.stdout
        assert "AI Advisor:" in result.stdout
        assert "deny" in result.stdout.lower()
        assert "Delta:" in result.stdout

    def test_policy_simulate_with_ai_and_ask_pattern(self, tmp_path: Path):
        policy_path = tmp_path / "policy.json"
        policy_path.write_text(json.dumps({"rules": []}), encoding="utf-8")

        result = runner.invoke(
            cli.app,
            [
                "policy",
                "simulate",
                "--path",
                str(policy_path),
                "--tool",
                "run_shell",
                "--param",
                "command=curl example.com",
                "--with-ai",
                "--ai-ask",
                "curl",
            ],
        )

        assert result.exit_code == 0
        assert "Policy Decision:" in result.stdout
        assert "AI Advisor:" in result.stdout
        assert "ask" in result.stdout.lower()
        assert "Delta:" in result.stdout

    def test_appeal_command_prints_result(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(tmp_path / "audit"))
        mcp_server.set_config(project_dir=tmp_path, auto_approve=True)

        import asyncio
        from claude_bridge.audit import get_recent_tool_calls

        asyncio.run(mcp_server.run_shell("sudo apt update"))

        record_id = get_recent_tool_calls(limit=1)["records"][0]["record_id"]

        result = runner.invoke(
            cli.app,
            ["appeal", "--record-id", record_id, "--justification", "Need access for debugging"],
        )

        assert result.exit_code == 0
        assert "Appeal" in result.stdout
        assert record_id in result.stdout
        assert "Status:" in result.stdout

    def test_appeal_command_can_request_escalation(self, monkeypatch, tmp_path: Path):
        import asyncio
        import claude_bridge.replay as replay_module
        from claude_bridge.audit import get_recent_tool_calls
        from claude_bridge.guard_policy import (
            DecisionAction,
            DecisionSource,
            PolicyDecision,
            RiskLevel,
        )
        from claude_bridge.replay import ReplayResult

        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(tmp_path / "audit"))
        mcp_server.set_config(project_dir=tmp_path, auto_approve=True)
        asyncio.run(mcp_server.run_shell("sudo apt update"))
        record_id = get_recent_tool_calls(limit=1)["records"][0]["record_id"]

        def _deny_replay(record, *, justification, **kwargs):
            decision = PolicyDecision(
                action=DecisionAction.DENY,
                source=DecisionSource.BUILTIN_GUARD,
                risk_level=RiskLevel.CRITICAL,
                reason="still denied after appeal",
            )
            return ReplayResult(
                original_decision=decision,
                replayed_decision=decision,
                changed=False,
                change_reason="unchanged",
                metadata={"appeal_justification": justification},
            )

        monkeypatch.setattr(replay_module, "replay_with_justification", _deny_replay)

        result = runner.invoke(
            cli.app,
            [
                "appeal",
                "--record-id",
                record_id,
                "--justification",
                "Need access for debugging",
                "--escalate",
            ],
        )

        assert result.exit_code == 0
        assert "Escalation created:" in result.stdout

    def test_appeal_history_command_prints_history(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(tmp_path / "audit"))
        mcp_server.set_config(project_dir=tmp_path, auto_approve=True)

        import asyncio
        from claude_bridge.audit import get_recent_tool_calls

        asyncio.run(mcp_server.run_shell("sudo apt update"))

        record_id = get_recent_tool_calls(limit=1)["records"][0]["record_id"]

        runner.invoke(
            cli.app,
            ["appeal", "--record-id", record_id, "--justification", "Need access for debugging"],
        )

        result = runner.invoke(
            cli.app,
            ["appeal-history", "--record-id", record_id],
        )

        assert result.exit_code == 0
        assert "Appeal History" in result.stdout
        assert "Total appeals:" in result.stdout

    def test_anomaly_scan_command_prints_summary(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(tmp_path / "audit"))
        mcp_server.set_config(project_dir=tmp_path, auto_approve=True)

        import asyncio

        asyncio.run(mcp_server.read_file("missing.txt"))
        asyncio.run(mcp_server.list_directory("."))

        result = runner.invoke(cli.app, ["anomaly", "scan", "--last", "--limit", "10"])

        assert result.exit_code == 0
        assert "Anomaly Scan" in result.stdout
        assert "Records scanned:" in result.stdout
        assert "Overall max score:" in result.stdout
        assert "Runtime policy:" in result.stdout

    def test_anomaly_scan_command_json_output(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(tmp_path / "audit"))
        mcp_server.set_config(project_dir=tmp_path, auto_approve=True)

        import asyncio

        asyncio.run(mcp_server.read_file("missing.txt"))

        result = runner.invoke(cli.app, ["anomaly", "scan", "--last", "--limit", "5", "--json"])

        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert "total_records_scanned" in parsed
        assert "anomaly_scores" in parsed
        assert "mvp_limits" in parsed
        assert parsed["runtime_policy"]["mode"] == "warn_and_log"
        assert parsed["runtime_policy"]["enforced"] is False

    def test_anomaly_baseline_command_writes_project_baseline(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(tmp_path / "audit"))
        mcp_server.set_config(project_dir=tmp_path, auto_approve=True)

        import asyncio

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("print('ok')", encoding="utf-8")
        asyncio.run(mcp_server.read_file("src/app.py"))
        asyncio.run(mcp_server.run_shell("git status"))

        result = runner.invoke(
            cli.app,
            [
                "anomaly",
                "baseline",
                "--project-dir",
                str(tmp_path),
                "--limit",
                "10",
                "--json",
            ],
        )

        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        baseline_path = tmp_path / ".claude-bridge" / "baseline.json"
        assert parsed["ok"] is True
        assert parsed["baseline_path"] == str(baseline_path)
        assert parsed["records_used"] >= 2
        written = json.loads(baseline_path.read_text(encoding="utf-8"))
        assert "read_file" in written["tool_counts"]
        assert "git status" in written["command_prefixes"]
        assert "src" in written["path_roots"]

    def test_audit_export_jsonl_to_stdout(self, monkeypatch, tmp_path: Path):
        """Export audit records in JSONL format to stdout."""
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(tmp_path / "audit"))
        mcp_server.set_config(project_dir=tmp_path, auto_approve=True)

        import asyncio

        (tmp_path / "test.txt").write_text("hello", encoding="utf-8")
        asyncio.run(mcp_server.read_file("test.txt"))

        result = runner.invoke(cli.app, ["audit", "export", "--format", "jsonl"])

        assert result.exit_code == 0
        lines = [line for line in result.stdout.strip().split("\n") if line.strip()]
        assert len(lines) >= 1
        parsed = json.loads(lines[0])
        assert "record_id" in parsed
        assert "timestamp" in parsed
        assert "tool_name" in parsed

    def test_audit_export_summary_json(self, monkeypatch, tmp_path: Path):
        """Export audit records in summary-json format."""
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(tmp_path / "audit"))
        mcp_server.set_config(project_dir=tmp_path, auto_approve=True)

        import asyncio

        (tmp_path / "test.txt").write_text("hello", encoding="utf-8")
        asyncio.run(mcp_server.read_file("test.txt"))

        result = runner.invoke(cli.app, ["audit", "export", "--format", "summary-json"])

        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert "session_id" in parsed
        assert "total_records" in parsed

    def test_audit_export_with_session_option(self, monkeypatch, tmp_path: Path):
        """Export specific session by ID."""
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(tmp_path / "audit"))
        mcp_server.set_config(project_dir=tmp_path, auto_approve=True)
        from claude_bridge.audit import current_session_id

        session_id = current_session_id()

        import asyncio

        (tmp_path / "test.txt").write_text("hello", encoding="utf-8")
        asyncio.run(mcp_server.read_file("test.txt"))

        result = runner.invoke(
            cli.app, ["audit", "export", "--session", session_id, "--format", "jsonl"]
        )

        assert result.exit_code == 0
        assert "record_id" in result.stdout

    def test_audit_export_invalid_session(self, monkeypatch, tmp_path: Path):
        """Export with invalid session ID should fail gracefully."""
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(tmp_path / "audit"))

        result = runner.invoke(
            cli.app,
            ["audit", "export", "--session", "invalid-session-id", "--format", "jsonl"],
        )

        # Should succeed but with empty output (no records found)
        assert result.exit_code == 0

    def test_audit_export_filtered_by_tool(self, monkeypatch, tmp_path: Path):
        """Export with tool name filter."""
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(tmp_path / "audit"))
        mcp_server.set_config(project_dir=tmp_path, auto_approve=True)

        import asyncio

        (tmp_path / "test.txt").write_text("hello", encoding="utf-8")
        asyncio.run(mcp_server.read_file("test.txt"))
        asyncio.run(mcp_server.list_directory("."))

        result = runner.invoke(
            cli.app, ["audit", "export", "--format", "jsonl", "--tool", "read_file"]
        )

        assert result.exit_code == 0
        lines = [line for line in result.stdout.strip().split("\n") if line.strip()]
        for line in lines:
            record = json.loads(line)
            assert record.get("tool_name") == "read_file"

    def test_audit_export_filtered_by_decision(self, monkeypatch, tmp_path: Path):
        """Export with decision filter."""
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(tmp_path / "audit"))
        policy_path = tmp_path / "policy.json"
        policy_path.write_text(
            json.dumps(
                {
                    "rules": [
                        {
                            "name": "deny-blocked",
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
        mcp_server.set_config(project_dir=tmp_path, auto_approve=True)

        import asyncio

        asyncio.run(mcp_server.run_shell("echo blocked"))

        result = runner.invoke(
            cli.app,
            ["audit", "export", "--format", "jsonl", "--decision", "deny"],
        )

        assert result.exit_code == 0
        lines = [line for line in result.stdout.strip().split("\n") if line.strip()]
        assert len(lines) >= 1
        for line in lines:
            record = json.loads(line)
            assert record.get("decision_action") == "deny"

    def test_audit_export_to_file(self, monkeypatch, tmp_path: Path):
        """Export to output file."""
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(tmp_path / "audit"))
        mcp_server.set_config(project_dir=tmp_path, auto_approve=True)
        output_file = tmp_path / "export.jsonl"

        import asyncio

        (tmp_path / "test.txt").write_text("hello", encoding="utf-8")
        asyncio.run(mcp_server.read_file("test.txt"))

        result = runner.invoke(
            cli.app,
            ["audit", "export", "--format", "jsonl", "--output", str(output_file)],
        )

        assert result.exit_code == 0
        assert output_file.exists()
        content = output_file.read_text(encoding="utf-8")
        assert "record_id" in content

    def test_audit_export_invalid_format(self, monkeypatch, tmp_path: Path):
        """Export with invalid format should fail."""
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(tmp_path / "audit"))

        result = runner.invoke(cli.app, ["audit", "export", "--format", "csv"])

        assert result.exit_code == 1
        assert "Invalid format" in result.stdout


class TestConfigCLI:
    def test_config_set_max_parallel(self):
        result = runner.invoke(cli.app, ["config", "set", "max_parallel", "8"])
        assert result.exit_code == 0

    def test_config_describe_max_parallel(self):
        result = runner.invoke(cli.app, ["config", "describe", "max_parallel"])
        assert result.exit_code == 0
        assert "1-32" in result.stdout or "parallel" in result.stdout.lower()

    def test_config_describe_auto_approve_risk_level(self):
        result = runner.invoke(cli.app, ["config", "describe", "auto_approve_risk_level"])
        assert result.exit_code == 0

    def test_root_invocation_no_command(self):
        result = runner.invoke(cli.app, [])
        assert result.exit_code == 0
        assert "Claude Bridge" in result.stdout or "Core" in result.stdout
