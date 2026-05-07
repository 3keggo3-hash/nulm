"""Tests for config module."""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from claude_bridge import config as config_module


class TestApplyConfig:
    async def test_apply_config_valid(self, temp_project):
        config_module.apply_config(
            project_dir=temp_project,
            shell_timeout=60,
            context_budget_profile="low-cost",
            auto_approve=True,
        )
        cfg = config_module.current_config()
        assert cfg["shell_timeout"] == 60
        assert cfg["context_budget_profile"] == "low-cost"
        assert cfg["auto_approve"] is True
        assert cfg["project_dir"] == temp_project.resolve()

    async def test_invalid_shell_timeout_rejected(self, temp_project):
        with pytest.raises(ValueError, match="shell_timeout must be a positive integer"):
            config_module.apply_config(project_dir=temp_project, shell_timeout=0)

    async def test_invalid_budget_profile_rejected(self, temp_project):
        with pytest.raises(ValueError, match="Unknown context budget profile"):
            config_module.apply_config(project_dir=temp_project, context_budget_profile="bogus")

    async def test_budget_profile_validation(self, temp_project):
        for profile in ("low-cost", "balanced", "deep"):
            config_module.apply_config(project_dir=temp_project, context_budget_profile=profile)
            assert config_module.current_config()["context_budget_profile"] == profile


class TestResolveApprovalMode:
    def test_read_only(self):
        auto, client, preset = config_module.resolve_approval_mode(approval_preset="read-only")
        assert (auto, client, preset) == (False, False, "read-only")

    def test_dev_safe(self):
        auto, client, preset = config_module.resolve_approval_mode(approval_preset="dev-safe")
        assert (auto, client, preset) == (False, True, "dev-safe")

    def test_ci_like(self):
        auto, client, preset = config_module.resolve_approval_mode(approval_preset="ci-like")
        assert (auto, client, preset) == (False, True, "ci-like")

    def test_power_user(self):
        auto, client, preset = config_module.resolve_approval_mode(approval_preset="power-user")
        assert (auto, client, preset) == (True, False, "power-user")

    def test_explicit_flags_no_preset(self):
        auto, client, preset = config_module.resolve_approval_mode(
            auto_approve=True, client_managed_approval=True
        )
        assert (auto, client, preset) == (True, True, None)

    def test_unknown_preset_raises(self):
        with pytest.raises(ValueError, match="Unknown approval preset"):
            config_module.resolve_approval_mode(approval_preset="made-up")


class TestCurrentConfig:
    async def test_thread_safety(self, temp_project):
        errors = []

        def read_config():
            try:
                for _ in range(50):
                    cfg = config_module.current_config()
                    assert "project_dir" in cfg
                    assert "shell_timeout" in cfg
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=read_config) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0

    async def test_api_key_redacted(self, temp_project):
        config_module.apply_config(
            project_dir=temp_project,
            ai_evaluator_api_key="secret123",
        )
        cfg = config_module.current_config()
        assert cfg["ai_evaluator_api_key"] == "[REDACTED]"

    async def test_empty_api_key_not_redacted(self, temp_project):
        config_module.apply_config(
            project_dir=temp_project,
            ai_evaluator_api_key="",
        )
        cfg = config_module.current_config()
        assert cfg["ai_evaluator_api_key"] == ""


class TestUpdateRuntimeConfig:
    async def test_update_shell_timeout(self, temp_project):
        result = config_module.update_runtime_config("shell_timeout", 45)
        assert result["shell_timeout"] == 45

    async def test_update_auto_approve(self, temp_project):
        result = config_module.update_runtime_config("auto_approve", True)
        assert result["auto_approve"] is True

    async def test_update_approval_preset(self, temp_project):
        result = config_module.update_runtime_config("approval_preset", "power-user")
        assert result["auto_approve"] is True
        assert result["client_managed_approval"] is False
        assert result["approval_preset"] == "power-user"

    async def test_invalid_key_raises(self, temp_project):
        with pytest.raises(ValueError, match="Unsupported config key"):
            config_module.update_runtime_config("nope", 42)

    async def test_invalid_shell_timeout_raises(self, temp_project):
        with pytest.raises(ValueError, match="shell_timeout must be a positive integer"):
            config_module.update_runtime_config("shell_timeout", -1)

    async def test_ai_api_key_cannot_be_set_at_runtime(self, temp_project):
        with pytest.raises(ValueError, match="cannot be set via MCP tool"):
            config_module.update_runtime_config("ai_evaluator_api_key", "sk-test")

    async def test_ai_fallback_allow_rejected_at_runtime(self, temp_project):
        with pytest.raises(ValueError, match="must be one of deny/ask"):
            config_module.update_runtime_config("ai_evaluator_fallback_action", "allow")


class TestConfigureFromEnvState:
    async def test_env_var_reading(self, temp_project, monkeypatch):
        env_dir = str(temp_project.resolve())
        monkeypatch.setenv("CLAUDE_BRIDGE_PROJECT_DIR", env_dir)
        monkeypatch.setenv("CLAUDE_BRIDGE_SHELL_TIMEOUT", "90")
        monkeypatch.setenv("CLAUDE_BRIDGE_AUTO_APPROVE", "1")
        monkeypatch.setenv("CLAUDE_BRIDGE_UNSAFE_AUTO_APPROVE_CONFIRMED", "1")
        monkeypatch.setenv("CLAUDE_BRIDGE_CONTEXT_BUDGET_PROFILE", "deep")

        config_module.configure_from_env_state()
        cfg = config_module.current_config()

        assert cfg["project_dir"] == temp_project.resolve()
        assert cfg["shell_timeout"] == 90
        assert cfg["auto_approve"] is True
        assert cfg["context_budget_profile"] == "deep"

    async def test_auto_approve_requires_second_env_confirmation(self, temp_project, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_PROJECT_DIR", str(temp_project.resolve()))
        monkeypatch.setenv("CLAUDE_BRIDGE_AUTO_APPROVE", "1")
        monkeypatch.delenv("CLAUDE_BRIDGE_UNSAFE_AUTO_APPROVE_CONFIRMED", raising=False)
        monkeypatch.delenv("CLAUDE_BRIDGE_UNSAFE_NOAPPROVAL_CONFIRMED", raising=False)

        config_module.configure_from_env_state()
        cfg = config_module.current_config()

        assert cfg["auto_approve"] is False
        assert cfg["client_managed_approval"] is True


class TestConfigGetters:
    async def test_project_dir(self, temp_project):
        assert config_module.project_dir() == temp_project.resolve()

    async def test_allowed_roots(self, temp_project):
        roots = config_module.allowed_roots()
        assert temp_project.resolve() in roots

    async def test_shell_timeout(self, temp_project):
        assert config_module.shell_timeout() == 30

    async def test_approval_mode(self, temp_project):
        auto, client = config_module.approval_mode()
        assert auto is True
        assert client is False


def test_tool_profile_filters_registered_mcp_tools(tmp_path):
    script = (
        "import asyncio, json\n"
        "from claude_bridge import server\n"
        "async def main():\n"
        "    tools = await server.mcp.list_tools()\n"
        "    print(json.dumps(sorted(tool.name for tool in tools)))\n"
        "asyncio.run(main())\n"
    )
    env = {
        **os.environ,
        "CLAUDE_BRIDGE_TOOL_PROFILE": "essential",
        "CLAUDE_BRIDGE_PROJECT_DIR": str(tmp_path),
    }

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    tool_names = set(json.loads(result.stdout))
    assert "read_file" in tool_names
    assert "run_shell" in tool_names
    assert "find_relevant_files" in tool_names
    assert "workspace_status" in tool_names
    assert "read_pdf" not in tool_names
    assert "create_plan" not in tool_names
    assert "commit_changes" not in tool_names


def test_essential_tool_profile_avoids_heavy_server_imports(tmp_path):
    script = (
        "import json, sys\n"
        "from claude_bridge import server\n"
        "print(json.dumps({\n"
        "    name: name in sys.modules\n"
        "    for name in (\n"
        "        'claude_bridge.indexing',\n"
        "        'claude_bridge.relevance',\n"
        "        'claude_bridge.smart',\n"
        "        'claude_bridge.workflow_tools',\n"
        "        'claude_bridge.insights',\n"
        "    )\n"
        "}))\n"
    )
    env = {
        **os.environ,
        "CLAUDE_BRIDGE_TOOL_PROFILE": "essential",
        "CLAUDE_BRIDGE_PROJECT_DIR": str(tmp_path),
    }

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    loaded_modules = json.loads(result.stdout)
    assert loaded_modules == {
        "claude_bridge.indexing": False,
        "claude_bridge.relevance": False,
        "claude_bridge.smart": False,
        "claude_bridge.workflow_tools": False,
        "claude_bridge.insights": False,
    }
