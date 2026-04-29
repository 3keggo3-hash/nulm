"""Shared test helpers."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from claude_bridge import server as mcp_server


def parse_payload(result: str) -> dict:
    return json.loads(result)


class FakeTSNode:
    def __init__(
        self,
        node_type: str,
        text: str = "",
        *,
        children: list["FakeTSNode"] | None = None,
        fields: dict[str, "FakeTSNode"] | None = None,
    ) -> None:
        self.type = node_type
        self._text = text
        self.children = children or []
        self._fields = fields or {}
        self.start_byte = 0
        self.end_byte = len(text.encode("utf-8"))

    def child_by_field_name(self, name: str):
        return self._fields.get(name)


@pytest.fixture
def temp_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        mcp_server.set_config(project_dir=project, auto_approve=True)
        yield project
