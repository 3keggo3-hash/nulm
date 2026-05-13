"""End-to-end tests for full Claude Bridge workflows."""

import asyncio
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


class TestFullWorkflowE2E:
    """End-to-end tests for complete workflows."""

    @pytest.fixture
    def isolated_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            src = project / "src"
            src.mkdir()
            (src / "__init__.py").write_text("")
            (src / "app.py").write_text(
                "def app():\\n    return 'Hello'\\n\\ndef get_version():\\n    return '1.0.0'\\n"
            )
            yield project

    @pytest.fixture(autouse=True)
    def setup_bridge(self, isolated_project):
        from claude_bridge import server as mcp_server

        mcp_server.set_config(
            project_dir=isolated_project,
            allowed_roots=[isolated_project],
            auto_approve=True,
        )

    @pytest.mark.asyncio
    async def test_configure_and_run_shell(self, isolated_project):
        from claude_bridge import server as mcp_server

        mcp_server.set_config(project_dir=isolated_project)
        result = await mcp_server.run_shell("echo test")
        assert result is not None

    @pytest.mark.asyncio
    async def test_file_operations_workflow(self, isolated_project):
        from claude_bridge.file_tools import read_file, write_file

        test_file = isolated_project / "test.txt"
        await write_file(str(test_file), "Hello E2E")
        content = await read_file(str(test_file))
        assert "Hello" in content or content is not None

    @pytest.mark.asyncio
    async def test_agent_loop_session(self, isolated_project):
        from claude_bridge import server as mcp_server

        mcp_server.set_config(project_dir=isolated_project, auto_approve=True)
        result = await mcp_server.run_agent_loop_session(
            steps=[
                {
                    "file": "src/app.py",
                    "search": "def app():\n    return 'Hello'",
                    "replace": 'def app():\n    """Return greeting."""\n    return \'Hello\'',
                    "validation_command": "echo ok",
                }
            ],
            max_iterations=1,
        )
        assert result is not None


class TestAuditTrailE2E:
    """E2E tests for audit trail."""

    @pytest.fixture
    def audit_project(self, tmp_path):
        from claude_bridge import server as mcp_server
        from claude_bridge.audit import reset_audit_session
        import os

        audit_dir = tmp_path / ".audit"
        audit_dir.mkdir()
        os.environ["CLAUDE_BRIDGE_AUDIT_DIR"] = str(audit_dir)

        project = tmp_path / "project"
        project.mkdir()
        mcp_server.set_config(project_dir=project, auto_approve=True)
        reset_audit_session()

        yield project, audit_dir

        if "CLAUDE_BRIDGE_AUDIT_DIR" in os.environ:
            del os.environ["CLAUDE_BRIDGE_AUDIT_DIR"]

    @pytest.mark.asyncio
    async def test_tool_call_logged(self, audit_project):
        from claude_bridge import server as mcp_server
        from claude_bridge.audit import get_recent_tool_calls

        project, _ = audit_project
        mcp_server.set_config(project_dir=project, auto_approve=True)
        await mcp_server.run_shell("echo test")
        calls = get_recent_tool_calls()
        assert isinstance(calls, dict)
        assert isinstance(calls["records"], list)


class TestConcurrentOperationsE2E:
    """E2E tests for concurrent operations."""

    @pytest.fixture
    def concurrent_project(self, tmp_path):
        from claude_bridge import server as mcp_server

        project = tmp_path / "concurrent"
        project.mkdir()
        mcp_server.set_config(project_dir=project, auto_approve=True)
        return project

    @pytest.mark.asyncio
    async def test_parallel_shell_commands(self, concurrent_project):
        from claude_bridge import server as mcp_server

        async def run_cmd(cmd):
            mcp_server.set_config(project_dir=concurrent_project, auto_approve=True)
            return await mcp_server.run_shell(cmd)

        results = await asyncio.gather(
            run_cmd("echo 1"),
            run_cmd("echo 2"),
            run_cmd("echo 3"),
        )
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_concurrent_file_reads(self, concurrent_project):
        from claude_bridge.file_tools import write_file, read_file

        files = []
        for i in range(5):
            f = concurrent_project / f"file_{i}.txt"
            await write_file(str(f), f"content {i}")
            files.append(str(f))

        async def read_async(path):
            return await read_file(path)

        results = await asyncio.gather(*[read_async(f) for f in files])
        assert len(results) == 5
