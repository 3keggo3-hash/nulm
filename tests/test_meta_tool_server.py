"""Tests for meta/configuration MCP tools."""

import json

from claude_bridge import server as mcp_server


class TestGetRecentToolCalls:
    async def test_get_recent_tool_calls_no_filters(self, temp_project):
        payload = json.loads(await mcp_server.get_recent_tool_calls(limit=5))
        assert payload["ok"] is True
        assert "session_id" in payload["details"]
        assert "records" in payload["details"]
        assert isinstance(payload["details"]["records"], list)

    async def test_get_recent_tool_calls_filter_by_tool_name(self, temp_project):
        await mcp_server.workspace_status()
        payload = json.loads(await mcp_server.get_recent_tool_calls(
            limit=10, tool_name="workspace_status"
        ))
        assert payload["ok"] is True
        assert len(payload["details"]["records"]) >= 1
        for record in payload["details"]["records"]:
            assert record["tool_name"] == "workspace_status"

    async def test_get_recent_tool_calls_filter_by_ok_false(self, temp_project):
        payload = json.loads(await mcp_server.get_recent_tool_calls(
            limit=10, ok=False
        ))
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

    async def test_bridge_status_includes_smart_features(self, temp_project):
        payload = json.loads(await mcp_server.bridge_status())
        assert payload["ok"] is True
        assert "smart_features" in payload["details"]


class TestAppealDecision:
    async def test_appeal_invalid_record_id_returns_error(self, temp_project):
        payload = json.loads(await mcp_server.appeal_decision(
            "nonexistent-record-id", "please reconsider"
        ))
        assert payload["ok"] is False
        assert payload["code"] == "appeal_failed"


class TestGetConfig:
    async def test_get_config_returns_config_dict(self, temp_project):
        payload = json.loads(await mcp_server.get_config())
        assert payload["ok"] is True
        details = payload["details"]
        assert "project_dir" in details
        assert "allowed_roots" in details
        assert "approval_presets" in details
        assert "editable_keys" in details
        assert "shell_timeout" in details["editable_keys"]


class TestSetConfigValue:
    async def test_set_config_value_updates_shell_timeout(self, temp_project):
        payload = json.loads(await mcp_server.set_config_value(
            "shell_timeout", 60
        ))
        assert payload["ok"] is True
        assert payload["details"]["shell_timeout"] == 60


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
