"""Integration test configuration and fixtures."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Generator

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_project_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_audit_dir(temp_project_dir: Path) -> Path:
    audit_dir = temp_project_dir / ".audit"
    audit_dir.mkdir(exist_ok=True)
    os.environ["CLAUDE_BRIDGE_AUDIT_DIR"] = str(audit_dir)
    yield audit_dir
    if "CLAUDE_BRIDGE_AUDIT_DIR" in os.environ:
        del os.environ["CLAUDE_BRIDGE_AUDIT_DIR"]


@pytest.fixture
def sample_project_structure(temp_project_dir: Path) -> Path:
    src = temp_project_dir / "src"
    src.mkdir()
    (src / "__init__.py").write_text("")
    (src / "main.py").write_text(
        'def main():\\n    print("hello")\\n\\nif __name__ == "__main__":\\n    main()\\n'
    )
    tests = temp_project_dir / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    (tests / "test_main.py").write_text(
        "from src.main import main\\n\\n\\ndef test_main():\\n    main()\\n"
    )
    pyproject = temp_project_dir / "pyproject.toml"
    pyproject.write_text("[project]\\nname = 'sample'\\nversion = '0.1.0'\\n")
    return temp_project_dir


@pytest.fixture
def clean_server_state():
    from claude_bridge import server as mcp_server

    original_config = mcp_server.set_config
    return original_config


class MockAIProvider:
    """Mock AI provider for testing."""

    def __init__(self, responses: list[dict[str, Any]] | None = None):
        self.responses = responses or [{"content": [{"text": "ok"}]}]
        self.call_count = 0
        self.last_request = None

    async def complete(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        self.call_count += 1
        self.last_request = {"prompt": prompt, **kwargs}
        response = (
            self.responses[self.call_count - 1] if self.responses else {"content": [{"text": "ok"}]}
        )
        return response

    def reset(self) -> None:
        self.call_count = 0
        self.last_request = None


@pytest.fixture
def mock_ai_provider() -> MockAIProvider:
    return MockAIProvider()


@pytest.fixture
def mock_shell_response() -> dict[str, Any]:
    return {
        "stdout": "test output",
        "stderr": "",
        "exit_code": 0,
    }


@pytest.fixture
def integration_config() -> dict[str, Any]:
    return {
        "project_dir": Path.cwd(),
        "allowed_roots": [Path.cwd()],
        "auto_approve": True,
        "shell_timeout": 30,
    }
