"""Tests for MCP system prompt and setup guide."""

from pathlib import Path

from claude_bridge.prompt import SYSTEM_PROMPT, generate_mcp_setup_guide


class TestSystemPrompt:
    """Test MCP system prompt content."""

    def test_prompt_contains_tool_names(self):
        assert "read_file" in SYSTEM_PROMPT
        assert "list_directory" in SYSTEM_PROMPT
        assert "run_shell" in SYSTEM_PROMPT
        assert "patch_file" in SYSTEM_PROMPT

    def test_prompt_contains_search_replace(self):
        assert "SEARCH" in SYSTEM_PROMPT
        assert "REPLACE" in SYSTEM_PROMPT

    def test_prompt_emphasizes_no_full_rewrite(self):
        prompt_lower = SYSTEM_PROMPT.lower()
        assert "never" in prompt_lower
        assert "write full files" in prompt_lower or "patch_file" in prompt_lower

    def test_prompt_mentions_mcp(self):
        assert "MCP" in SYSTEM_PROMPT

    def test_prompt_mentions_approval(self):
        assert "approval" in SYSTEM_PROMPT.lower() or "confirm" in SYSTEM_PROMPT.lower()

    def test_prompt_mentions_path_recovery_flow(self):
        prompt_lower = SYSTEM_PROMPT.lower()
        assert "path_outside_project" in prompt_lower
        assert "workspace_status()" in SYSTEM_PROMPT
        assert "switch_project_root(path)" in SYSTEM_PROMPT


class TestMCPSetupGuide:
    """Test MCP setup guide content."""

    def _guide(self, tmp_path: Path) -> str:
        return generate_mcp_setup_guide(tmp_path)

    def test_guide_contains_json_config(self, tmp_path: Path):
        guide = self._guide(tmp_path)
        assert "mcpServers" in guide
        assert "claude-bridge" in guide

    def test_guide_contains_command(self, tmp_path: Path):
        guide = self._guide(tmp_path)
        assert "claude-bridge" in guide
        assert "claude_bridge.mcp_server" in guide

    def test_guide_contains_config_paths(self, tmp_path: Path):
        guide = self._guide(tmp_path)
        assert "claude_desktop_config.json" in guide

    def test_guide_is_non_empty(self, tmp_path: Path):
        guide = self._guide(tmp_path)
        assert len(guide) > 200
