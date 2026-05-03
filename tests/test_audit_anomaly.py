"""Tests for anomaly_counts integration in audit session summary."""

from claude_bridge import server as mcp_server
from tests.helpers import parse_payload


class TestAnomalyCountsInAuditSummary:
    """Verify anomaly_counts appears in audit session summary."""

    async def test_session_insights_includes_anomaly_counts(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)

        await mcp_server.list_directory(".")
        await mcp_server.read_file("missing.txt")

        payload = parse_payload(await mcp_server.session_insights(limit=10))
        assert payload["ok"] is True
        details = payload["details"]
        assert "anomaly_counts" in details
        assert isinstance(details["anomaly_counts"], dict)

    async def test_anomaly_counts_with_new_tools(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)

        # Use different tools — each is a "new_tool_use"
        await mcp_server.list_directory(".")
        await mcp_server.read_file("missing.txt")
        target = project / "test.txt"
        target.write_text("hello", encoding="utf-8")
        await mcp_server.read_file("test.txt")

        payload = parse_payload(await mcp_server.session_insights(limit=10))
        assert payload["ok"] is True
        anomaly_counts = payload["details"]["anomaly_counts"]
        # list_directory and read_file are both new tools
        assert anomaly_counts.get("new_tool_use", 0) >= 2

    async def test_empty_session_anomaly_counts(self, temp_audit_project, monkeypatch):
        project, audit_dir = temp_audit_project
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=project, auto_approve=True)

        # No tool calls yet
        payload = parse_payload(await mcp_server.session_insights(limit=10))
        assert payload["ok"] is True
        assert payload["details"]["anomaly_counts"] == {}
