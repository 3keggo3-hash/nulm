"""Tests for environment-driven MCP configuration."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from pathlib import Path

from claude_bridge import server as mcp_server


class TestEnvConfiguration:
    def test_configure_from_env_defaults_client_managed_approval_to_disabled(
        self, monkeypatch, tmp_path: Path
    ):
        monkeypatch.setenv("CLAUDE_BRIDGE_PROJECT_DIR", str(tmp_path))
        monkeypatch.delenv("CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL", raising=False)

        mcp_server.configure_from_env()
        current = mcp_server.current_config()

        assert current["client_managed_approval"] is False

    def test_configure_from_env_parses_core_fields(self, monkeypatch, tmp_path: Path):
        extra_root = tmp_path.parent / "extra-root"
        extra_root.mkdir(exist_ok=True)
        monkeypatch.setenv("CLAUDE_BRIDGE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("CLAUDE_BRIDGE_ALLOWED_ROOTS", f"{tmp_path}:{extra_root}")
        monkeypatch.setenv("CLAUDE_BRIDGE_AUTO_APPROVE", "yes")
        monkeypatch.setenv("CLAUDE_BRIDGE_UNSAFE_AUTO_APPROVE_CONFIRMED", "1")
        monkeypatch.setenv("CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL", "off")
        monkeypatch.setenv("CLAUDE_BRIDGE_SHELL_TIMEOUT", "45")

        mcp_server.configure_from_env()
        current = mcp_server.current_config()

        assert current["project_dir"] == tmp_path.resolve()
        assert current["allowed_roots"] == [tmp_path.resolve(), extra_root.resolve()]
        assert current["auto_approve"] is True
        assert current["client_managed_approval"] is False
        assert current["shell_timeout"] == 45

    def test_force_auto_approve_overrides_env(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CLAUDE_BRIDGE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("CLAUDE_BRIDGE_AUTO_APPROVE", "false")
        monkeypatch.setenv("CLAUDE_BRIDGE_UNSAFE_AUTO_APPROVE_CONFIRMED", "1")

        mcp_server.configure_from_env(force_auto_approve=True)
        current = mcp_server.current_config()

        assert current["auto_approve"] is True

    def test_force_auto_approve_requires_second_confirmation(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CLAUDE_BRIDGE_PROJECT_DIR", str(tmp_path))
        monkeypatch.delenv("CLAUDE_BRIDGE_UNSAFE_AUTO_APPROVE_CONFIRMED", raising=False)
        monkeypatch.delenv("CLAUDE_BRIDGE_UNSAFE_NOAPPROVAL_CONFIRMED", raising=False)

        mcp_server.configure_from_env(force_auto_approve=True)
        current = mcp_server.current_config()

        assert current["auto_approve"] is False
        assert current["client_managed_approval"] is True

    def test_invalid_shell_timeout_falls_back_to_default(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CLAUDE_BRIDGE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("CLAUDE_BRIDGE_SHELL_TIMEOUT", "invalid")

        mcp_server.configure_from_env()
        current = mcp_server.current_config()

        assert current["shell_timeout"] == 30

    def test_empty_client_managed_approval_env_stays_disabled(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CLAUDE_BRIDGE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL", "")

        mcp_server.configure_from_env()
        current = mcp_server.current_config()

        assert current["client_managed_approval"] is False

    def test_approval_preset_from_env_overrides_manual_flags(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CLAUDE_BRIDGE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("CLAUDE_BRIDGE_AUTO_APPROVE", "false")
        monkeypatch.setenv("CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL", "false")
        monkeypatch.setenv("CLAUDE_BRIDGE_APPROVAL_PRESET", "power-user")

        mcp_server.configure_from_env()
        current = mcp_server.current_config()

        assert current["approval_preset"] == "power-user"
        assert current["auto_approve"] is True
        assert current["client_managed_approval"] is False

    def test_onboarding_enabled_can_be_disabled_from_env(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CLAUDE_BRIDGE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("CLAUDE_BRIDGE_ONBOARDING_ENABLED", "false")

        mcp_server.configure_from_env()
        current = mcp_server.current_config()

        assert current["onboarding_enabled"] is False

    def test_intent_compaction_can_be_enabled_from_env(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CLAUDE_BRIDGE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("CLAUDE_BRIDGE_INTENT_COMPACTION_ENABLED", "true")

        mcp_server.configure_from_env()
        current = mcp_server.current_config()

        assert current["intent_compaction_enabled"] is True
