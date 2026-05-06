"""Tests for workflow tools."""

import json
from pathlib import Path  # noqa: F401

import pytest  # noqa: F401

from claude_bridge import server as mcp_server
from claude_bridge import workflow_agent_loop as wf_agent_loop
from claude_bridge import workflow_tools as wf


def parse_payload(result: str) -> dict:
    return json.loads(result)


class TestDetectProjectType:
    def test_python_project(self, temp_project):
        (temp_project / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        assert wf.detect_project_type(temp_project, temp_project) == "python"

    def test_node_project(self, temp_project):
        (temp_project / "package.json").write_text('{"name": "test"}')
        assert wf.detect_project_type(temp_project, temp_project) == "node"

    def test_rust_project(self, temp_project):
        (temp_project / "Cargo.toml").write_text("[package]\nname = 'test'")
        assert wf.detect_project_type(temp_project, temp_project) == "rust"

    def test_go_project(self, temp_project):
        (temp_project / "go.mod").write_text("module example.com/test")
        assert wf.detect_project_type(temp_project, temp_project) == "go"

    def test_unknown_project(self, temp_project):
        assert wf.detect_project_type(temp_project, temp_project) == "unknown"


class TestBuildContextPack:
    async def test_build_context_pack_for_file(self, temp_project):
        src = temp_project / "src"
        src.mkdir()
        (src / "main.py").write_text("print('hello')")
        payload = parse_payload(
            await mcp_server.build_context_pack(target="src/main.py", goal="understand main")
        )
        assert payload["ok"] is True
        assert any("main.py" in f for f in payload["details"]["selected_files"])

    async def test_build_context_pack_with_tests(self, temp_project):
        (temp_project / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        tests = temp_project / "tests"
        tests.mkdir()
        (tests / "test_main.py").write_text("def test_main(): pass")
        (temp_project / "main.py").write_text("print('hello')")
        payload = parse_payload(
            await mcp_server.build_context_pack(
                target=".", goal="understand tests", include_tests=True
            )
        )
        assert payload["ok"] is True
        assert any("test_main.py" in f for f in payload["details"]["test_files"])


class TestSuggestValidationCommands:
    def test_python_validation(self, temp_project):
        (temp_project / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        commands = wf.suggest_validation_commands(temp_project, temp_project)
        assert "python3 -m pytest" in commands
        assert "git diff" in commands

    def test_rust_validation(self, temp_project):
        (temp_project / "Cargo.toml").write_text("[package]\nname = 'test'")
        commands = wf.suggest_validation_commands(temp_project, temp_project)
        assert "cargo test" in commands
        assert "git diff" in commands


class TestRunAgentLoopStep:
    async def test_agent_loop_step_patch_and_validate(self, temp_project, monkeypatch):
        test_file = temp_project / "module.py"
        test_file.write_text("def old_name():\n    return 1\n")
        monkeypatch.setattr(wf_agent_loop, "_validation_command_error", lambda cmd: None)
        payload = parse_payload(
            await mcp_server.run_agent_loop_step(
                file="module.py",
                search="old_name",
                replace="new_name",
                validation_command="echo ok",
                iteration=1,
                max_iterations=3,
            )
        )
        assert payload["ok"] is True
        assert payload["details"]["patch_result"]["ok"] is True
        assert payload["details"]["decision"] == "stop_success"
        assert "new_name" in test_file.read_text()

    async def test_agent_loop_step_invalid_iteration(self, temp_project):
        payload = parse_payload(
            await mcp_server.run_agent_loop_step(
                file="module.py",
                search="x",
                replace="y",
                validation_command="git diff",
                iteration=0,
                max_iterations=3,
            )
        )
        assert payload["ok"] is False
        assert payload["code"] == "invalid_iteration"

    async def test_agent_loop_step_validation_fails_no_continue_budget(
        self, temp_project, monkeypatch
    ):
        test_file = temp_project / "module.py"
        test_file.write_text("def old_name():\n    return 1\n")
        monkeypatch.setattr(wf_agent_loop, "_validation_command_error", lambda cmd: None)
        payload = parse_payload(
            await mcp_server.run_agent_loop_step(
                file="module.py",
                search="old_name",
                replace="new_name",
                validation_command="false",
                iteration=3,
                max_iterations=3,
            )
        )
        assert payload["ok"] is True
        assert payload["details"]["patch_result"]["ok"] is True
        assert payload["details"]["decision"] == "stop_failure"


class TestRunAgentLoopSession:
    async def test_agent_loop_session_two_steps_success(self, temp_project, monkeypatch):
        test_file = temp_project / "module.py"
        test_file.write_text("def fn_a():\n    return 'a'\n\ndef fn_b():\n    return 'b'\n")
        monkeypatch.setattr(wf_agent_loop, "_validation_command_error", lambda cmd: None)
        steps = [
            {
                "file": "module.py",
                "search": "fn_a",
                "replace": "patched_a",
                "validation_command": "false",
            },
            {
                "file": "module.py",
                "search": "fn_b",
                "replace": "patched_b",
                "validation_command": "echo ok",
            },
        ]
        payload = parse_payload(
            await mcp_server.run_agent_loop_session(steps=steps, max_iterations=5)
        )
        assert payload["ok"] is True
        assert payload["details"]["final_decision"] == "stop_success"
        assert payload["details"]["executed_steps"] == 2
