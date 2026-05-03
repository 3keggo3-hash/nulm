"""Tests for MCP prompt registration and rendering."""

from claude_bridge import server as mcp_server


class TestPrompts:
    async def test_core_prompts_are_listed(self):
        prompts = await mcp_server.mcp.list_prompts()
        names = [prompt.name for prompt in prompts]

        assert "review" in names
        assert "compact" in names
        assert "optimize" in names
        assert "orchestrate" in names
        assert "agent_loop" in names
        assert "quality" in names
        assert "test" in names
        assert "todo" in names
        assert "explain" in names
        assert "commit" in names
        assert "shadow" in names
        assert "benchmark" in names
        assert "platform" in names
        assert "refactor" in names
        assert "debug" in names
        assert "document" in names
        assert "security" in names

    async def test_review_prompt_renders_target_path(self):
        result = await mcp_server.mcp.get_prompt(
            "review",
            {"target": "src/", "focus": "bugs and missing tests"},
        )

        assert result.messages
        message_text = result.messages[0].content.text
        assert "Target: src/" in message_text
        assert "Focus: bugs and missing tests" in message_text

    async def test_review_prompt_accepts_language(self):
        result = await mcp_server.mcp.get_prompt(
            "review",
            {"target": "src/", "focus": "bugs", "language": "English"},
        )

        message_text = result.messages[0].content.text
        assert "Response language: English" in message_text

    async def test_optimize_prompt_renders_focus(self):
        result = await mcp_server.mcp.get_prompt(
            "optimize",
            {"target": "src/", "focus": "performance and readability"},
        )

        message_text = result.messages[0].content.text
        assert "Target: src/" in message_text
        assert "Focus: performance and readability" in message_text

    async def test_test_prompt_renders_style(self):
        result = await mcp_server.mcp.get_prompt(
            "test",
            {"target": "tests/", "test_style": "regression tests"},
        )

        message_text = result.messages[0].content.text
        assert "Target: tests/" in message_text
        assert "Preferred test style: regression tests" in message_text

    async def test_quality_prompt_renders_focus(self):
        result = await mcp_server.mcp.get_prompt(
            "quality",
            {"target": "src/", "focus": "correctness and regression safety"},
        )

        message_text = result.messages[0].content.text
        assert "Target: src/" in message_text
        assert "Focus: correctness and regression safety" in message_text
        assert "Cross-check related implementation" in message_text

    async def test_orchestrate_prompt_renders_focus(self):
        result = await mcp_server.mcp.get_prompt(
            "orchestrate",
            {"target": "src/", "focus": "split by modules and define integration gates"},
        )

        message_text = result.messages[0].content.text
        assert "Target: src/" in message_text
        assert "Focus: split by modules and define integration gates" in message_text
        assert "parallelizable tracks" in message_text

    async def test_agent_loop_prompt_renders_goal(self):
        result = await mcp_server.mcp.get_prompt(
            "agent_loop",
            {"target": "src/", "goal": "fix the failing behavior with bounded iterations"},
        )

        message_text = result.messages[0].content.text
        assert "Target: src/" in message_text
        assert "Goal: fix the failing behavior with bounded iterations" in message_text
        assert "iteration cap" in message_text

    async def test_todo_prompt_has_defaults(self):
        result = await mcp_server.mcp.get_prompt("todo")

        message_text = result.messages[0].content.text
        assert "Target: ." in message_text
        assert "Keywords to scan: TODO, FIXME, HACK, XXX" in message_text

    async def test_explain_prompt_renders_audience_and_language(self):
        result = await mcp_server.mcp.get_prompt(
            "explain",
            {
                "target": "src/claude_bridge/server.py",
                "audience": "a junior Python developer",
                "language": "English",
            },
        )

        message_text = result.messages[0].content.text
        assert "Target: src/claude_bridge/server.py" in message_text
        assert "Audience: a junior Python developer" in message_text
        assert "Response language: English" in message_text

    async def test_commit_prompt_has_defaults(self):
        result = await mcp_server.mcp.get_prompt("commit")

        message_text = result.messages[0].content.text
        assert "Target: ." in message_text
        assert (
            "Preferred style: short imperative commit message with a concise summary"
            in message_text
        )

    async def test_shadow_prompt_pushes_critical_reread(self):
        result = await mcp_server.mcp.get_prompt(
            "shadow",
            {"target": "src/", "focus": "challenge prior assumptions"},
        )

        message_text = result.messages[0].content.text
        assert "Target: src/" in message_text
        assert "Focus: challenge prior assumptions" in message_text
        assert "critical reread" in message_text

    async def test_platform_prompt_targets_cross_platform_risks(self):
        result = await mcp_server.mcp.get_prompt("platform")

        message_text = result.messages[0].content.text
        assert "Linux, Windows, WSL, VS Code" in message_text
        assert "path issues" in message_text

    async def test_compact_prompt_targets_lower_cost_context(self):
        result = await mcp_server.mcp.get_prompt(
            "compact",
            {"target": "src/", "goal": "continue with lower token cost"},
        )

        message_text = result.messages[0].content.text
        assert "Target: src/" in message_text
        assert "Goal: continue with lower token cost" in message_text
        assert "smallest useful set of files" in message_text

    async def test_compact_prompt_accepts_language(self):
        result = await mcp_server.mcp.get_prompt(
            "compact",
            {"target": "src/", "goal": "shrink", "language": "English"},
        )

        message_text = result.messages[0].content.text
        assert "Response language: English" in message_text

    async def test_refactor_prompt_renders_focus(self):
        result = await mcp_server.mcp.get_prompt(
            "refactor",
            {"target": "src/", "focus": "reduce duplication"},
        )

        message_text = result.messages[0].content.text
        assert "Target: src/" in message_text
        assert "Focus: reduce duplication" in message_text
        assert "structural issues" in message_text

    async def test_debug_prompt_renders_focus(self):
        result = await mcp_server.mcp.get_prompt(
            "debug",
            {"target": "src/", "focus": "trace failing code path"},
        )

        message_text = result.messages[0].content.text
        assert "Target: src/" in message_text
        assert "Focus: trace failing code path" in message_text
        assert "root cause" in message_text

    async def test_document_prompt_renders_style(self):
        result = await mcp_server.mcp.get_prompt(
            "document",
            {"target": "src/", "style": "module docstrings"},
        )

        message_text = result.messages[0].content.text
        assert "Target: src/" in message_text
        assert "Preferred style: module docstrings" in message_text

    async def test_security_prompt_renders_focus(self):
        result = await mcp_server.mcp.get_prompt(
            "security",
            {"target": "src/", "focus": "injection vectors"},
        )

        message_text = result.messages[0].content.text
        assert "Target: src/" in message_text
        assert "Focus: injection vectors" in message_text
        assert "injection vectors" in message_text

    async def test_prompt_arguments_expose_user_friendly_target_name(self):
        prompts = await mcp_server.mcp.list_prompts()
        prompt_by_name = {prompt.name: prompt for prompt in prompts}

        assert prompt_by_name["review"].arguments[0].name == "target"
        assert prompt_by_name["review"].arguments[0].description == "File or directory to review"
        assert prompt_by_name["commit"].arguments[0].name == "target"

    async def test_all_workflow_prompts_have_language_argument(self):
        prompts = await mcp_server.mcp.list_prompts()
        prompt_by_name = {prompt.name: prompt for prompt in prompts}

        for name in [
            "review",
            "optimize",
            "orchestrate",
            "agent_loop",
            "quality",
            "test",
            "todo",
            "explain",
            "commit",
            "compact",
            "shadow",
            "benchmark",
            "platform",
            "refactor",
            "debug",
            "document",
            "security",
        ]:
            arg_names = [a.name for a in prompt_by_name[name].arguments]
            assert "language" in arg_names, f"{name} prompt should expose language argument"
