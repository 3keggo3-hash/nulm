"""Tests for config module."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from claude_bridge import config as config_module


def _list_tools_for_profile(tmp_path: Path, profile: str) -> set[str]:
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
        "CLAUDE_BRIDGE_TOOL_PROFILE": profile,
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
    return set(json.loads(result.stdout))


def _list_tools_without_profile(tmp_path: Path) -> set[str]:
    script = (
        "import asyncio, json\n"
        "from claude_bridge import server\n"
        "async def main():\n"
        "    tools = await server.mcp.list_tools()\n"
        "    print(json.dumps(sorted(tool.name for tool in tools)))\n"
        "asyncio.run(main())\n"
    )
    env = {**os.environ, "CLAUDE_BRIDGE_PROJECT_DIR": str(tmp_path)}
    env.pop("CLAUDE_BRIDGE_TOOL_PROFILE", None)

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    return set(json.loads(result.stdout))


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

    async def test_ai_routing_config_has_no_secret_values(self, temp_project):
        config_module.apply_config(
            project_dir=temp_project,
            ai_routing_enabled=True,
            ai_model_profiles={
                "fast": {
                    "provider": "openai",
                    "model": "gpt-test",
                    "api_key_env": "OPENAI_API_KEY",
                    "input_cost_per_mtok": 0.15,
                    "output_cost_per_mtok": 0.60,
                    "quality_tier": "cheap",
                    "max_output_tokens": 400,
                }
            },
        )
        cfg = config_module.current_config()
        assert cfg["ai_routing_enabled"] is True
        assert cfg["ai_model_profiles"]["fast"]["api_key_env"] == "OPENAI_API_KEY"
        assert cfg["ai_model_profiles"]["fast"]["quality_tier"] == "cheap"
        assert cfg["ai_model_profiles"]["fast"]["max_output_tokens"] == 400
        assert "sk-" not in json.dumps(cfg["ai_model_profiles"])


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

    async def test_update_ai_model_profiles_accepts_cost_metadata(self, temp_project):
        result = config_module.update_runtime_config(
            "ai_model_profiles",
            {
                "balanced": {
                    "provider": "openai",
                    "model": "gpt-test",
                    "api_key_env": "OPENAI_API_KEY",
                    "input_cost_per_mtok": 1.25,
                    "output_cost_per_mtok": 5.0,
                    "quality_tier": "balanced",
                    "max_output_tokens": 600,
                }
            },
        )

        profile = result["ai_model_profiles"]["balanced"]

        assert profile["input_cost_per_mtok"] == 1.25
        assert profile["output_cost_per_mtok"] == 5.0
        assert profile["quality_tier"] == "balanced"
        assert profile["max_output_tokens"] == 600


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

    async def test_ai_routing_env_var_reading(self, temp_project, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_PROJECT_DIR", str(temp_project.resolve()))
        monkeypatch.setenv("CLAUDE_BRIDGE_AI_ROUTING_ENABLED", "1")
        monkeypatch.setenv("CLAUDE_BRIDGE_AI_ROUTING_MODE", "rules")
        monkeypatch.setenv("CLAUDE_BRIDGE_AI_DEFAULT_PROFILE", "fast")
        monkeypatch.setenv(
            "CLAUDE_BRIDGE_AI_PROFILES_JSON",
            '{"fast": {"provider": "openai", "model": "gpt-test", '
            '"api_key_env": "OPENAI_API_KEY"}}',
        )
        monkeypatch.setenv(
            "CLAUDE_BRIDGE_AI_ROUTING_RULES_JSON",
            '[{"name": "review", "profile": "fast", "keywords": ["review"]}]',
        )

        config_module.configure_from_env_state()
        cfg = config_module.current_config()

        assert cfg["ai_routing_enabled"] is True
        assert cfg["ai_routing_mode"] == "rules"
        assert cfg["ai_default_model_profile"] == "fast"
        assert cfg["ai_model_profiles"]["fast"]["model"] == "gpt-test"
        assert cfg["ai_routing_rules"][0]["profile"] == "fast"

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
    tool_names = _list_tools_for_profile(tmp_path, "essential")
    assert "read_file" in tool_names
    assert "run_shell" in tool_names
    assert "find_relevant_files" in tool_names
    assert "workspace_status" in tool_names
    assert "nulm_assist" not in tool_names
    assert "run_council_session" not in tool_names
    assert "read_pdf" not in tool_names
    assert "create_plan" not in tool_names
    assert "commit_changes" not in tool_names


def test_standard_tool_profile_registers_documented_workflow_tools(tmp_path):
    tool_names = _list_tools_for_profile(tmp_path, "standard")
    assert "run_workflow" in tool_names
    assert "run_agent_loop_step" in tool_names
    assert "run_agent_loop_session" in tool_names
    assert "list_tasks" in tool_names
    assert "list_pending_approvals" in tool_names
    assert "nulm_assist" in tool_names
    assert "run_council_session" in tool_names
    assert "read_url" in tool_names
    assert "read_pdf" in tool_names
    assert "read_image" in tool_names
    assert "recommend_skills" in tool_names
    assert "inspect_skill_package" in tool_names
    assert "run_skill" not in tool_names
    assert "_run_workflow" not in tool_names


def test_full_tool_profile_registers_experimental_execution_tools(tmp_path):
    tool_names = _list_tools_for_profile(tmp_path, "full")
    assert "run_skill" in tool_names
    assert "run_council_session" in tool_names


def test_missing_tool_profile_env_registers_standard_not_full(tmp_path):
    tool_names = _list_tools_without_profile(tmp_path)
    assert "run_workflow" in tool_names
    assert "read_url" in tool_names
    assert "read_pdf" in tool_names
    assert "create_plan" not in tool_names


def test_tool_profile_union_covers_public_server_exports():
    from claude_bridge import server

    public_tool_exports = {
        name for name, value in vars(server).items() if callable(value) and not name.startswith("_")
    }
    profile_tools = set().union(*config_module.TOOL_GROUPS.values())
    ignored_exports = {
        "approval_mode",
        "Any",
        "FastMCP",
        "Path",
        "ToolAnnotations",
        "active_tool_names",
        "apply_config",
        "clear_index_cache",
        "configure_from_env",
        "configure_from_env_state",
        "current_config",
        "get_last_bridge_change",
        "get_trust_score_impl",
        "git_commit",
        "git_status_snapshot",
        "mcp",
        "raw_ai_evaluator_config",
        "register_file_tools",
        "register_git_tools",
        "register_indexing_tools",
        "register_insights_tools",
        "register_meta_agent_tools",
        "register_meta_tools",
        "register_multi_format_tools",
        "register_prompts",
        "register_shell_tools",
        "register_skill_tools",
        "register_smart_tools",
        "register_url_tools",
        "register_workflow_tools",
        "register_control_plane_tools",
        "register_council_tools",
        "reset_audit_session",
        "reset_onboarding_state",
        "reset_process_sessions",
        "run_mcp_server",
        "send_feedback_impl",
        "send_to_process",
        "set_config",
        "interactive_shell",
        "get_process_status",
        "update_runtime_config",
        "emit_progress_event",
        "get_recent_events",
        "get_stream_capabilities",
        "stream_subscribe",
        "register_notification_tools",
        "register_proposal_tools",
    }

    assert sorted(public_tool_exports - profile_tools - ignored_exports) == []


def test_tools_overview_recommendations_exist_in_standard_profile(tmp_path):
    tool_names = _list_tools_for_profile(tmp_path, "standard")
    assert {"session_insights", "usage_insights", "smart_status"}.issubset(tool_names)


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


class TestAutoApproveRiskLevel:
    async def test_default_risk_level_is_medium(self, temp_project):
        config_module.apply_config(project_dir=temp_project)
        cfg = config_module.current_config()
        assert cfg["auto_approve_risk_level"] == "medium"

    async def test_apply_config_accepts_risk_level(self, temp_project):
        config_module.apply_config(project_dir=temp_project, auto_approve_risk_level="high")
        cfg = config_module.current_config()
        assert cfg["auto_approve_risk_level"] == "high"

    async def test_invalid_risk_level_rejected(self, temp_project):
        with pytest.raises(ValueError, match="auto_approve_risk_level must be one of"):
            config_module.apply_config(project_dir=temp_project, auto_approve_risk_level="invalid")

    async def test_update_runtime_config_risk_level(self, temp_project):
        result = config_module.update_runtime_config("auto_approve_risk_level", "low")
        assert result["auto_approve_risk_level"] == "low"

    async def test_update_runtime_config_invalid_risk_level(self, temp_project):
        with pytest.raises(ValueError, match="auto_approve_risk_level must be one of"):
            config_module.update_runtime_config("auto_approve_risk_level", "critical")


class TestShouldAutoApproveRisk:
    def test_none_never_auto_approves(self):
        config_module._CONFIG["auto_approve_risk_level"] = "none"
        config_module._CONFIG["auto_approve"] = True
        config_module._CONFIG["client_managed_approval"] = False
        assert config_module.should_auto_approve_risk("low") is False
        assert config_module.should_auto_approve_risk("medium") is False
        assert config_module.should_auto_approve_risk("high") is False

    def test_low_only_auto_approves_low(self):
        config_module._CONFIG["auto_approve_risk_level"] = "low"
        config_module._CONFIG["auto_approve"] = True
        config_module._CONFIG["client_managed_approval"] = False
        assert config_module.should_auto_approve_risk("low") is True
        assert config_module.should_auto_approve_risk("medium") is False
        assert config_module.should_auto_approve_risk("high") is False

    def test_medium_auto_approves_low_and_medium(self):
        config_module._CONFIG["auto_approve_risk_level"] = "medium"
        config_module._CONFIG["auto_approve"] = True
        config_module._CONFIG["client_managed_approval"] = False
        assert config_module.should_auto_approve_risk("low") is True
        assert config_module.should_auto_approve_risk("medium") is True
        assert config_module.should_auto_approve_risk("high") is False

    def test_high_auto_approves_low_medium_and_high(self):
        config_module._CONFIG["auto_approve_risk_level"] = "high"
        config_module._CONFIG["auto_approve"] = True
        config_module._CONFIG["client_managed_approval"] = False
        assert config_module.should_auto_approve_risk("low") is True
        assert config_module.should_auto_approve_risk("medium") is True
        assert config_module.should_auto_approve_risk("high") is True
        assert config_module.should_auto_approve_risk("critical") is False
