"""Tests for CLI setup and desktop integration helpers."""

import json
from pathlib import Path

from typer.testing import CliRunner

from claude_bridge import cli
from claude_bridge.prompt import build_desktop_config, build_target_config, generate_mcp_setup_guide
from claude_bridge import server as mcp_server

runner = CliRunner()


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
            f"{tmp_path.resolve()}:{extra_root.resolve()}"
        )
        assert server["env"]["CLAUDE_BRIDGE_AUTO_APPROVE"] == "1"
        assert server["env"]["CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL"] == "0"
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

    def test_build_desktop_config_includes_approval_preset_when_requested(self, tmp_path: Path):
        config = build_desktop_config(
            tmp_path,
            python_executable="/usr/bin/python3",
            package_root=Path("/tmp/fake-project"),
            approval_preset="dev-safe",
        )

        server = config["mcpServers"]["claude-bridge"]
        assert server["env"]["CLAUDE_BRIDGE_APPROVAL_PRESET"] == "dev-safe"

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
        observed: dict[str, object] = {}

        def fake_run(*, transport: str = "stdio") -> None:
            observed["transport"] = transport

        monkeypatch.setattr(cli.mcp, "run", fake_run)

        result = runner.invoke(cli.app, ["start", "--project-dir", str(tmp_path)])

        assert result.exit_code == 0
        assert result.stdout == ""
        assert observed["transport"] == "stdio"

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
            ],
        )

        assert result.exit_code == 0
        assert "installed for Claude Desktop" in result.stdout
        written = json.loads(config_path.read_text(encoding="utf-8"))
        server = written["mcpServers"]["claude-bridge"]
        assert server["args"] == ["-m", "claude_bridge.mcp_server"]
        assert server["env"]["CLAUDE_BRIDGE_PROJECT_DIR"] == str(project_dir.resolve())
        assert server["env"]["CLAUDE_BRIDGE_ALLOWED_ROOTS"] == (
            f"{project_dir.resolve()}:{extra_root.resolve()}"
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
            ["install", "--project-dir", str(project_dir), "--target", "vscode"],
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
            ["install", "--project-dir", str(project_dir), "--config-path", str(config_path)],
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
            ["install", "--project-dir", str(project_dir), "--config-path", str(config_path)],
        )

        assert result.exit_code == 1
        assert "Install failed" in result.stdout

    def test_configure_from_env_applies_project_dir(self, monkeypatch, tmp_path: Path):
        extra_root = tmp_path.parent / "extra-root"
        extra_root.mkdir(exist_ok=True)
        monkeypatch.setenv("CLAUDE_BRIDGE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("CLAUDE_BRIDGE_ALLOWED_ROOTS", f"{tmp_path}:{extra_root}")
        monkeypatch.setenv("CLAUDE_BRIDGE_AUTO_APPROVE", "true")
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

        result = runner.invoke(cli.app, ["audit", "--last", "--limit", "5"])

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

    def test_replay_command_prints_human_readable_result(
        self, monkeypatch, tmp_path: Path
    ):
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
