"""Tests for project insight tools: stats, todo scan, recent files, language distribution, git log."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


import json
import subprocess
from claude_bridge import server as mcp_server


def parse_payload(result: str) -> dict:
    return json.loads(result)


class TestProjectInsights:
    async def test_project_stats_python_files(self, temp_project):
        src = temp_project / "src"
        src.mkdir()
        (src / "main.py").write_text("import os\n\n\ndef main():\n    pass\n")
        (src / "utils.py").write_text("def helper():\n    return True\n")

        payload = parse_payload(await mcp_server.project_insights("."))
        assert payload["ok"] is True
        assert payload["details"]["total_files"] >= 2
        assert payload["details"]["total_code_lines"] >= 5
        assert any(lang["language"] == "Python" for lang in payload["details"]["languages"])

    async def test_project_stats_counts_lines_and_files(self, temp_project):
        (temp_project / "module.py").write_text("x = 1\ny = 2\nz = 3\n")

        payload = parse_payload(await mcp_server.project_insights("."))
        assert payload["ok"] is True
        assert payload["details"]["total_files"] == 1
        assert payload["details"]["total_code_lines"] == 3

    async def test_project_stats_rejects_file_path(self, temp_project):
        (temp_project / "data.txt").write_text("hello")
        payload = parse_payload(await mcp_server.project_insights("data.txt"))
        assert payload["ok"] is False
        assert payload["code"] == "not_a_directory"


class TestTodoScan:
    async def test_todo_scan_finds_markers(self, temp_project):
        src = temp_project / "src"
        src.mkdir()
        (src / "auth.py").write_text("# TODO: implement login flow\n")
        (src / "parser.py").write_text("def parse():\n    # FIXME: handle edge cases\n    pass\n")
        (src / "utils.py").write_text("x = 1  # HACK: temporary workaround\n")

        payload = parse_payload(await mcp_server.todo_scan("."))
        assert payload["ok"] is True
        assert payload["details"]["total_markers"] >= 3
        tags = {f["tag"] for f in payload["details"]["findings"]}
        assert "TODO" in tags
        assert "FIXME" in tags
        assert "HACK" in tags

    async def test_todo_scan_returns_counts_by_tag(self, temp_project):
        (temp_project / "app.py").write_text("# TODO: a\n# TODO: b\n# FIXME: c\n")

        payload = parse_payload(await mcp_server.todo_scan("."))
        by_tag = {item["tag"]: item["count"] for item in payload["details"]["by_tag"]}
        assert by_tag.get("TODO") == 2
        assert by_tag.get("FIXME") == 1

    async def test_todo_scan_empty_project(self, temp_project):
        payload = parse_payload(await mcp_server.todo_scan("."))
        assert payload["ok"] is True
        assert payload["details"]["total_markers"] == 0


class TestRecentFiles:
    async def test_recent_files_lists_newly_created(self, temp_project):
        (temp_project / "new.py").write_text("print('hello')\n")
        (temp_project / "old.js").write_text("const x = 1;\n")

        payload = parse_payload(await mcp_server.recent_files(".", limit=10))
        assert payload["ok"] is True
        filenames = [entry["file"] for entry in payload["details"]["recent"]]
        assert "new.py" in filenames
        assert "old.js" in filenames

    async def test_recent_files_respects_limit(self, temp_project):
        for i in range(5):
            (temp_project / f"file_{i}.py").write_text(f"# file {i}\n")

        payload = parse_payload(await mcp_server.recent_files(".", limit=2))
        assert payload["ok"] is True
        assert len(payload["details"]["recent"]) <= 2

    async def test_recent_files_includes_size_and_extension(self, temp_project):
        (temp_project / "data.py").write_text("x = 1\n")

        payload = parse_payload(await mcp_server.recent_files(".", limit=5))
        entry = payload["details"]["recent"][0]
        assert "size" in entry
        assert "size_human" in entry
        assert "modified" in entry


class TestLanguageDistribution:
    async def test_language_distribution_python_and_js(self, temp_project):
        (temp_project / "app.py").write_text("def main():\n    pass\n")
        (temp_project / "helper.js").write_text("function helper() {}\n")

        payload = parse_payload(await mcp_server.language_distribution("."))
        assert payload["ok"] is True
        langs = {item["language"]: item for item in payload["details"]["languages"]}
        assert "Python" in langs
        assert "JavaScript" in langs
        assert langs["Python"]["files"] == 1
        assert langs["JavaScript"]["files"] == 1

    async def test_language_distribution_shows_percent_and_dominant(self, temp_project):
        (temp_project / "main.py").write_text("x = 1\n")

        payload = parse_payload(await mcp_server.language_distribution("."))
        assert payload["ok"] is True
        assert payload["details"]["dominant"] == "Python"
        assert payload["details"]["languages"][0]["percent"] == 100.0

    async def test_language_distribution_empty_project(self, temp_project):
        payload = parse_payload(await mcp_server.language_distribution("."))
        assert payload["ok"] is True
        assert payload["details"]["languages"] == []
        assert "dominant" not in payload["details"]


class TestGitInsights:
    async def test_git_log_summary_init_and_commit(self, temp_project):
        subprocess.run(["git", "init"], cwd=temp_project, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=temp_project,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=temp_project,
            capture_output=True,
        )
        (temp_project / "main.py").write_text("print('hello')\n")
        subprocess.run(["git", "add", "main.py"], cwd=temp_project, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=temp_project,
            capture_output=True,
        )

        payload = parse_payload(await mcp_server.git_insights(".", limit=5))
        assert payload["ok"] is True
        assert payload["details"]["total_shown"] >= 1
        commit = payload["details"]["recent_commits"][0]
        assert "hash" in commit
        assert "author" in commit
        assert "message" in commit
        assert "timestamp" in commit
        assert "contributors" in payload["details"]

    async def test_git_insights_non_git_directory(self, temp_project):
        payload = parse_payload(await mcp_server.git_insights(".", limit=5))
        assert payload["ok"] is False
        assert payload["code"] == "git_error"
        assert "error" in payload["details"]
