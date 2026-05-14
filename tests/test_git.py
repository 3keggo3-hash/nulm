"""Tests for git integration."""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from claude_bridge import server as mcp_server
from claude_bridge.git_tool_server import register_git_tools
from claude_bridge.meta_agent_server import register_meta_agent_tools


def parse_payload(result: str) -> dict:
    return json.loads(result)


class FakeMcp:
    def tool(self, **_kwargs):
        def decorator(fn):
            return fn

        return decorator


def tool_options(
    _description: str,
    *,
    read_only: bool = False,
    destructive: bool = False,
    open_world: bool = False,
) -> dict:
    return {}


def audit_passthrough(_name: str, _params: dict, result: str, *, started_at: float) -> str:
    return result


@pytest.fixture
def git_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        subprocess.run(["git", "init"], cwd=project, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=project,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=project,
            capture_output=True,
            check=True,
        )
        mcp_server.set_config(project_dir=project, auto_approve=True)
        yield project


@pytest.fixture
def no_git_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        mcp_server.set_config(project_dir=project, auto_approve=True)
        yield project


class TestGitIntegration:
    """Test git auto-commit functionality."""

    async def test_git_commit_after_patch(self, git_project):
        test_file = git_project / "test.py"
        test_file.write_text("def foo():\n    pass")

        subprocess.run(["git", "add", "."], cwd=git_project, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"], cwd=git_project, capture_output=True, check=True
        )

        result = await mcp_server.patch_file(
            file="test.py",
            search="def foo():\n    pass",
            replace="def foo():\n    return 42",
        )

        payload = parse_payload(result)
        assert payload["ok"] is True
        assert "Patched" in payload["message"]
        log_result = subprocess.run(
            ["git", "log", "--oneline"], cwd=git_project, capture_output=True, text=True
        )
        assert "bridge: update" in log_result.stdout
        assert "return 42" in test_file.read_text()

    async def test_auto_git_init(self, no_git_project):
        test_file = no_git_project / "test.py"
        test_file.write_text("x = 1")

        result = await mcp_server.patch_file(file="test.py", search="x = 1", replace="x = 2")

        payload = parse_payload(result)
        assert payload["ok"] is True
        assert "Patched" in payload["message"]
        assert not (no_git_project / ".git").exists()

    async def test_git_commit_message_contains_filename(self, git_project):
        test_file = git_project / "my_module.py"
        test_file.write_text("def func(): pass")

        await mcp_server.patch_file(
            file="my_module.py",
            search="def func(): pass",
            replace="def func(): return None",
        )

        log_result = subprocess.run(
            ["git", "log", "-1", "--pretty=format:%s"],
            cwd=git_project,
            capture_output=True,
            text=True,
        )
        assert "my_module.py" in log_result.stdout

    async def test_patch_reports_git_commit_warning(self, git_project, monkeypatch):
        test_file = git_project / "test.py"
        test_file.write_text("x = 1")

        monkeypatch.setattr(
            mcp_server,
            "_git_commit",
            lambda file_path, project_dir=None: {
                "init": True,
                "add": True,
                "commit": False,
                "output": "missing git config",
            },
        )

        payload = parse_payload(
            await mcp_server.patch_file(file="test.py", search="x = 1", replace="x = 2")
        )

        assert payload["ok"] is True
        assert "git commit failed" in payload["message"].lower()
        assert payload["details"]["git"]["commit"] is False

    async def test_patch_uses_active_subproject_git_root(self, no_git_project):
        desktop_root = no_git_project / "Desktop"
        desktop_root.mkdir()
        tertis_dir = desktop_root / "tertis"
        tertis_dir.mkdir()
        test_file = tertis_dir / "grid_manager.gd"
        test_file.write_text("const GRID_SIZE := 5\n")

        mcp_server.set_config(
            project_dir=tertis_dir,
            allowed_roots=[no_git_project, desktop_root],
            auto_approve=True,
        )

        payload = parse_payload(
            await mcp_server.patch_file(
                file="grid_manager.gd",
                search="const GRID_SIZE := 5",
                replace="const GRID_SIZE := 6",
            )
        )

        assert payload["ok"] is True
        assert not (tertis_dir / ".git").exists()
        assert not (desktop_root / ".git").exists()

    async def test_patch_does_not_change_active_project_root(self, no_git_project):
        desktop_root = no_git_project / "Desktop"
        desktop_root.mkdir()
        tertis_dir = desktop_root / "tertis"
        tertis_dir.mkdir()
        test_file = tertis_dir / "grid_manager.gd"
        test_file.write_text("const GRID_SIZE := 5\n")

        mcp_server.set_config(
            project_dir=no_git_project,
            allowed_roots=[no_git_project, desktop_root],
            auto_approve=True,
        )

        payload = parse_payload(
            await mcp_server.patch_file(
                file=str(test_file),
                search="const GRID_SIZE := 5",
                replace="const GRID_SIZE := 6",
            )
        )

        assert payload["ok"] is True
        assert mcp_server.current_config()["project_dir"] == no_git_project.resolve()

    async def test_undo_last_patch_restores_previous_content(self, git_project):
        test_file = git_project / "test.py"
        test_file.write_text("x = 1\n")

        payload = parse_payload(
            await mcp_server.patch_file(file="test.py", search="x = 1", replace="x = 2")
        )
        assert payload["ok"] is True
        assert test_file.read_text() == "x = 2\n"

        preview = parse_payload(await mcp_server.undo_last_patch())
        assert preview["ok"] is False
        assert preview["code"] == "confirmation_required"

        undo_payload = parse_payload(await mcp_server.undo_last_patch(confirm=True))
        assert undo_payload["ok"] is True
        assert test_file.read_text() == "x = 1\n"

        log_result = subprocess.run(
            ["git", "log", "-1", "--pretty=format:%s"],
            cwd=git_project,
            capture_output=True,
            text=True,
        )
        assert log_result.stdout == "bridge: undo test.py"

    async def test_undo_last_patch_removes_new_file_from_write(self, git_project):
        payload = parse_payload(
            await mcp_server.write_file("notes.txt", "hello from bridge", overwrite=False)
        )
        assert payload["ok"] is True
        assert (git_project / "notes.txt").exists()

        undo_payload = parse_payload(await mcp_server.undo_last_patch(confirm=True))
        assert undo_payload["ok"] is True
        assert not (git_project / "notes.txt").exists()

    async def test_undo_last_patch_requires_approval(self, git_project):
        test_file = git_project / "test.py"
        test_file.write_text("x = 1\n")

        payload = parse_payload(
            await mcp_server.patch_file(file="test.py", search="x = 1", replace="x = 2")
        )
        assert payload["ok"] is True

        mcp_server.apply_config(
            project_dir=git_project,
            allowed_roots=[git_project],
            auto_approve=False,
            client_managed_approval=False,
            shell_timeout=30,
        )

        undo_payload = parse_payload(await mcp_server.undo_last_patch(confirm=True))
        assert undo_payload["ok"] is False
        assert undo_payload["code"] == "approval_rejected"

    async def test_commit_changes_requires_approval_when_not_client_managed(self, git_project):
        mcp_server.set_config(
            project_dir=git_project,
            auto_approve=False,
            client_managed_approval=False,
        )
        tools = register_git_tools(
            mcp=FakeMcp(),
            tool_options=tool_options,
            audit_tool_call=audit_passthrough,
            json_response=mcp_server._json_response,
            project_dir=lambda: git_project,
            enabled_names={"commit_changes"},
        )

        payload = parse_payload(await tools["commit_changes"]("test commit"))

        assert payload["ok"] is False
        assert payload["code"] == "approval_rejected"

    async def test_checkpoint_tools_require_approval_when_not_client_managed(self, git_project):
        mcp_server.set_config(
            project_dir=git_project,
            auto_approve=False,
            client_managed_approval=False,
        )

        def should_not_run(**_kwargs):
            raise AssertionError("checkpoint implementation should not run")

        tools = register_meta_agent_tools(
            mcp=FakeMcp(),
            tool_options=tool_options,
            audit_tool_call=audit_passthrough,
            json_response=mcp_server._json_response,
            create_plan_impl=lambda **_kwargs: {"ok": True},
            execute_step_impl=lambda **_kwargs: {"ok": True},
            get_plan_status_impl=lambda **_kwargs: {"ok": True},
            explore_approaches_impl=lambda **_kwargs: {"ok": True},
            execute_approach_impl=lambda **_kwargs: {"ok": True},
            compare_approaches_impl=lambda **_kwargs: {"ok": True},
            self_critique_impl=lambda **_kwargs: {"ok": True},
            create_checkpoint_impl=should_not_run,
            restore_checkpoint_impl=should_not_run,
            list_checkpoints_impl=lambda **_kwargs: {"ok": True},
            enabled_names={"create_checkpoint", "restore_checkpoint"},
        )

        create_payload = parse_payload(await tools["create_checkpoint"]("before-risky-change"))
        restore_payload = parse_payload(await tools["restore_checkpoint"]("before-risky-change"))

        assert create_payload["ok"] is False
        assert create_payload["code"] == "approval_rejected"
        assert restore_payload["ok"] is False
        assert restore_payload["code"] == "approval_rejected"

    async def test_set_config_clears_undo_snapshot_state(self, git_project):
        test_file = git_project / "test.py"
        test_file.write_text("x = 1\n")

        payload = parse_payload(
            await mcp_server.patch_file(file="test.py", search="x = 1", replace="x = 2")
        )
        assert payload["ok"] is True

        mcp_server.set_config(project_dir=git_project, auto_approve=True)

        undo_payload = parse_payload(await mcp_server.undo_last_patch(confirm=True))
        assert undo_payload["ok"] is False
        assert undo_payload["code"] == "no_undo_state"


class TestGitErrorHandling:
    """Test git error scenarios."""

    async def test_git_function_exposed(self, git_project):
        """Internal _git_commit returns a dict with init/add/commit keys."""
        result = mcp_server._git_commit("test.py")
        assert "init" in result
        assert "add" in result
        assert "commit" in result

    async def test_undo_last_patch_without_state_returns_structured_error(self, git_project):
        payload = parse_payload(await mcp_server.undo_last_patch(confirm=True))
        assert payload["ok"] is False
        assert payload["code"] == "no_undo_state"

    async def test_git_commit_returns_failure_dict_for_path_outside_repo(self, git_project):
        outside_file = git_project.parent / "outside.py"
        outside_file.write_text("x = 1\n")

        result = mcp_server._git_commit(str(outside_file), project_dir=git_project)

        assert result["add"] is False
        assert result["commit"] is False
        assert "outside git repo root" in result["output"]
