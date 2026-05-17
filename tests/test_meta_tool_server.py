"""Tests for meta/configuration MCP tools."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


import json

from claude_bridge import server as mcp_server
from claude_bridge.meta_tool_server import _autocomplete_suggestions


class TestAdviseNextStep:
    async def test_advise_next_step_returns_agent_advice(self, temp_project):
        payload = json.loads(
            await mcp_server.advise_next_step(
                "Make this project public ready",
                target=".",
            )
        )

        assert payload["ok"] is True
        details = payload["details"]
        assert details["schema_version"] == "agent_advice.v1"
        assert "release-readiness" in details["recommended_next_step"]
        assert "README.md" in details["needed_context"]
        assert details["should_ask_user"] is False

    async def test_advise_next_step_rejects_invalid_context_json(self, temp_project):
        payload = json.loads(
            await mcp_server.advise_next_step(
                "Improve quality",
                recent_context_json="[]",
            )
        )

        assert payload["ok"] is False
        assert payload["code"] == "invalid_advisor_context"


class TestAgentQualityTools:
    async def test_improve_request_returns_scoped_prompt(self, temp_project):
        payload = json.loads(
            await mcp_server.improve_request(
                "Make this code professional",
                target="src/claude_bridge/server.py",
            )
        )

        assert payload["ok"] is True
        details = payload["details"]
        assert details["schema_version"] == "improved_request.v1"
        assert "smallest safe implementation slice" in details["improved_prompt"]

    async def test_plan_quality_review_flags_missing_validation(self, temp_project):
        payload = json.loads(
            await mcp_server.plan_quality_review(
                "Read the entire codebase and refactor everything.",
                goal="Improve quality",
            )
        )

        assert payload["ok"] is True
        details = payload["details"]
        assert details["schema_version"] == "plan_quality_review.v1"
        assert details["verdict"] == "revise"
        assert details["missing_tests"]

    async def test_plan_quality_review_rejects_invalid_context_json(self, temp_project):
        payload = json.loads(
            await mcp_server.plan_quality_review(
                "Inspect target and run pytest.",
                recent_context_json="[]",
            )
        )

        assert payload["ok"] is False
        assert payload["code"] == "invalid_advisor_context"

    async def test_suggest_bridge_config_returns_safe_config_suggestions(self, temp_project):
        payload = json.loads(await mcp_server.suggest_bridge_config("Token usage is too high"))

        assert payload["ok"] is True
        details = payload["details"]
        assert details["schema_version"] == "bridge_config_suggestions.v1"
        assert "ai_evaluator_api_key" in details["restricted_keys"]
        assert details["suggestions"]

    async def test_review_result_quality_returns_quality_review(self, temp_project):
        payload = json.loads(
            await mcp_server.review_result_quality(
                "Add review_result_quality MCP tool",
                "Added deterministic review logic and ran pytest.",
                changed_files_json=json.dumps(
                    {
                        "files": [
                            "src/claude_bridge/agent_advisor.py",
                            "src/claude_bridge/meta_tool_server.py",
                            "docs/roadmap.md",
                        ]
                    }
                ),
                validation_json=json.dumps({"commands": ["pytest tests/test_agent_advisor.py"]}),
                self_critique_json=json.dumps(
                    {"ok": True, "details": {"summary": {"total_issues": 0}}}
                ),
            )
        )

        assert payload["ok"] is True
        details = payload["details"]
        assert details["schema_version"] == "result_quality_review.v1"
        assert details["verdict"] == "pass_with_notes"
        assert details["goal_alignment"]
        assert any("self_critique" in item for item in details["strengths"])

    async def test_review_result_quality_rejects_invalid_json(self, temp_project):
        payload = json.loads(
            await mcp_server.review_result_quality(
                "Add review_result_quality MCP tool",
                "Added deterministic review logic.",
                validation_json="[]",
            )
        )

        assert payload["ok"] is False
        assert payload["code"] == "invalid_advisor_context"

    async def test_review_result_quality_rejects_invalid_changed_files(self, temp_project):
        payload = json.loads(
            await mcp_server.review_result_quality(
                "Add review_result_quality MCP tool",
                "Added deterministic review logic.",
                changed_files_json=json.dumps({"files": "src/claude_bridge/agent_advisor.py"}),
            )
        )

        assert payload["ok"] is False
        assert payload["code"] == "invalid_advisor_context"

    async def test_review_result_quality_rejects_invalid_self_critique_json(self, temp_project):
        payload = json.loads(
            await mcp_server.review_result_quality(
                "Add review_result_quality MCP tool",
                "Added deterministic review logic.",
                self_critique_json="[]",
            )
        )

        assert payload["ok"] is False
        assert payload["code"] == "invalid_advisor_context"

    async def test_apply_bridge_config_change_updates_safe_key(self, temp_project):
        payload = json.loads(
            await mcp_server.apply_bridge_config_change("intent_compaction_enabled", True)
        )

        assert payload["ok"] is True
        assert payload["details"]["key"] == "intent_compaction_enabled"
        assert payload["details"]["previous_value"] is False
        assert payload["details"]["new_value"] is True
        assert "rollback_hint" in payload["details"]

    async def test_apply_bridge_config_change_rejects_secret_key(self, temp_project):
        payload = json.loads(
            await mcp_server.apply_bridge_config_change("ai_evaluator_api_key", "secret")
        )

        assert payload["ok"] is False
        assert payload["code"] == "unsafe_config_change"


class TestGetRecentToolCalls:
    async def test_get_recent_tool_calls_no_filters(self, temp_project):
        payload = json.loads(await mcp_server.get_recent_tool_calls(limit=5))
        assert payload["ok"] is True
        assert "session_id" in payload["details"]
        assert "records" in payload["details"]
        assert isinstance(payload["details"]["records"], list)

    async def test_get_recent_tool_calls_filter_by_tool_name(self, temp_project):
        mcp_server.set_config(project_dir=temp_project)
        await mcp_server.workspace_status()
        payload = json.loads(
            await mcp_server.get_recent_tool_calls(limit=10, tool_name="workspace_status")
        )
        assert payload["ok"] is True
        assert len(payload["details"]["records"]) >= 1
        for record in payload["details"]["records"]:
            assert record["tool_name"] == "workspace_status"

    async def test_get_recent_tool_calls_filter_by_ok_false(self, temp_project):
        payload = json.loads(await mcp_server.get_recent_tool_calls(limit=10, ok=False))
        assert payload["ok"] is True
        for record in payload["details"]["records"]:
            assert record.get("ok") is False

    async def test_get_recent_tool_calls_respects_limit(self, temp_project):
        for _ in range(3):
            await mcp_server.workspace_status()
        payload = json.loads(await mcp_server.get_recent_tool_calls(limit=2))
        assert payload["ok"] is True
        assert len(payload["details"]["records"]) <= 2


class TestSessionInsights:
    async def test_session_insights_returns_summary(self, temp_project):
        await mcp_server.bridge_status()
        payload = json.loads(await mcp_server.session_insights(limit=10))
        assert payload["ok"] is True
        assert "session_id" in payload["details"]
        assert "total_records" in payload["details"]
        assert "failure_count" in payload["details"]


class TestBridgeStatus:
    async def test_bridge_status_returns_project_and_approval(self, temp_project):
        payload = json.loads(await mcp_server.bridge_status())
        assert payload["ok"] is True
        details = payload["details"]
        assert str(temp_project) in details["active_project_dir"]
        assert "allowed_roots" in details
        assert "auto_approve" in details
        assert "context_budget_profile" in details
        assert details["skill_governance"]["registered_count"] >= 0
        assert details["skill_governance"]["source_visibility"] == "metadata_only"
        assert details["ai_evaluator"]["latency"]["sample_count"] >= 0

    async def test_bridge_status_includes_smart_features(self, temp_project):
        payload = json.loads(await mcp_server.bridge_status())
        assert payload["ok"] is True
        assert "smart_features" in payload["details"]

    async def test_bridge_status_includes_agent_quality_telemetry(self, temp_project):
        payload = json.loads(await mcp_server.bridge_status())
        assert payload["ok"] is True
        assert payload["details"]["summary"]
        assert payload["details"]["next_best_actions"]
        readiness = payload["details"]["readiness"]
        assert readiness["ready_to_read"] is True
        assert "approval" in readiness["approval_mode_explained"].lower()
        assert readiness["first_safe_prompt"]
        agent_quality = payload["details"]["agent_quality"]
        assert "advise_next_step" in agent_quality["available_tools"]["planning"]
        assert "review_result_quality" in agent_quality["available_tools"]["workflow_result_review"]
        assert agent_quality["telemetry"]["sample_count"] >= 0
        assert agent_quality["safe_config_mutation"]["only_via"] == "apply_bridge_config_change"


class TestToolsOverview:
    async def test_tools_overview_groups_agent_quality_tools(self, temp_project):
        payload = json.loads(await mcp_server.tools_overview())
        assert payload["ok"] is True
        assert payload["details"]["recommended_starters"]
        assert payload["details"]["recommended_starters"][0]["intent"] == "public_ready_check"
        agent_quality = payload["details"]["groups"]["agent_quality"]
        assert "improve_request" in agent_quality["planning"]
        assert "suggest_bridge_config" in agent_quality["config"]
        assert "review_result_quality" in agent_quality["workflow_result_review"]


class TestAppealDecision:
    async def test_appeal_invalid_record_id_returns_error(self, temp_project):
        payload = json.loads(
            await mcp_server.appeal_decision("nonexistent-record-id", "please reconsider")
        )
        assert payload["ok"] is False
        assert payload["code"] == "appeal_failed"


class TestGetConfig:
    async def test_get_config_returns_config_dict(self, temp_project):
        payload = json.loads(await mcp_server.get_config())
        assert payload["ok"] is True
        details = payload["details"]
        assert "project_dir" in details
        assert "allowed_roots" in details
        assert "editable_keys" in details
        assert "shell_timeout" in details["editable_keys"]
        assert "auto_approve" not in details["editable_keys"]


class TestSetConfigValue:
    async def test_set_config_value_updates_shell_timeout(self, temp_project):
        payload = json.loads(await mcp_server.set_config_value("shell_timeout", 60))
        assert payload["ok"] is True
        assert payload["details"]["shell_timeout"] == 60

    async def test_set_config_value_rejects_auto_approve(self, temp_project):
        payload = json.loads(await mcp_server.set_config_value("auto_approve", True))
        assert payload["ok"] is False
        assert payload["code"] == "invalid_config_value"

    async def test_set_config_value_rejects_approval_and_remote_ai_keys(self, temp_project):
        for key, value in [
            ("approval_preset", "dev-safe"),
            ("client_managed_approval", True),
            ("ai_evaluator_enabled", True),
            ("ai_evaluator_provider", "openai"),
            ("ai_evaluator_model", "gpt-4o-mini"),
            ("ai_evaluator_fallback_action", "ask"),
        ]:
            payload = json.loads(await mcp_server.set_config_value(key, value))
            assert payload["ok"] is False
            assert payload["code"] == "invalid_config_value"


class TestWorkspaceStatus:
    async def test_workspace_status_returns_project_root(self, temp_project):
        payload = json.loads(await mcp_server.workspace_status())
        assert payload["ok"] is True
        details = payload["details"]
        assert str(temp_project) in details["active_project_dir"]
        assert "allowed_roots" in details

    async def test_workspace_status_includes_root_rules(self, temp_project):
        payload = json.loads(await mcp_server.workspace_status())
        assert payload["ok"] is True
        assert "root_rules" in payload["details"]
        assert payload["details"]["root_rules"]["can_switch_to_subdirectories"] is True


class TestAutocompleteSuggestions:
    def test_rejects_path_traversal(self, tmp_path):
        (tmp_path / "safe.txt").write_text("safe")
        result = _autocomplete_suggestions(
            "../../etc",
            project_dir=lambda: tmp_path,
        )
        assert not any("etc" in s["text"] for s in result["suggestions"])

    def test_rejects_context_path_traversal(self, tmp_path):
        (tmp_path / "safe.txt").write_text("safe")
        result = _autocomplete_suggestions(
            "",
            project_dir=lambda: tmp_path,
            context="../../etc",
        )
        assert not any("etc" in s["text"] for s in result["suggestions"])
