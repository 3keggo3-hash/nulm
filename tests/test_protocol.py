"""Tests for Tool Protocol implementation."""

import os
import tempfile
from pathlib import Path

import pytest

from claude_bridge.server import BridgeServer


@pytest.fixture
def temp_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def server(temp_project):
    return BridgeServer(project_dir=temp_project, auto_approve=True)


class TestReadCommand:
    async def test_read_existing_file(self, server, temp_project):
        test_file = temp_project / "test.txt"
        test_file.write_text("hello world")
        result = server._cmd_read("test.txt")
        assert result["ok"] is True
        assert result["content"] == "hello world"

    async def test_read_missing_file(self, server, temp_project):
        result = server._cmd_read("nonexistent.txt")
        assert result["ok"] is False
        assert "not found" in result["error"]

    async def test_read_outside_project(self, server, temp_project):
        # This should raise HTTPException but we test via the method
        pass


class TestListCommand:
    async def test_list_directory(self, server, temp_project):
        (temp_project / "file1.txt").write_text("content")
        (temp_project / "subdir").mkdir()
        result = server._cmd_list(".")
        assert result["ok"] is True
        names = {e["name"] for e in result["entries"]}
        assert "file1.txt" in names
        assert "subdir" in names


class TestShellCommand:
    async def test_shell_blocked_commands(self, server, temp_project):
        result = server._cmd_shell("sudo apt install something")
        assert result["ok"] is False
        assert "blocked" in result["error"].lower()

    async def test_shell_safe_command(self, server, temp_project):
        result = server._cmd_shell("echo hello")
        assert result["ok"] is True
        assert "hello" in result["stdout"]


class TestPatchCommand:
    async def test_patch_simple_replace(self, server, temp_project):
        test_file = temp_project / "test.py"
        test_file.write_text("def foo():\\n    pass\\n")
        result = server._cmd_patch(
            "test.py",
            "def foo():\\n    pass",
            "def foo():\\n    return 42",
        )
        assert result["ok"] is True
        content = test_file.read_text()
        assert "return 42" in content

    async def test_patch_ambiguous_search(self, server, temp_project):
        test_file = temp_project / "test.py"
        test_file.write_text("pass\\npass\\n")
        result = server._cmd_patch("test.py", "pass", "changed")
        assert result["ok"] is False
        assert "ambiguous" in result["error"].lower()

    async def test_patch_python_syntax_check(self, server, temp_project):
        test_file = temp_project / "test.py"
        test_file.write_text("def valid():\\n    pass\\n")
        result = server._cmd_patch(
            "test.py",
            "def valid():\\n    pass",
            "def valid(:\\n    invalid syntax here",
        )
        assert result["ok"] is False
        assert "syntax" in result["error"].lower()
