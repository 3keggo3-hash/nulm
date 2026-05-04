"""Tests for workflow tools."""

import json
from pathlib import Path  # noqa: F401

import pytest  # noqa: F401

from claude_bridge import server as mcp_server
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

    def test_no_files_unknown(self, temp_project):
        assert wf.detect_project_type(temp_project, temp_project) == "unknown"


class TestSuggestValidationCommands:
    async def test_suggest_for_python(self, temp_project):
        (temp_project / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        payload = parse_payload(await mcp_server.suggest_validation_commands("."))
        assert payload["ok"] is True
        assert payload["details"]["project_type"] == "python"
        cmds = payload["details"]["validation_commands"]
        assert "python3 -m pytest" in cmds
        assert "git diff" in cmds

    async def test_suggest_for_node(self, temp_project):
        (temp_project / "package.json").write_text('{"name": "test"}')
        payload = parse_payload(await mcp_server.suggest_validation_commands("."))
        assert payload["ok"] is True
        assert payload["details"]["project_type"] == "node"
        cmds = payload["details"]["validation_commands"]
        assert any("npm test" in cmd for cmd in cmds)

    async def test_suggest_for_rust(self, temp_project):
        (temp_project / "Cargo.toml").write_text("[package]\nname = 'test'")
        payload = parse_payload(await mcp_server.suggest_validation_commands("."))
        assert payload["ok"] is True
        assert payload["details"]["project_type"] == "rust"
        cmds = payload["details"]["validation_commands"]
        assert any("cargo test" in cmd for cmd in cmds)


class TestBuildContextPack:
    async def test_build_context_pack_for_file(self, temp_project):
        (temp_project / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        src = temp_project / "src"
        src.mkdir()
        (src / "main.py").write_text("def hello():\n    return 'hello'\n")
        payload = parse_payload(
            await mcp_server.build_context_pack(
                target="src/main.py",
                goal="understand the main module",
                include_tests=False,
                include_git_diff=False,
                include_docs=False,
            )
        )
        assert payload["ok"] is True
        assert payload["details"]["project_type"] == "python"
        assert "src/main.py" in payload["details"]["selected_files"]
        assert payload["details"]["target"] == "src/main.py"
        assert payload["details"]["goal"] == "understand the main module"
        assert "validation_commands" in payload["details"]
        assert payload["details"]["cached"] is False

    async def test_build_context_pack_with_tests(self, temp_project):
        (temp_project / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        pkg = temp_project / "pkg"
        pkg.mkdir()
        (pkg / "auth.py").write_text("def login():\n    return True\n")
        tests = temp_project / "tests"
        tests.mkdir()
        (tests / "test_auth.py").write_text("from pkg.auth import login\n\ndef test_login():\n    assert login()\n")
        payload = parse_payload(
            await mcp_server.build_context_pack(
                target="pkg/auth.py",
                goal="review auth flow",
                include_tests=True,
                include_git_diff=False,
                include_docs=False,
            )
        )
        assert payload["ok"] is True
        assert payload["details"]["project_type"] == "python"
        assert "pkg/auth.py" in payload["details"]["selected_files"]
        test_files = payload["details"]["test_files"]
        assert any("test_auth.py" in tf for tf in test_files)


class TestRunWorkflow:
    async def test_run_workflow_review_mode(self, temp_project):
        (temp_project / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        src = temp_project / "src"
        src.mkdir()
        (src / "main.py").write_text("def hello():\n    return 'hello'\n")
        payload = parse_payload(
            await mcp_server.run_workflow(mode="review", target="src/main.py")
        )
        assert payload["ok"] is True
        assert payload["details"]["mode"] == "review"
        assert payload["details"]["project_type"] == "python"
        assert "prompt" in payload["details"]
        assert "steps" in payload["details"]

    async def test_run_workflow_explain_mode(self, temp_project):
        (temp_project / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        src = temp_project / "src"
        src.mkdir()
        (src / "main.py").write_text("def hello():\n    return 'hello'\n")
        payload = parse_payload(
            await mcp_server.run_workflow(mode="explain", target="src/main.py")
        )
        assert payload["ok"] is True
        assert payload["details"]["mode"] == "explain"

    async def test_run_workflow_with_execute(self, temp_project):
        (temp_project / "pyproject.toml").write_text("[project]\nname = 'test'\n")
        src = temp_project / "src"
        src.mkdir()
        (src / "main.py").write_text("def hello():\n    return 'hello'\n")
        payload = parse_payload(
            await mcp_server.run_workflow(
                mode="review", target="src/main.py", execute=True
            )
        )
        assert payload["ok"] is True
        assert payload["details"]["execute"] is True
        assert "execution" in payload["details"]


class TestRunAgentLoopStep:
    async def test_agent_loop_step_patch_and_validate(self, temp_project, monkeypatch):
        test_file = temp_project / "module.py"
        test_file.write_text("def old_name():\n    return 1\n")
        monkeypatch.setattr(wf, "_validation_command_error", lambda cmd: None)
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
        monkeypatch.setattr(wf, "_validation_command_error", lambda cmd: None)
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
        test_file.write_text(
            "def fn_a():\n    return 'a'\n\ndef fn_b():\n    return 'b'\n"
        )
        monkeypatch.setattr(wf, "_validation_command_error", lambda cmd: None)
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
        assert payload["details"]["executed_steps"] == 2
        assert payload["details"]["final_decision"] == "stop_success"
        content = test_file.read_text()
        assert "patched_a" in content
        assert "patched_b" in content
        assert "module.py" in payload["details"]["session_summary"]["files_touched"]
